"""DUT check re-run at $0 on cached runs (validate_dut.py --out folders) with the code as it now stands: tracks rebuilt
from the cached SAM replies, today's near-miss rules, Spark's stored verdicts re-applied through today's rider gate,
and validate_dut's scoring. Nothing is sent to SAM and no events.json is written: a cache miss stops the check. A
piece with no stored verdict takes Spark's reply saved beside its crop (review.review), while the crop is the same;
one with neither stays in, as unreviewed events do on the page, and "unreviewed" counts those events. --spark N asks
Spark (paid) about at most N such crops and saves its replies there, so later runs read them at $0.
Also checks our vehicle speeds against the dataset's positions at its own, evenly spaced frame rate.
Run: python3 validate_offline.py DUT_REPO out/dut-vcrowd out/dut-15s [--site '{"person_mode": "video"}'] [--json FILE] [--spark N]
"""
import argparse
import csv
import json
import math
import statistics
from pathlib import Path

import analyze
import crowd
import review
import road
import sam
import validate_dut

TOTALS = ("matched", "missed", "missed_by_review", "missed_at_threshold", "extra", "extra_at_threshold", "unreviewed")
NATIVE_STEP = 3          # reference speed: distance over +-3 source frames, at DUT's own 23.976 fps
NEAR_BAR_KMH = (7, 13)   # reference speeds this close to the 10 km/h "moving" bar, where a small error flips a conflict


def offline(*_args, **_kwargs):
    raise RuntimeError("not in the run's cache: validate_offline never calls SAM or re-encodes a clip")


def stored_verdicts(events):
    """Spark's verdict per pedestrian piece in a run's events.json, read by today's rule (older runs kept a
    "cyclist" as a pedestrian)."""
    return {e["person"]: r and {**r, "is_person": r["is_person"] and r["road_user"] not in review.NOT_PEDESTRIANS}
            for e in events if "review" in e for r in [e["review"]]}


def with_verdicts(events, verdicts, person_boxes, vehicle_boxes, people):
    """`events` with each piece's stored verdict passed through today's rider gate, as analyze.review_people does;
    pieces without one stay unreviewed."""
    rideables = [t for name, t in vehicle_boxes.items() if name.split("#")[0].lower() in review.RIDEABLE]
    return [{**e, "review": review.gated(verdicts[e["person"]], analyze.piece_boxes(person_boxes, people, e["person"]),
                                         rideables, *analyze.motion(people, e["person"]))}
            if e["person"] in verdicts else e for e in events]


def spark_asker(limit):
    """review.ask for at most `limit` paid calls (the key loaded only if one is made); after that, and with limit 0,
    no reply, so the piece stays unreviewed."""
    asked = []
    def ask(image_path, _key, top_down=False):
        if len(asked) >= limit:
            return None
        asked.append(image_path)
        print(f"asking Spark ({len(asked)} of at most {limit}): {image_path.parent.name}/{image_path.name}", flush=True)
        return original_ask(image_path, sam.load_api_key(), top_down)
    return ask


original_ask = review.ask


def rebuild(site, clip_out):
    """validate_dut.our_tracks plus today's events with the stored verdicts, cut in the run's own SAM parts."""
    stamp = json.loads((clip_out / "source.json").read_text())
    analyze.CHUNK_FRAMES, analyze.OVERLAP_FRAMES = stamp["chunk_frames"], stamp["overlap_frames"]  # as this run cut
    person_boxes, vehicle_boxes, people, vehicles, total = validate_dut.our_tracks(site, clip_out)
    verdicts = stored_verdicts(json.loads((clip_out / "events.json").read_text())["events"])
    events = road.conflicts(people, vehicles, analyze.FPS)
    clip, top_down = clip_out / "clip.mp4", site.get("view") == "top-down"
    frame_size = tuple(int(v) for v in analyze.probe(clip, "stream=width,height").split(","))
    for pid in list(dict.fromkeys(e["person"] for e in events))[:analyze.MAX_REVIEWS]:  # as analyze.review_people
        if pid not in verdicts and (v := review.review(clip, analyze.piece_boxes(person_boxes, people, pid), frame_size,
                                                       clip_out / f"person-{pid.replace('/', '-')}.jpg", "", top_down)):
            verdicts[pid] = v
    return with_verdicts(events, verdicts, person_boxes, vehicle_boxes, people), people, vehicles, total


def native_speeds(repo, clip):
    """Each DUT car's speed (m/s) per clip frame from its positions at the source's own frame rate, where frames are
    evenly spaced: our clip is resampled to analyze.FPS, this reference is not."""
    pos = {}
    folder = repo / "data" / "trajectories_filtered"
    for row in csv.DictReader(open(folder / f"intersection_{clip}_traj_veh_filtered.csv")):
        pos.setdefault(f"car#{row['id']}", {})[int(float(row["frame"]))] = (float(row["x_est"]), float(row["y_est"]))
    step = lambda p, s: math.dist(p[s - NATIVE_STEP], p[s + NATIVE_STEP]) * validate_dut.SOURCE_FPS / (2 * NATIVE_STEP)
    # a clip frame takes its last source frame, as in ground_truth(); None where that one has no neighbours
    return {vid: {validate_dut.to_clip_frame(s): step(p, s) if s - NATIVE_STEP in p and s + NATIVE_STEP in p else None
                  for s in p} for vid, p in pos.items()}


def speed_pairs(repo, clip, vehicles):
    """(our m/s, reference m/s) on every frame where one of our vehicle tracks follows a DUT car."""
    _, cars = validate_dut.ground_truth(repo, clip)
    ids, native = validate_dut.identities(vehicles, cars, validate_dut.VEHICLE_ID_DIST_M), native_speeds(repo, clip)
    return [(mps, ref) for vid, shapes in vehicles.items() for f, mps in road.speeds(shapes, analyze.FPS).items()
            if (ref := native.get(ids.get(vid), {}).get(f)) is not None]


def rescore(repo, run, clip, override=None):
    """One clip of a cached run through today's code, scored by validate_dut.compare. `override` changes the run's
    site file (e.g. another person_mode whose replies the folder also caches)."""
    site = {**json.loads((run / f"site-{clip}.json").read_text()), **(override or {})}
    events, people, vehicles, total = rebuild(site, run / clip)
    result = validate_dut.compare(repo, clip, events, road.exposure(people, vehicles, analyze.FPS, total), people,
                                  vehicles, total)
    return {**result, "unreviewed": sum("review" not in e for e in events),
            "speed_vs_native": speed_pairs(repo, clip, vehicles)}


def speed_summary(pairs):
    """Our speed error against the native-rate reference, and how often it puts a car near the bar on the wrong side."""
    errors = sorted(abs(ours - ref) * 3.6 for ours, ref in pairs)
    near = [(ours, ref) for ours, ref in pairs if NEAR_BAR_KMH[0] <= ref * 3.6 <= NEAR_BAR_KMH[1]]
    wrong = sum((ours >= road.MOVING_MPS) != (ref >= road.MOVING_MPS) for ours, ref in near)
    return {"frames": len(pairs), "mean_abs_kmh": round(statistics.mean(errors), 2) if errors else None,
            "p95_abs_kmh": round(errors[int(0.95 * (len(errors) - 1))], 2) if errors else None,
            "near_bar_wrong_side_pct": round(100 * wrong / len(near), 1) if near else None}


def total(rows):
    """The run's sums over its clips."""
    return {"conflicts": sum(r["truth"]["conflicts"] for r in rows), **{k: sum(r[k] for r in rows) for k in TOTALS},
            "found_before_review": sum(r["before_review"]["matched"] for r in rows),
            "speed_vs_native": speed_summary([p for r in rows for p in r["speed_vs_native"]])}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", type=Path, help="DUT dataset repo (trajectories)")
    parser.add_argument("runs", type=Path, nargs="+", help="cached validate_dut.py --out folders")
    parser.add_argument("--site", type=json.loads, help="site overrides as JSON, e.g. another cached person_mode")
    parser.add_argument("--json", type=Path, help="also save every clip's result here")
    parser.add_argument("--spark", type=int, default=0, metavar="N",
                        help="ask Spark (paid) about at most N crops with no saved reply; default 0: none")
    args = parser.parse_args()
    sam.request = crowd.request = analyze.encode = offline
    sam.RETRY_WAITS_S = ()  # a reply missing from the cache fails at once, not after the retries' waits
    review.ask = spark_asker(args.spark)
    results = {}
    for run in args.runs:
        clips = sorted(p.stem.removeprefix("site-") for p in run.glob("site-*.json"))
        rows = [rescore(args.repo, run, clip, args.site) for clip in clips]
        results[str(run)] = {"total": total(rows), "clips": rows}
        print(run, json.dumps(results[str(run)]["total"]))
    if args.json:
        args.json.write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
