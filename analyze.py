"""Crossing Watch: find pedestrian-vehicle near-misses in one video of a crossing.

Run: python3 analyze.py VIDEO SITE.json [--out DIR] [--budget USD]
SITE.json holds four calibration points (clip pixels) and where they lie on the road (metres); see sites/.
Writes DIR/events.json and prints the most dangerous moments first.
"""
import argparse
import json
import math
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
SAM_MIN_FRAMES = 50           # ...which bills at least this many frames per request
SAM_USD_PER_IMAGE = 0.0025    # crowd mode: SAM images, Meta's list price of $2.50 per 1,000 images
MAX_COST_USD = 10.0  # above this estimate, --allow-cost (or a --budget) is required
MODES = ("video", "crowd", "auto")  # person_mode / vehicle_mode values
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
    for key, crowd_of in (("person_mode", "crowds"), ("vehicle_mode", "traffic")):
        if site.get(key, "video") not in MODES:
            raise SystemExit(f"{path}: {key} must be \"video\", \"crowd\" (frame-by-frame detection for dense {crowd_of}) "
                             "or \"auto\" (video first, frame by frame for a concept whose video requests fill up)")
    if site.get("person_grid", 1) not in (1, 2, 3):
        raise SystemExit(f"{path}: person_grid must be 1, 2 or 3 (use 2 or 3 when more than ~16 people are in view)")
    if site.get("view", "oblique") not in ("oblique", "top-down"):
        raise SystemExit(f"{path}: view must be \"oblique\" (a phone up high, looking across) or \"top-down\" (drone)")
    sizes = site.get("vehicle_sizes_m", {})
    if not (isinstance(sizes, dict) and all(k in vehicles and isinstance(v, list) and len(v) == 2
                                            and all(isinstance(x, (int, float)) and x > 0 for x in v) and v[0] >= v[1]
                                            for k, v in sizes.items())):
        raise SystemExit(f"{path}: vehicle_sizes_m must map vehicle concepts to tape-measured [length, width] in "
                         "metres, length first, e.g. {\"car\": [3.9, 1.7]}")
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


def spend_cap(budget, allow):
    """Dollars a run may spend on new SAM requests: --budget is a hard cap; without one, MAX_COST_USD unless
    --allow-cost."""
    return budget if budget is not None else math.inf if allow else MAX_COST_USD


def billed_frames(pieces, total):
    """Frames SAM video bills for one request on each part: parts overlap, and a short last part is billed
    SAM_MIN_FRAMES."""
    return [max(SAM_MIN_FRAMES, min(CHUNK_FRAMES, total - first)) for first, _, _ in pieces]


def check_cost(pieces, plan, frame_size, total, cap, images=0, all_images=0):
    """Refuse a surprise bill: estimate the SAM cost of the requests not already cached and stop if it is over `cap`
    dollars (spend_cap). `plan` is [(concept, grid)]; each tile of each part is one request; `images` uncached
    crowd-mode image requests out of `all_images`. Returns (that estimate, the cost of the whole video, cached or
    not)."""
    units = [(frames, tile_folder(folder, rect, frame_size), concept)
             for (_, _, folder), frames in zip(pieces, billed_frames(pieces, total))
             for concept, grid in plan for rect in tiles(frame_size, grid)]
    def usd_for(frames, image_requests):
        return frames / 1000 * SAM_USD_PER_1K_FRAMES + image_requests * SAM_USD_PER_IMAGE
    usd = usd_for(sum(n for n, folder, concept in units if not sam.cache_path(folder, concept).exists()), images)
    print(f"{total / FPS / 60:.1f} min of video, {len(pieces)} part(s), {len(units)} SAM video request(s), "
          f"{images} image request(s); "
          f"SAM cost about ${usd:.2f}", flush=True)
    if round(usd, 2) > cap:  # in whole cents, as printed
        raise SystemExit(f"estimated SAM cost ${usd:.2f} is over the ${cap:.2f} this run may still spend; pass a larger "
                         f"--budget USD (without one the cap is ${MAX_COST_USD:.0f}, lifted by --allow-cost). Replies "
                         "already received are cached and not paid for again")
    return usd, usd_for(sum(n for n, _, _ in units), all_images)



def full_requests(pieces, plan, frame_size):
    """(requests that hit SAM's object limit, all requests) among the cached replies: in a full one, people or
    vehicles that arrived later were not tracked."""
    replies = [sam.cache_path(tile_folder(folder, rect, frame_size), concept)
               for _, _, folder in pieces for concept, grid in plan for rect in tiles(frame_size, grid)]
    found = [len(sam.parse(r.read_text())) for r in replies if r.exists()]
    return sum(n >= sam.MAX_OBJECTS for n in found), len(found)


def fill_seconds(pieces, concept, grid, frame_size):
    """For each part whose cached SAM video reply for `concept` filled up (sam.saturation_frame; the earliest of its
    tiles), the second into the part when it did. A fill at CHUNK_FRAMES - OVERLAP_FRAMES or later does not count in
    a part that is not the last: the next part covers those frames."""
    seconds = []
    for k, (_, _, folder) in enumerate(pieces):
        replies = [sam.cache_path(tile_folder(folder, rect, frame_size), concept) for rect in tiles(frame_size, grid)]
        fills = [sam.saturation_frame(sam.parse(r.read_text())) for r in replies if r.exists()]
        last = k == len(pieces) - 1
        counted = [f for f in fills if f is not None and (last or f < CHUNK_FRAMES - OVERLAP_FRAMES)]
        if counted:
            seconds.append(min(counted) / FPS)
    return seconds


def switch_note(concept, seconds, parts):
    """The page's line for a concept auto mode moved to frame-by-frame detection, from its fill_seconds."""
    lo, hi = min(seconds), max(seconds)
    within = f"{lo:.1f} s" if lo == hi else f"{lo:.1f}-{hi:.1f} s"
    return (f"{concept}: {sam.MAX_OBJECTS} objects taken within {within} in {len(seconds)} of {parts} "
            f"part{'' if parts == 1 else 's'}, so frame-by-frame was used")


def auto_switch(site, pieces, plan, key, frame_size):
    """{concept: fill_seconds} for the auto-mode concepts in `plan` whose SAM video replies filled up; their video
    requests are sent (or read from cache) first. Those concepts are then detected frame by frame, as in crowd mode."""
    switched = {}
    for concept, grid in plan:
        if concept in crowd_concepts(site, "auto"):
            track_all(pieces, concept, key, frame_size, grid)  # sends the video requests not cached yet
            if seconds := fill_seconds(pieces, concept, grid, frame_size):
                switched[concept] = seconds
    return switched


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



def crowd_concepts(site, mode="crowd"):
    """Concepts detected frame by frame on images (crowd mode) instead of tracked by SAM video, which keeps at most
    sam.MAX_OBJECTS per request: people with "person_mode": "crowd", vehicles with "vehicle_mode": "crowd". With
    `mode` "auto", the concepts auto mode may switch."""
    return (([site.get("person", "person")] if site.get("person_mode") == mode else [])
            + (list(site["vehicles"]) if site.get("vehicle_mode") == mode else []))


def crowd_frames(site, concept, total):
    """The clip frames crowd mode sends as images for `concept`: people at crowd.CROWD_FPS, vehicles faster."""
    rate = crowd.CROWD_FPS if concept == site.get("person", "person") else crowd.VEHICLE_FPS
    return crowd.sample_frames(total, FPS, rate)


def image_requests(site, concepts, total, out_dir):
    """(uncached, all) crowd-mode image requests for `concepts`."""
    frames = [(c, f) for c in concepts for f in crowd_frames(site, c, total)]
    return sum(not (crowd.cache_dir(out_dir, c) / f"{f:06d}.sam.txt").exists() for c, f in frames), len(frames)


def concept_tracks(site, concept, clip, total, pieces, out_dir, key, frame_size, grid=1, switched=()):
    """One concept's tracks in whole-clip frames and pixels, by crowd mode or SAM video as the site asks; concepts
    `switched` by auto mode go frame by frame too."""
    if concept in crowd_concepts(site) or concept in switched:
        jump = crowd.MAX_AREA_JUMP if concept in site["vehicles"] else math.inf
        return crowd.track(clip, crowd_frames(site, concept, total), FPS, concept, key, crowd.cache_dir(out_dir, concept), jump)
    return track_all(pieces, concept, key, frame_size, grid)


def probe(path, entries, *extra):
    return subprocess.run(["ffprobe", "-v", "error", *extra, "-select_streams", "v:0", "-show_entries", entries,
                           "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True).stdout.strip()


def write_events(out_dir, site, events, seen, cost, full, privacy=None):
    (out_dir / "events.json").write_text(json.dumps({"site": site.get("name", ""), "fps": FPS, "exposure": seen,
                                                     "cost": cost,
                                                     "sam_full_requests": full, "privacy": privacy,
                                                     "events": events}, indent=1))


def road_tracks(site, H, person_boxes, vehicle_boxes, frame_size):
    """SAM boxes -> (pedestrian track pieces, vehicle shapes) in road metres, cleaned: riders dropped, tracks split
    where the ID jumps, pieces under road.MIN_PIECE_S dropped, only the analysis zone (and carriageway, if marked)
    kept. A vehicle seen at an angle is a car-shaped footprint when its concept has a size (vehicle_size)."""
    zone = site.get("zone_m") or road.zone_around(site["world_points"])
    top_down = site.get("view") == "top-down"
    walkers = {pid: road.without_riders(t, vehicle_boxes.values()) for pid, t in person_boxes.items()}
    people = {f"{pid}/{k}": piece for pid, t in walkers.items()
              for k, piece in enumerate(road.split_at_jumps(road.moving_frames(  # stillness judged before cutting
                  road.person_points(t, H, zone, site.get("roadway_m"), frame_size, top_down), FPS), FPS))
              if len(piece) >= road.MIN_PIECE_S * FPS}
    sizes = {vid: vehicle_size(site, vid) for vid in vehicle_boxes}
    vehicles = {vid: road.vehicle_footprints(t, H, sizes[vid], FPS, zone, frame_size) if sizes[vid]
                else road.vehicle_edges(t, H, zone, frame_size, top_down) for vid, t in vehicle_boxes.items()}
    return people, vehicles


def vehicle_size(site, vid):
    """(length, width) in metres of a vehicle id's concept for a car-shaped footprint: the site's tape-measured
    "vehicle_sizes_m", else road.VEHICLE_SIZES_M. None from a top-down camera, where the box is the footprint, and
    for a concept with no size (such as the single concept "vehicle"), which keeps the lower box edge."""
    if site.get("view") == "top-down":
        return None
    concept = vid.split("#")[0]
    return site.get("vehicle_sizes_m", {}).get(concept) or road.VEHICLE_SIZES_M.get(concept.lower())



def placed(events, people, vehicles):
    """The events with where each happened, both paths around the moment and the vehicle's footprint (or lower
    edge) at its moment, in road metres, for the map."""
    out = []
    for e in events:
        fp, fv = round(e["t_person_s"] * FPS), round(e["t_vehicle_s"] * FPS)
        feet = people[e["person"]]
        centres = {f: road.centroid(shape) for f, shape in vehicles[e["vehicle"]].items()}
        out.append({**e, "where": [round(c, 1) for c in feet[fp]] if fp in feet else None,
                    "path_person": roadmap.path_around(feet, fp, FPS), "path_vehicle": roadmap.path_around(centres, fv, FPS),
                    "footprint": [[round(v, 1) for v in q] for q in vehicles[e["vehicle"]][fv]]})
    return out


def piece_boxes(person_boxes, people, pid):
    """SAM boxes of just the track piece `pid` ("<sam id>/<piece>") that made an event."""
    boxes = person_boxes[pid.split("/")[0]]
    return {f: boxes[f] for f in people[pid] if f in boxes}


def walking_kmh(feet):
    """A pedestrian piece's median speed in km/h, or None when it is too short to measure."""
    mps = list(road.speeds({f: (p,) for f, p in feet.items()}, FPS).values())
    return round(statistics.median(mps) * 3.6, 1) if mps else None


def review_people(clip, out_dir, events, people, person_boxes, vehicle_boxes, key, frame_size, top_down):
    """Spark looks once at each pedestrian piece involved in a conflict (most dangerous first, at most
    MAX_REVIEWS), and its verdict is attached to all that piece's events. A rider call stands only with a
    rideable vehicle's box under the person (review.gated)."""
    rideables = [t for name, t in vehicle_boxes.items() if name.split("#")[0].lower() in review.RIDEABLE]
    verdicts = {}
    for e in events:
        pid = e["person"]
        if pid not in verdicts and len(verdicts) < MAX_REVIEWS:
            boxes = piece_boxes(person_boxes, people, pid)
            try:
                verdict = review.review(clip, boxes, frame_size, out_dir / f"person-{pid.replace('/', '-')}.jpg",
                                        key, top_down)
            except (subprocess.CalledProcessError, OSError) as err:
                print(f"review of {pid} failed: {err}", flush=True)
                verdict = None
            verdicts[pid] = review.gated(verdict, boxes, rideables, walking_kmh(people[pid]))
        e["review"] = verdicts.get(pid)


def evidence_events(events):
    """The top EVIDENCE_CLIPS events Spark did not reject: the ones that get an evidence clip."""
    return [e for e in events if (e.get("review") or {}).get("is_person", True)][:EVIDENCE_CLIPS]


def shown_frames(events, total):
    """The clip frames that are published: every evidence clip's frames, and frame 0 (pack's street photo)."""
    windows = [render.window(e, FPS) for e in evidence_events(events)]
    return {0, *(f for first, last in windows for f in range(first, min(last, total - 1) + 1))}


def search_heads(site, clip, out_dir, events, total, pieces, key, budget):
    """When a SAM video request for people was full, people who came later have no track, so no blur. SAM image
    search looks for them, as crowd mode would, on the person frames within one sample of a shown frame (so the boxes
    filled in between samples cover each one), within `budget` dollars (check_cost). Each found box is also held on the
    frames up to the next sample either side that have none, so the last frame of a clip and the frames next to a
    person seen on one sample are covered too. Returns (their tracks, the frames searched)."""
    person = site.get("person", "person")
    sampled, shown = crowd_frames(site, person, total), shown_frames(events, total)
    frames = [f for f in sampled if not shown.isdisjoint(range(f - sampled.step + 1, f + sampled.step))]
    cache = crowd.cache_dir(out_dir, person)
    print(f"a SAM video request for {person} was full: SAM image search on {len(frames)} published frames for "
          "the people it missed", flush=True)
    check_cost(pieces, [], None, total, budget, sum(not (cache / f"{f:06d}.sam.txt").exists() for f in frames),
               len(frames))
    near = lambda f: (g for d in range(1, sampled.step) for g in (f - d, f + d) if 0 <= g < total)
    found = crowd.track(clip, frames, FPS, person, key, cache)
    return {tid: {**{g: b for f, b in t.items() for g in near(f)}, **t} for tid, t in found.items()}, frames


def heads(person_boxes, found, frames):
    """(person tracks whose heads are blurred: the tracked and the found, the page's counts). Counts are for the
    busiest searched frame, since the tracker splits people seen only every 0.2 s into many short tracks: the most
    people with a track on one frame, and the most found on one frame who sit on no tracked box (LINK_SHARE)."""
    on = lambda tracks, f: [t[f] for t in tracks if f in t]
    def missed(f):
        tracked = on(person_boxes.values(), f)
        return sum(all(road.inside_share(*sorted((b, o), key=box_area)) < LINK_SHARE for o in tracked)
                   for b in on(found.values(), f))
    counts = {"heads_tracked": max(len(on(person_boxes.values(), f)) for f in frames),
              "heads_found": max(map(missed, frames))}
    return [*person_boxes.values(), *found.values()], counts


def add_evidence(video, clip, out_dir, events, people, person_boxes, vehicle_boxes, key, frame_size, everyone):
    """Evidence clip and sound check for evidence_events; one failure costs that event's evidence, not the run. Only
    the frames of the track piece that made the event are boxed; the heads of `everyone` and every number plate are
    blurred."""
    for i, e in enumerate(evidence_events(events)):
        pair = piece_boxes(person_boxes, people, e["person"]), vehicle_boxes[e["vehicle"]]
        try:
            e["clip"] = render.render(clip, e, *pair, FPS, out_dir / f"event{i + 1}.mp4", everyone=everyone,
                                      frame_size=frame_size, vehicles=list(vehicle_boxes.values())).name
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
              f"{at20['death_risk_pct']}%), at {e['t_person_s']:.1f} s  "
              f"[Spark: {review.unconfirmed_rider(verdict) or verdict.get('road_user', 'not reviewed')}]")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video")
    parser.add_argument("site")
    parser.add_argument("--out", help="output folder (default out/<video name>)")
    parser.add_argument("--allow-cost", action="store_true", help=f"run even if SAM would cost over ${MAX_COST_USD:.0f}")
    parser.add_argument("--budget", type=float, metavar="USD", help="hard cap on what new SAM requests may cost in "
                        f"this run, at Meta's list prices (replaces the ${MAX_COST_USD:.0f} cap; --allow-cost does not lift it)")
    args = parser.parse_args()
    if args.budget is not None and not args.budget >= 0:
        parser.error("--budget must be 0 or more US dollars")

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
    video_plan = [(c, g) for c, g in [(person_concept, grid)] + [(c, 1) for c in site["vehicles"]] if c not in crowded]
    cap = spend_cap(args.budget, args.allow_cost)
    spent, sam_usd = check_cost(pieces, video_plan, frame_size, total, cap, *image_requests(site, crowded, total, out_dir))
    switched = auto_switch(site, pieces, video_plan, key, frame_size)
    notes = [switch_note(c, seconds, len(pieces)) for c, seconds in switched.items()]
    if switched:
        print("auto mode: " + "; ".join(notes), flush=True)
        more, whole = check_cost(pieces, [], frame_size, total, cap - spent,
                                 *image_requests(site, list(switched), total, out_dir))
        spent, sam_usd = spent + more, sam_usd + whole
    image_usd = image_requests(site, crowded + list(switched), total, out_dir)[1] * SAM_USD_PER_IMAGE
    cost = lambda searched=0: {"sam_usd": round(sam_usd + searched * SAM_USD_PER_IMAGE, 2),
                               "image_usd": round(image_usd + searched * SAM_USD_PER_IMAGE, 2)}

    tracks_of = lambda concept, g=1: concept_tracks(site, concept, clip, total, pieces, out_dir, key, frame_size, g,
                                                    switched)
    person_boxes = tracks_of(person_concept, grid)
    vehicle_boxes = {f"{concept}#{vid}": t for concept in site["vehicles"] for vid, t in tracks_of(concept).items()}
    top_down = site.get("view") == "top-down"
    people, vehicles = road_tracks(site, H, person_boxes, vehicle_boxes, frame_size)
    events = placed(road.conflicts(people, vehicles, FPS), people, vehicles)
    seen = road.exposure(people, vehicles, FPS, total)
    full = (*full_requests(pieces, [(c, g) for c, g in video_plan if c not in switched], frame_size), notes)
    if full[0]:
        print(f"warning: {full[0]} of {full[1]} SAM requests hit the {sam.MAX_OBJECTS}-object limit; later arrivals "
              "in those parts were not tracked (use person_mode / vehicle_mode \"crowd\": the Crowded and Dense "
              "traffic boxes on the calibration page; or \"auto\")", flush=True)

    write_events(out_dir, site, events, seen, cost(), full)  # saved before the slower, network-bound evidence step
    review_people(clip, out_dir, events, people, person_boxes, vehicle_boxes, key, frame_size, top_down)
    everyone, privacy, searched = list(person_boxes.values()), None, []
    if events and person_concept not in crowded + list(switched) and \
            full_requests(pieces, [(person_concept, grid)], frame_size)[0]:
        found, searched = search_heads(site, clip, out_dir, events, total, pieces, key, cap - spent)
        everyone, privacy = heads(person_boxes, found, searched)
    add_evidence(args.video, clip, out_dir, events, people, person_boxes, vehicle_boxes, key, frame_size, everyone)
    write_events(out_dir, site, events, seen, cost(len(searched)), full, privacy)
    report(seen, events)


if __name__ == "__main__":
    main()
