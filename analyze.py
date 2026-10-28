"""Crossing Watch: find pedestrian-vehicle near-misses in one video of a crossing.

Run: python3 analyze.py VIDEO SITE.json [--out DIR]
SITE.json holds four calibration points (clip pixels) and where they lie on the road (metres); see sites/.
Writes DIR/events.json and prints the most dangerous moments first.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

import listen
import render
import review
import road
import sam

EVIDENCE_CLIPS = 5
MAX_REVIEWS = 40  # Spark looks at no more pedestrians than this per run
FPS = 10
WIDTH = 640
CHUNK_FRAMES = 3_000  # 5 min per SAM request (SAM 3.1 takes up to 15,000 frames; smaller keeps uploads modest)
SAM_USD_PER_1K_FRAMES = 0.20
MAX_COST_USD = 10.0  # above this estimate, --allow-cost is required
PREP_FILTER = re.compile(r"^((crop|scale|transpose|hflip|vflip)(=[\w.*:+\-/]+)?)(,(crop|scale|transpose|hflip|vflip)(=[\w.*:+\-/]+)?)*$")


def numeric_points(points, count=None):
    return (isinstance(points, list) and (count is None or len(points) == count) and len(points) >= 3
            and all(isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p) for p in points))


def load_site(path):
    site = json.loads(Path(path).read_text())
    for key in ("image_points", "world_points"):
        if not numeric_points(site.get(key), 4):
            raise SystemExit(f"{path}: {key} must be four [x, y] number pairs")
    vehicles = site.get("vehicles")
    if not (isinstance(vehicles, list) and vehicles and all(isinstance(v, str) and v.strip() for v in vehicles)):
        raise SystemExit(f"{path}: 'vehicles' must be a list of concept names, e.g. [\"car\", \"motorcycle\"]")
    if not isinstance(site.get("person", "person"), str):
        raise SystemExit(f"{path}: 'person' must be a concept name")
    zone = site.get("zone_m")
    if zone is not None and not (isinstance(zone, list) and len(zone) == 4 and all(isinstance(v, (int, float)) for v in zone)
                                 and zone[0] < zone[2] and zone[1] < zone[3]):
        raise SystemExit(f"{path}: zone_m must be [x_min, y_min, x_max, y_max] in metres")
    if "roadway_m" in site and not numeric_points(site["roadway_m"]):
        raise SystemExit(f"{path}: roadway_m must be a polygon of at least three [x, y] points in metres")
    if site.get("view", "oblique") not in ("oblique", "top-down"):
        raise SystemExit(f"{path}: view must be \"oblique\" (a phone up high, looking across) or \"top-down\" (drone)")
    if not PREP_FILTER.match(site.get("prep_filter", "") or "crop"):
        raise SystemExit(f"{path}: prep_filter may only use crop, scale, transpose, hflip or vflip")
    return site


def check_source(video, out_dir, prep_filter):
    """Refuse to reuse an output folder (its clip and paid SAM replies) made from another video or settings."""
    stat = Path(video).stat()
    stamp = {"video": str(Path(video).resolve()), "bytes": stat.st_size, "prep_filter": prep_filter, "fps": FPS,
             "width": WIDTH, "chunk_frames": CHUNK_FRAMES}
    stamp_file = out_dir / "source.json"
    if stamp_file.exists() and json.loads(stamp_file.read_text()) != stamp:
        raise SystemExit(f"{out_dir} was made from a different video or settings; pass a new --out folder")
    stamp_file.write_text(json.dumps(stamp, indent=1))


def prepare(video, out_dir, extra_filter=""):
    """Re-encode to what SAM wants: H.264 with faststart, FPS frames a second, WIDTH pixels wide."""
    clip = out_dir / "clip.mp4"
    if clip.exists():
        return clip
    partial = out_dir / "clip.part.mp4"
    filters = ",".join(f for f in (extra_filter, f"fps={FPS}", f"scale={WIDTH}:-2") if f)
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", filters, "-an", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(partial)], check=True)
        partial.replace(clip)
    finally:
        partial.unlink(missing_ok=True)
    return clip


def frame_count(clip):
    return int(probe(clip, "stream=nb_read_packets", "-count_packets"))


def parts(clip, out_dir, total):
    """(first frame, clip, cache folder) per SAM request; long videos are cut into CHUNK_FRAMES pieces."""
    if total <= CHUNK_FRAMES:
        return [(0, clip, out_dir)]
    pieces = []
    for first in range(0, total, CHUNK_FRAMES):
        folder = out_dir / f"part{first // CHUNK_FRAMES}"
        folder.mkdir(exist_ok=True)
        piece, partial = folder / "clip.mp4", folder / "clip.part.mp4"
        if not piece.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{first / FPS:.3f}", "-i", str(clip), "-frames:v",
                            str(CHUNK_FRAMES), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                            str(partial)], check=True)
            partial.replace(piece)
        pieces.append((first, piece, folder))
    return pieces


def check_cost(pieces, concepts, total, allow):
    """Refuse a surprise bill: estimate the SAM cost of the requests not already cached."""
    todo = sum(1 for _, _, folder in pieces for c in concepts if not sam.cache_path(folder, c).exists())
    usd = todo / max(1, len(pieces) * len(concepts)) * total * len(concepts) / 1000 * SAM_USD_PER_1K_FRAMES
    print(f"{total / FPS / 60:.1f} min of video, {len(pieces)} part(s); SAM cost about ${usd:.2f}", flush=True)
    if usd > MAX_COST_USD and not allow:
        raise SystemExit(f"estimated SAM cost ${usd:.2f} is over ${MAX_COST_USD:.0f}; re-run with --allow-cost")


def track_all(pieces, concept, key):
    """One concept's tracks over all parts, frame numbers shifted back to the whole clip."""
    merged = {}
    for k, (first, piece, folder) in enumerate(pieces):
        for obj, track in sam.track(piece, concept, key, folder).items():
            merged[f"{k}:{obj}" if len(pieces) > 1 else obj] = {first + f: b for f, b in track.items()}
    return merged


def probe(path, entries, *extra):
    return subprocess.run(["ffprobe", "-v", "error", *extra, "-select_streams", "v:0", "-show_entries", entries,
                           "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True).stdout.strip()


def write_events(out_dir, site, events, seen):
    (out_dir / "events.json").write_text(json.dumps({"site": site.get("name", ""), "fps": FPS, "exposure": seen,
                                                     "events": events}, indent=1))


def road_tracks(site, H, person_boxes, vehicle_boxes, frame_size):
    """SAM boxes -> (pedestrian track pieces, vehicle shapes) in road metres, cleaned: riders dropped, tracks split
    where the ID jumps, only the analysis zone (and carriageway, if marked) kept."""
    zone = site.get("zone_m") or road.zone_around(site["world_points"])
    top_down = site.get("view") == "top-down"
    walkers = {pid: road.without_riders(t, vehicle_boxes.values()) for pid, t in person_boxes.items()}
    people = {f"{pid}/{k}": piece for pid, t in walkers.items()
              for k, piece in enumerate(road.split_at_jumps(road.moving_frames(  # stillness judged before cutting
                  road.person_points(t, H, zone, site.get("roadway_m"), frame_size, top_down), FPS), FPS))}
    vehicles = {vid: road.vehicle_edges(t, H, zone, frame_size, top_down) for vid, t in vehicle_boxes.items()}
    return people, vehicles


def piece_boxes(person_boxes, people, pid):
    """SAM boxes of just the track piece `pid` ("<sam id>/<piece>") that made an event."""
    boxes = person_boxes[pid.split("/")[0]]
    return {f: boxes[f] for f in people[pid] if f in boxes}


def review_people(clip, out_dir, events, people, person_boxes, key, frame_size, top_down):
    """Spark looks once at each pedestrian piece involved in a conflict (most dangerous first, at most
    MAX_REVIEWS), and its verdict is attached to all that piece's events."""
    verdicts = {}
    for e in events:
        pid = e["person"]
        if pid not in verdicts and len(verdicts) < MAX_REVIEWS:
            try:
                verdicts[pid] = review.review(clip, piece_boxes(person_boxes, people, pid), frame_size,
                                              out_dir / f"person-{pid.replace('/', '-')}.jpg", key, top_down)
            except (subprocess.CalledProcessError, OSError) as err:
                print(f"review of {pid} failed: {err}", flush=True)
                verdicts[pid] = None
        e["review"] = verdicts.get(pid)


def add_evidence(video, clip, out_dir, events, people, person_boxes, vehicle_boxes, key, frame_size):
    """Evidence clip and sound check for the top events Spark did not reject; one failure costs that event's
    evidence, not the run. Only the frames of the track piece that made the event are boxed."""
    kept = [e for e in events if (e.get("review") or {}).get("is_person", True)]
    for i, e in enumerate(kept[:EVIDENCE_CLIPS]):
        pair = piece_boxes(person_boxes, people, e["person"]), vehicle_boxes[e["vehicle"]]
        try:
            e["clip"] = render.render(clip, e, *pair, FPS, out_dir / f"event{i + 1}.mp4",
                                      everyone=list(person_boxes.values()), frame_size=frame_size).name
            e["heard"] = listen.listen(video, e, out_dir / f"event{i + 1}.wav", key)
        except (subprocess.CalledProcessError, OSError) as err:
            print(f"evidence for event {i + 1} failed: {err}", flush=True)


def report(seen, events):
    serious = sum(e["tier"] == "serious" for e in events)
    print(f"{seen['minutes']} min, {seen['crossings']} crossings, {seen['vehicles']} moving vehicles, 85th-percentile "
          f"speed {seen['speed_85th_kmh']} km/h; {serious} serious near-misses (PET < {road.PET_MAX_S} s), "
          f"{len(events) - serious} close passes (< {road.CLOSE_PASS_S} s)")
    for e in events:
        verdict, at20 = e.get("review") or {}, e["with_limit"]["20"]
        print(f"  [{e['tier']}] person {e['person']} / {e['vehicle']}: PET {e['pet_s']:.1f} s, {e['gap_m']} m, {e['vehicle_kmh']} km/h "
              f"(adult death risk if hit {e['death_risk_pct']}%; at a 20 km/h limit {at20['impact_kmh']} km/h, "
              f"{at20['death_risk_pct']}%), at {e['t_person_s']:.1f} s  [Spark: {verdict.get('road_user', 'not reviewed')}]")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video")
    parser.add_argument("site")
    parser.add_argument("--out", help="output folder (default out/<video name>)")
    parser.add_argument("--allow-cost", action="store_true", help=f"run even if SAM would cost over ${MAX_COST_USD:.0f}")
    args = parser.parse_args()

    site = load_site(args.site)
    out_dir = Path(args.out or Path("out") / Path(args.video).stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    check_source(args.video, out_dir, site.get("prep_filter", ""))
    clip = prepare(args.video, out_dir, site.get("prep_filter", ""))
    frame_size = tuple(int(v) for v in probe(clip, "stream=width,height").split(","))
    if site.get("frame_size") and tuple(site["frame_size"]) != frame_size:
        raise SystemExit(f"calibration was marked on a {site['frame_size']} frame but the clip is {list(frame_size)}: "
                         f"open a frame of {clip} in calibrate.html and mark the points again")
    if site.get("prep_filter") and site.get("marked_on") == "raw video frame":
        raise SystemExit(f"prep_filter changes the frame, but the points were marked on the raw video: open a frame of "
                         f"{clip} in calibrate.html, tick 'frame is from clip.mp4' and mark them again")
    H = road.homography(site["image_points"], site["world_points"])
    key = sam.load_api_key()
    total = frame_count(clip)
    pieces = parts(clip, out_dir, total)
    person_concept = site.get("person", "person")
    check_cost(pieces, [person_concept, *site["vehicles"]], total, args.allow_cost)

    person_boxes = track_all(pieces, person_concept, key)
    vehicle_boxes = {f"{concept}#{vid}": t for concept in site["vehicles"]
                     for vid, t in track_all(pieces, concept, key).items()}
    top_down = site.get("view") == "top-down"
    people, vehicles = road_tracks(site, H, person_boxes, vehicle_boxes, frame_size)
    events = road.conflicts(people, vehicles, FPS)
    seen = road.exposure(people, vehicles, FPS, total)

    write_events(out_dir, site, events, seen)  # saved before the slower, network-bound evidence step
    review_people(clip, out_dir, events, people, person_boxes, key, frame_size, top_down)
    add_evidence(args.video, clip, out_dir, events, people, person_boxes, vehicle_boxes, key, frame_size)
    write_events(out_dir, site, events, seen)
    report(seen, events)


if __name__ == "__main__":
    main()
