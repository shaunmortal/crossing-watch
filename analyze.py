"""Crossing Watch: find pedestrian-vehicle near-misses in one video of a crossing.

Run: python3 analyze.py VIDEO SITE.json [--out DIR]
SITE.json holds four calibration points (clip pixels) and where they lie on the road (metres); see sites/.
Writes DIR/events.json and prints the most dangerous moments first.
"""
import argparse
import json
import re
import statistics
import subprocess
from pathlib import Path

import crowd
import listen
import render
import review
import roadmap
import road
import sam

EVIDENCE_CLIPS = 5
MAX_REVIEWS = 40  # Spark looks at no more pedestrians than this per run
FPS = 10
WIDTH = 640
CHUNK_FRAMES = 150    # 15 s per SAM request: one request tracks at most sam.MAX_OBJECTS objects in all
OVERLAP_FRAMES = 20   # consecutive parts share 2 s, so someone crossing the cut keeps one ID
TILE_OVERLAP = 0.15   # neighbouring person tiles share this much of the frame
LINK_SHARE = 0.6      # two tracks are one object when, on shared frames, the smaller box lies this much inside the other
SAM_USD_PER_1K_FRAMES = 0.20  # SAM video, Meta's list price
SAM_USD_PER_IMAGE = 0.0025    # crowd mode: SAM images, Meta's list price of $2.50 per 1,000 images
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
    names = [sam.cache_path(Path("."), c).name.lower() for c in [site.get("person", "person"), *vehicles]]
    if len(set(names)) < len(names):
        raise SystemExit(f"{path}: two concepts have the same cache name (only letters and digits count, any case)")
    if not isinstance(site.get("person", "person"), str):
        raise SystemExit(f"{path}: 'person' must be a concept name")
    zone = site.get("zone_m")
    if zone is not None and not (isinstance(zone, list) and len(zone) == 4 and all(isinstance(v, (int, float)) for v in zone)
                                 and zone[0] < zone[2] and zone[1] < zone[3]):
        raise SystemExit(f"{path}: zone_m must be [x_min, y_min, x_max, y_max] in metres")
    if "roadway_m" in site and not numeric_points(site["roadway_m"]):
        raise SystemExit(f"{path}: roadway_m must be a polygon of at least three [x, y] points in metres")
    if "zebra_m" in site and site["zebra_m"] != [] and not numeric_points(site["zebra_m"]):
        raise SystemExit(f"{path}: zebra_m must be the marked crossing's corners as [x, y] points in metres, or [] for none")
    if "gate_m" in site and not (isinstance(site["gate_m"], list) and len(site["gate_m"]) == 2
                                 and numeric_points(site["gate_m"] * 2)):  # numeric_points wants three or more
        raise SystemExit(f"{path}: gate_m must be the gate's two posts as [x, y] points in metres")
    if site.get("person_mode", "video") not in ("video", "crowd"):
        raise SystemExit(f"{path}: person_mode must be \"video\" or \"crowd\" (frame-by-frame detection for dense crowds)")
    if site.get("vehicle_mode", "video") not in ("video", "crowd"):
        raise SystemExit(f"{path}: vehicle_mode must be \"video\" or \"crowd\" (frame-by-frame detection for dense traffic)")
    if site.get("person_grid", 1) not in (1, 2, 3):
        raise SystemExit(f"{path}: person_grid must be 1, 2 or 3 (use 2 or 3 when more than ~16 people are in view)")
    if site.get("view", "oblique") not in ("oblique", "top-down"):
        raise SystemExit(f"{path}: view must be \"oblique\" (a phone up high, looking across) or \"top-down\" (drone)")
    if not PREP_FILTER.match(site.get("prep_filter", "") or "crop"):
        raise SystemExit(f"{path}: prep_filter may only use crop, scale, transpose, hflip or vflip")
    return site


def check_source(video, out_dir, prep_filter):
    """Refuse to reuse an output folder (its clip and paid SAM replies) made from another video or settings."""
    stat = Path(video).stat()
    stamp = {"video": str(Path(video).resolve()), "bytes": stat.st_size, "prep_filter": prep_filter, "fps": FPS,
             "width": WIDTH, "chunk_frames": CHUNK_FRAMES, "overlap_frames": OVERLAP_FRAMES}
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


def encode(source, out_path, *ffmpeg_args):
    """Re-encode `source` to an H.264 faststart clip SAM accepts, written atomically."""
    partial = out_path.with_name(out_path.stem + ".part.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ffmpeg_args[:2], "-i", str(source), *ffmpeg_args[2:], "-an",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(partial)], check=True)
    partial.replace(out_path)
    return out_path


def parts(clip, out_dir, total):
    """(first frame, clip, cache folder) per SAM request; long videos are cut into CHUNK_FRAMES pieces that
    overlap by OVERLAP_FRAMES."""
    if total <= CHUNK_FRAMES:
        return [(0, clip, out_dir)]
    pieces = []
    for k, first in enumerate(range(0, total - OVERLAP_FRAMES, CHUNK_FRAMES - OVERLAP_FRAMES)):
        folder = out_dir / f"part{k}"
        folder.mkdir(exist_ok=True)
        piece = folder / "clip.mp4"
        if not piece.exists():
            encode(clip, piece, "-ss", f"{first / FPS:.3f}", "-frames:v", str(CHUNK_FRAMES))
        pieces.append((first, piece, folder))
    return pieces


def even(v):
    return int(v) // 2 * 2


def tiles(frame_size, grid):
    """(x, y, w, h) crops: the whole frame for grid 1, else a grid x grid layout whose neighbours overlap by
    TILE_OVERLAP. SAM 3.1 returns at most 16 objects per frame and request, so crowds need tiles."""
    width, height = frame_size
    if grid == 1:
        return [(0, 0, width, height)]
    w, h = even(width / grid * (1 + TILE_OVERLAP)), even(height / grid * (1 + TILE_OVERLAP))
    xs = [even((width - w) * i / (grid - 1)) for i in range(grid)]
    ys = [even((height - h) * i / (grid - 1)) for i in range(grid)]
    return [(x, y, w, h) for y in ys for x in xs]


def tile_folder(folder, rect, frame_size):
    return folder if rect == (0, 0, *frame_size) else folder / f"tile{rect[0]}_{rect[1]}"


def tile_clip(piece, folder, rect, frame_size):
    """(clip, cache folder) for one crop of a part; the whole part when the crop is the whole frame."""
    sub = tile_folder(folder, rect, frame_size)
    if sub == folder:
        return piece, folder
    sub.mkdir(exist_ok=True)
    clip = sub / "clip.mp4"
    if not clip.exists():
        encode(piece, clip, "-ss", "0", "-vf", "crop={2}:{3}:{0}:{1}".format(*rect))
    return clip, sub


def check_cost(pieces, plan, frame_size, total, allow, images=0, all_images=0):
    """Refuse a surprise bill: estimate the SAM cost of the requests not already cached. `plan` is
    [(concept, grid)]; each tile of each part is one request; `images` uncached crowd-mode image requests out of
    `all_images`. Returns the estimated cost of the whole video, cached or not."""
    units = [(folder, rect, concept) for _, _, folder in pieces for concept, grid in plan for rect in tiles(frame_size, grid)]
    todo = sum(1 for folder, rect, concept in units if not sam.cache_path(tile_folder(folder, rect, frame_size), concept).exists())
    def usd_for(requests, image_requests):
        return requests * total / len(pieces) / 1000 * SAM_USD_PER_1K_FRAMES + image_requests * SAM_USD_PER_IMAGE
    usd = usd_for(todo, images)
    print(f"{total / FPS / 60:.1f} min of video, {len(pieces)} part(s), {len(units)} SAM video request(s), "
          f"{images} image request(s); "
          f"SAM cost about ${usd:.2f}", flush=True)
    if usd > MAX_COST_USD and not allow:
        raise SystemExit(f"estimated SAM cost ${usd:.2f} is over ${MAX_COST_USD:.0f}; re-run with --allow-cost")
    return usd_for(len(units), all_images)



def full_requests(pieces, plan, frame_size):
    """(requests that hit SAM's object limit, all requests) among the cached replies: in a full one, people or
    vehicles that arrived later were not tracked."""
    replies = [sam.cache_path(tile_folder(folder, rect, frame_size), concept)
               for _, _, folder in pieces for concept, grid in plan for rect in tiles(frame_size, grid)]
    found = [len(sam.parse(r.read_text())) for r in replies if r.exists()]
    return sum(n >= sam.MAX_OBJECTS for n in found), len(found)

def box_area(b):
    return (b[2] - b[0]) * (b[3] - b[1])


def link(merged, new, share=LINK_SHARE):
    """`merged` plus the `new` tracks ({name: {frame: box}}). A new track that sits on an existing one over their
    shared frames (overlapping tiles, or the overlap of two parts) joins it, keeping the larger box per frame,
    since a box cut by a tile edge is the smaller one; the rest are added under their own names."""
    scores = []
    for nid, track in new.items():
        for mid, old in merged.items():
            shared = track.keys() & old.keys()
            if shared:
                score = statistics.mean(road.inside_share(*sorted((track[f], old[f]), key=box_area)) for f in shared)
                if score >= share:
                    scores.append((score, nid, mid))
    out = {name: dict(track) for name, track in merged.items()}
    joined = set()
    for _, nid, mid in sorted(scores, reverse=True):
        if nid in joined or mid in joined:
            continue
        joined.update((nid, mid))
        for f, b in new[nid].items():
            if f not in out[mid] or box_area(b) > box_area(out[mid][f]):
                out[mid][f] = b
    out.update({nid: dict(track) for nid, track in new.items() if nid not in joined})
    return out


def track_all(pieces, concept, key, frame_size=None, grid=1):
    """One concept's tracks over all parts (and tiles), in whole-clip frames and pixels, with an object seen
    by two tiles or across a part boundary joined into one track."""
    single = len(pieces) == 1 and grid == 1
    merged = {}
    for k, (first, piece, folder) in enumerate(pieces):
        part = {}
        for t, rect in enumerate(tiles(frame_size, grid) if grid > 1 else [None]):
            clip, cache = (piece, folder) if rect is None else tile_clip(piece, folder, rect, frame_size)
            dx, dy = (0, 0) if rect is None else rect[:2]
            found = {(obj if single else f"{k}.{t}:{obj}"): {first + f: [b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy]
                                                            for f, b in track.items()}
                     for obj, track in sam.track(clip, concept, key, cache).items()}
            part = link(part, found)
        merged = link(merged, part)
    return merged



def crowd_concepts(site):
    """Concepts detected frame by frame on images (crowd mode) instead of tracked by SAM video, which keeps at most
    sam.MAX_OBJECTS per request: people with "person_mode": "crowd", vehicles with "vehicle_mode": "crowd"."""
    return (([site.get("person", "person")] if site.get("person_mode") == "crowd" else [])
            + (list(site["vehicles"]) if site.get("vehicle_mode") == "crowd" else []))


def crowd_frames(site, concept, total):
    """The clip frames crowd mode sends as images for `concept`: people at crowd.CROWD_FPS, vehicles faster."""
    rate = crowd.CROWD_FPS if concept == site.get("person", "person") else crowd.VEHICLE_FPS
    return crowd.sample_frames(total, FPS, rate)


def concept_tracks(site, concept, clip, total, pieces, out_dir, key, frame_size, grid=1):
    """One concept's tracks in whole-clip frames and pixels, by crowd mode or SAM video as the site asks."""
    if concept in crowd_concepts(site):
        return crowd.track(clip, crowd_frames(site, concept, total), FPS, concept, key, crowd.cache_dir(out_dir, concept))
    return track_all(pieces, concept, key, frame_size, grid)


def probe(path, entries, *extra):
    return subprocess.run(["ffprobe", "-v", "error", *extra, "-select_streams", "v:0", "-show_entries", entries,
                           "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True).stdout.strip()


def write_events(out_dir, site, events, seen, cost, full, timeline=None, paths=None):
    (out_dir / "events.json").write_text(json.dumps({"site": site.get("name", ""), "fps": FPS, "exposure": seen,
                                                     "cost": cost,
                                                     "sam_full_requests": full, "timeline": timeline,
                                                     "paths": paths, "events": events}, indent=1))


def road_tracks(site, H, person_boxes, vehicle_boxes, frame_size):
    """SAM boxes -> (pedestrian track pieces, vehicle shapes) in road metres, cleaned: riders dropped, tracks split
    where the ID jumps, pieces under road.MIN_PIECE_S dropped, only the analysis zone (and carriageway, if marked)
    kept."""
    zone = site.get("zone_m") or road.zone_around(site["world_points"])
    top_down = site.get("view") == "top-down"
    walkers = {pid: road.without_riders(t, vehicle_boxes.values()) for pid, t in person_boxes.items()}
    people = {f"{pid}/{k}": piece for pid, t in walkers.items()
              for k, piece in enumerate(road.split_at_jumps(road.moving_frames(  # stillness judged before cutting
                  road.person_points(t, H, zone, site.get("roadway_m"), frame_size, top_down), FPS), FPS))
              if len(piece) >= road.MIN_PIECE_S * FPS}
    vehicles = {vid: road.vehicle_edges(t, H, zone, frame_size, top_down) for vid, t in vehicle_boxes.items()}
    return people, vehicles



def placed(events, people, vehicles):
    """The events with where each happened and both paths around the moment, in road metres, for the map."""
    out = []
    for e in events:
        fp, fv = round(e["t_person_s"] * FPS), round(e["t_vehicle_s"] * FPS)
        feet = people[e["person"]]
        centres = {f: road.centroid(shape) for f, shape in vehicles[e["vehicle"]].items()}
        out.append({**e, "where": [round(c, 1) for c in feet[fp]] if fp in feet else None,
                    "path_person": roadmap.path_around(feet, fp, FPS), "path_vehicle": roadmap.path_around(centres, fv, FPS)})
    return out


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
    person_concept, grid = site.get("person", "person"), site.get("person_grid", 1)
    crowded = crowd_concepts(site)
    images = sum(1 for c in crowded for f in crowd_frames(site, c, total)
                 if not (crowd.cache_dir(out_dir, c) / f"{f:06d}.sam.txt").exists())
    video_plan = [(c, g) for c, g in [(person_concept, grid)] + [(c, 1) for c in site["vehicles"]] if c not in crowded]
    all_images = sum(len(crowd_frames(site, c, total)) for c in crowded)
    cost = {"sam_usd": round(check_cost(pieces, video_plan, frame_size, total, args.allow_cost, images, all_images), 2),
            "image_usd": round(all_images * SAM_USD_PER_IMAGE, 2)}

    tracks_of = lambda concept, g=1: concept_tracks(site, concept, clip, total, pieces, out_dir, key, frame_size, g)
    person_boxes = tracks_of(person_concept, grid)
    vehicle_boxes = {f"{concept}#{vid}": t for concept in site["vehicles"] for vid, t in tracks_of(concept).items()}
    top_down = site.get("view") == "top-down"
    people, vehicles = road_tracks(site, H, person_boxes, vehicle_boxes, frame_size)
    events = placed(road.conflicts(people, vehicles, FPS), people, vehicles)
    seen = road.exposure(people, vehicles, FPS, total)
    timeline = road.timeline(people, vehicles, FPS, total)  # the gap barcode's spans, kept out of `seen`
    paths = road.crossing_paths(people, vehicles, FPS)  # the desire lines, kept out of `seen` too
    full = full_requests(pieces, video_plan, frame_size)
    if full[0]:
        print(f"warning: {full[0]} of {full[1]} SAM requests hit the {sam.MAX_OBJECTS}-object limit; later arrivals "
              "in those parts were not tracked (use person_mode / vehicle_mode \"crowd\": the Crowded and Dense "
              "traffic boxes on the calibration page)", flush=True)

    write_events(out_dir, site, events, seen, cost, full, timeline, paths)  # saved before the slower, network-bound evidence step
    review_people(clip, out_dir, events, people, person_boxes, key, frame_size, top_down)
    add_evidence(args.video, clip, out_dir, events, people, person_boxes, vehicle_boxes, key, frame_size)
    write_events(out_dir, site, events, seen, cost, full, timeline, paths)
    report(seen, events)


if __name__ == "__main__":
    main()
