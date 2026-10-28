"""End-to-end check against ground truth: run the whole pipeline (SAM 3.1 -> metres -> near-misses -> Spark) on
DUT drone clips of a campus crosswalk full of students, and compare with the dataset's own tracked trajectories.

Data (no licence given; internal testing only, not in this repo): https://github.com/dongfang-steven-yang/vci-dataset-dut
(trajectories and ratios in the repo; stabilised videos from its Google Drive link).
Run: python3 validate_dut.py DUT_REPO DUT_VIDEOS 15 01 03     (each clip costs a few cents of SAM)
"""
import argparse
import csv
import json
import math
import subprocess
from pathlib import Path

import analyze
import crowd
import pack
import road

SOURCE_FPS = 2997 / 125
CAR_LENGTH_M, CAR_WIDTH_M = 4.6, 1.8  # DUT gives the car centre and heading, not its size
PERSON_ID_DIST_M, VEHICLE_ID_DIST_M = 1.0, 2.5  # our track follows a ground-truth track if this close
# A disagreement is a "boundary" case when the other side finds the same pair once each threshold is widened by
# about our measured error: speed ±1.5 km/h around the 10 km/h moving bar, gap +0.3 m, PET +0.3 s.
SPEED_BAND_KMH, GAP_BAND_M, PET_BAND_S = 1.5, 0.3, 0.3


def to_clip_frame(source_frame):
    return round((source_frame - 1) / SOURCE_FPS * analyze.FPS)


def ground_truth(repo, clip):
    people, vehicles = {}, {}
    folder = repo / "data" / "trajectories_filtered"
    for row in csv.DictReader(open(folder / f"intersection_{clip}_traj_ped_filtered.csv")):
        people.setdefault(row["id"], {})[to_clip_frame(int(float(row["frame"])))] = (float(row["x_est"]), float(row["y_est"]))
    for row in csv.DictReader(open(folder / f"intersection_{clip}_traj_veh_filtered.csv")):
        x, y, psi = float(row["x_est"]), float(row["y_est"]), float(row["psi_est"])
        c, s = math.cos(psi), math.sin(psi)
        f = to_clip_frame(int(float(row["frame"])))
        vehicles.setdefault(f"car#{row['id']}", {})[f] = tuple(
            (x + dx * c - dy * s, y + dx * s + dy * c) for dx, dy in
            ((CAR_LENGTH_M / 2, CAR_WIDTH_M / 2), (CAR_LENGTH_M / 2, -CAR_WIDTH_M / 2),
             (-CAR_LENGTH_M / 2, -CAR_WIDTH_M / 2), (-CAR_LENGTH_M / 2, CAR_WIDTH_M / 2)))
    return people, vehicles


def site_for(repo, video, clip, out, grid=1, mode="video"):
    """Top-down site file: the clip frame's corners in clip pixels, in metres from the dataset's pixel ratio."""
    width, height = (int(v) for v in analyze.probe(video, "stream=width,height").split(","))
    ratio = float((repo / "data" / "ratios" / f"intersection_{clip}_ratio_pixel2meter.txt").read_text())
    clip_w, clip_h = analyze.WIDTH, round(height * analyze.WIDTH / width / 2) * 2
    image = [[0, 0], [clip_w, 0], [clip_w, clip_h], [0, clip_h]]
    site = {"name": f"DUT crosswalk {clip} (drone, ground-truth test)", "view": "top-down",
            "image_points": image, "world_points": [[x * width / clip_w / ratio, y * height / clip_h / ratio] for x, y in image],
            "calibration_note": "From the dataset's measured pixel-to-metre ratio.", "person": "person", "vehicles": ["car"],
            "person_grid": grid, "person_mode": mode}
    path = out / f"site-{clip}.json"
    path.write_text(json.dumps(site, indent=1))
    return path


def position(item):
    """A pedestrian point, or the centre of a vehicle shape."""
    return road.centroid(item) if isinstance(item[0], tuple) else item


def identities(ours, truth, max_dist):
    """Our track id -> the ground-truth id it follows: the truth track nearest to it, voted over shared frames."""
    names = {}
    for oid, track in ours.items():
        votes = {}
        for f, item in track.items():
            near = min(((math.dist(position(item), position(t[f])), tid) for tid, t in truth.items() if f in t),
                       default=None)
            if near and near[0] <= max_dist:
                votes[near[1]] = votes.get(near[1], 0) + 1
        if votes:
            names[oid] = max(votes, key=votes.get)
    return names


def match(truth, found, person_ids, vehicle_ids):
    """(truth event, our event) pairs for the same pedestrian and vehicle, plus the unmatched of each."""
    by_pair = {}
    for f in found:
        key = (person_ids.get(f["person"]), vehicle_ids.get(f["vehicle"]))
        if None not in key and (key not in by_pair or f["pet_s"] < by_pair[key]["pet_s"]):
            by_pair[key] = f
    pairs = [(t, by_pair[(t["person"], t["vehicle"])]) for t in truth if (t["person"], t["vehicle"]) in by_pair]
    used = {id(f) for _, f in pairs}
    missed = [t for t in truth if (t["person"], t["vehicle"]) not in by_pair]
    return pairs, missed, [f for f in found if id(f) not in used]


def near_threshold(feet, shapes):
    """True when this pedestrian and vehicle conflict once the thresholds are widened by the bands."""
    return road.closest_pass(feet, shapes, analyze.FPS, radius=road.CONFLICT_RADIUS_M + GAP_BAND_M,
                             pet_max=road.CLOSE_PASS_S + PET_BAND_S,
                             min_speed=road.MOVING_MPS - SPEED_BAND_KMH / 3.6) is not None


def boundary_flags(missed, extra, people, vehicles, our_people, our_vehicles, person_ids, vehicle_ids):
    """For each missed truth event and each extra event of ours: is it only a threshold-boundary disagreement?"""
    def ours_for(truth_id, ids):
        return [oid for oid, tid in ids.items() if tid == truth_id]
    missed_b = [any(near_threshold(our_people[p], our_vehicles[v]) for p in ours_for(t["person"], person_ids)
                    for v in ours_for(t["vehicle"], vehicle_ids)) for t in missed]
    extra_b = [f["person"] in person_ids and f["vehicle"] in vehicle_ids
               and near_threshold(people[person_ids[f["person"]]], vehicles[vehicle_ids[f["vehicle"]]]) for f in extra]
    return missed_b, extra_b


def check_clip(repo, videos, clip, out, grid=1, mode="video"):
    video = videos / f"intersection_{clip}_roi.mp4"
    clip_out = out / clip
    subprocess.run(["python3", "analyze.py", str(video), str(site_for(repo, video, clip, out, grid, mode)), "--out", str(clip_out)],
                   check=True)
    data = json.loads((clip_out / "events.json").read_text())
    found = pack.confirmed(data["events"])
    people, vehicles = ground_truth(repo, clip)
    truth = road.conflicts(people, vehicles, analyze.FPS)
    site = json.loads((out / f"site-{clip}.json").read_text())
    frame_size = tuple(int(v) for v in analyze.probe(clip_out / "clip.mp4", "stream=width,height").split(","))
    clip_file = clip_out / "clip.mp4"
    pieces = analyze.parts(clip_file, clip_out, analyze.frame_count(clip_file))  # all cached by the run above
    our_people, our_vehicles = analyze.road_tracks(
        site, road.homography(site["image_points"], site["world_points"]),
        (crowd.track(clip_file, analyze.frame_count(clip_file), analyze.FPS, "person", None, clip_out / "crowd-person")
         if mode == "crowd" else analyze.track_all(pieces, "person", None, frame_size, site.get("person_grid", 1))),
        {f"car#{k}": t for k, t in analyze.track_all(pieces, "car", None, frame_size).items()}, frame_size)
    person_ids = identities(our_people, people, PERSON_ID_DIST_M)
    vehicle_ids = identities(our_vehicles, vehicles, VEHICLE_ID_DIST_M)
    pairs, missed, extra = match(truth, found, person_ids, vehicle_ids)
    missed_b, extra_b = boundary_flags(missed, extra, people, vehicles, our_people, our_vehicles, person_ids, vehicle_ids)
    return {"clip": clip, "truth": {"pedestrians": len(people), "conflicts": len(truth),
                                    "serious": sum(e["tier"] == "serious" for e in truth)},
            "pipeline": {"exposure": data.get("exposure"), "conflicts": len(found),
                         "serious": sum(e["tier"] == "serious" for e in found)},
            "matched": len(pairs), "missed": len(missed), "extra": len(extra),
            "missed_at_threshold": sum(missed_b), "extra_at_threshold": sum(extra_b),
            "pet_abs_error_s": [round(abs(t["pet_s"] - f["pet_s"]), 1) for t, f in pairs],
            "speed_error_kmh": [round(f["vehicle_kmh"] - t["vehicle_kmh"], 1) for t, f in pairs],
            "missed_events": [{**{k: e[k] for k in ("tier", "pet_s", "t_person_s", "vehicle_kmh")}, "at_threshold": b}
                              for e, b in zip(missed, missed_b)],
            "extra_events": [{**{k: e[k] for k in ("tier", "pet_s", "t_person_s", "vehicle_kmh")}, "at_threshold": b}
                             for e, b in zip(extra, extra_b)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", type=Path)
    parser.add_argument("videos", type=Path)
    parser.add_argument("clips", nargs="+")
    parser.add_argument("--grid", type=int, default=1, help="person_grid: tile crowded frames for SAM")
    parser.add_argument("--mode", choices=("video", "crowd"), default="video", help="person_mode")
    args = parser.parse_args()
    out = Path("out/dut")
    out.mkdir(parents=True, exist_ok=True)
    results = [check_clip(args.repo, args.videos, clip, out, args.grid, args.mode) for clip in args.clips]
    (out / "validation.json").write_text(json.dumps(results, indent=1))
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
