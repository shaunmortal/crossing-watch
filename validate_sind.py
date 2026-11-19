"""Check the near-miss maths on real ground-truth trajectories: the SinD public sample (Tianjin, drone, 20 min,
pedestrians and mixed traffic in metres). Our PET is compared with the textbook conflict-zone PET (Allen et al.
1978: time from the first road user leaving the conflict spot to the second arriving), computed independently.

With --oblique HEIGHT,BACK it instead films the same trajectories with a simulated phone HEIGHT m up and BACK m
behind the crossing, turns each vehicle into the box SAM would see, and compares the conflicts found from the lower
box edge and from car-shaped footprints (road.vehicle_footprints) with those from SinD's true footprints.

Data (non-commercial; not in this repo): https://github.com/SOTIF-AVLab/SinD, Data/Tianjin/8_2_1/
Run: python3 validate_sind.py data/sind [--oblique 10,25]
"""
import argparse
import sys
import csv
import json
import math
import random
import statistics
import time
from pathlib import Path

import road

FPS = 10
ZONE_M = road.CONFLICT_RADIUS_M  # conflict spot radius, the same 1 m both methods use
WINDOW_S = 10                    # textbook PET looks at the vehicle this long either side of the event
FOCAL_PX = 1500.0                # simulated phone camera: focal length in pixels
MIN_DEPTH_M = 0.5                # ...which sees nothing closer than this
CALIBRATION_M = 5.0              # simulated calibration: four road points this far either way of the crossing
BOX_NOISE_PX = 3.0               # robustness rows: SAM box edges off by this much (standard deviation)...
SIZE_ERROR = 1.2                 # ...or every footprint length this many times too long
HEIGHT_M = {"car": 1.5, "bus": 3.0, "truck": 3.0, "motorcycle": 1.3, "bicycle": 1.3, "tricycle": 1.6}  # box tops


def load(folder):
    people, vehicles, true_speed = {}, {}, {}
    for row in csv.DictReader(open(folder / "Ped_smoothed_tracks.csv")):
        people.setdefault(row["track_id"], {})[int(row["frame_id"])] = (float(row["x"]), float(row["y"]))
    for row in csv.DictReader(open(folder / "Veh_smoothed_tracks.csv")):
        vid = f"{row['agent_type']}#{row['track_id']}"
        x, y, yaw = float(row["x"]), float(row["y"]), float(row["yaw_rad"])
        half_l, half_w = float(row["length"]) / 2, float(row["width"]) / 2
        c, s = math.cos(yaw), math.sin(yaw)
        corners = tuple((x + dx * c - dy * s, y + dx * s + dy * c)
                        for dx, dy in ((half_l, half_w), (half_l, -half_w), (-half_l, -half_w), (-half_l, half_w)))
        vehicles.setdefault(vid, {})[int(row["frame_id"])] = corners
        true_speed.setdefault(vid, {})[int(row["frame_id"])] = math.hypot(float(row["vx"]), float(row["vy"]))
    return people, vehicles, true_speed


CELL_M = 0.5  # conflict-area raster


def runs(frames):
    """Contiguous runs of frame numbers as (first, last) pairs."""
    out = []
    for f in sorted(frames):
        if out and f == out[-1][1] + 1:
            out[-1] = (out[-1][0], f)
        else:
            out.append((f, f))
    return out


def textbook_pet(feet, shapes):
    """Allen et al. (1978) PET over a conflict AREA: the road cells both the pedestrian's path and the vehicle's swept
    path (grown by ZONE_M) covered. PET is the gap between one leaving that area and the other entering it,
    0 when both were inside at once; None when the paths never meet. Independent of road.closest_pass."""
    cell = lambda p: (math.floor(p[0] / CELL_M), math.floor(p[1] / CELL_M))
    centre = lambda c: ((c[0] + 0.5) * CELL_M, (c[1] + 0.5) * CELL_M)
    ped_cells = {cell(p) for p in feet.values()}
    area = {c for c in ped_cells if any(road.footprint_distance(centre(c), s) <= ZONE_M for s in shapes.values())}
    if not area:
        return None
    ped_runs = runs(f for f, p in feet.items() if cell(p) in area)
    veh_runs = runs(f for f, s in shapes.items() if any(road.footprint_distance(centre(c), s) <= ZONE_M for c in area))
    gaps = [max(0, v0 - p1, p0 - v1) for p0, p1 in ped_runs for v0, v1 in veh_runs]
    return min(gaps) / FPS


def compare(people, vehicles, events):
    rows = []
    for e in events:
        near = round(e["t_vehicle_s"] * FPS)
        window = {f: s for f, s in vehicles[e["vehicle"]].items() if abs(f - near) <= WINDOW_S * FPS}
        rows.append({"person": e["person"], "vehicle": e["vehicle"], "tier": e["tier"], "ours_s": e["pet_s"],
                     "textbook_s": textbook_pet(people[e["person"]], window), "vehicle_kmh": e["vehicle_kmh"]})
    return rows


def speed_error(vehicles, true_speed):
    """Our speed (least-squares slope of positions) against SinD's own velocity, km/h: (mean, 95th percentile)."""
    errors = sorted(abs(v - true_speed[vid][f]) * 3.6 for vid, shapes in vehicles.items()
                    for f, v in road.speeds(shapes, FPS).items())
    return statistics.mean(errors), errors[int(0.95 * len(errors))]


def summarise(people, vehicles, events, rows, seconds, speed):
    diffs = [abs(r["ours_s"] - r["textbook_s"]) for r in rows if r["textbook_s"] is not None]
    same_tier = sum(1 for r in rows if r["textbook_s"] is not None
                    and (r["textbook_s"] < road.PET_MAX_S) == (r["tier"] == "serious"))
    frames = max(max(t) for t in people.values()) + 1
    return {"exposure": road.exposure(people, vehicles, FPS, frames), "conflicts": len(events),
            "serious": sum(e["tier"] == "serious" for e in events), "search_seconds": round(seconds, 1),
            "pet_vs_textbook": {"compared": len(diffs),
                                "mean_abs_diff_s": round(statistics.mean(diffs), 2) if diffs else None,
                                "within_0_5_s": sum(d <= 0.5 for d in diffs), "same_tier": same_tier},
            "speed_error_kmh": {"mean": round(speed[0], 2), "p95": round(speed[1], 2)},
            "by_vehicle_type": {k: sum(e["vehicle"].startswith(k + "#") for e in events)
                                for k in sorted({v.split("#")[0] for v in vehicles})}}


def camera(centre, height, back, focal=FOCAL_PX):
    """project(x, y, z) -> image pixel, or None out of view, for a phone `height` m up and `back` m behind road point
    `centre` (towards -y), looking at it; image y grows downwards."""
    n = math.hypot(height, back)
    fwd, down = (back / n, -height / n), (-height / n, -back / n)  # (y, z) parts; the image x axis is world x

    def project(x, y, z):
        d = (x - centre[0], y - centre[1] + back, z - height)
        depth = d[1] * fwd[0] + d[2] * fwd[1]
        if depth <= MIN_DEPTH_M:
            return None
        return focal * d[0] / depth, focal * (d[1] * down[0] + d[2] * down[1]) / depth
    return project


def box(project, corners, height):
    """The box [x1, y1, x2, y2] SAM would draw round a vehicle `height` m tall standing on `corners`, or None."""
    pixels = [project(x, y, z) for x, y in corners for z in (0.0, height)]
    if None in pixels:
        return None
    us, vs = [p[0] for p in pixels], [p[1] for p in pixels]
    return [min(us), min(vs), max(us), max(vs)]


def calibration(project, centre):
    """road.homography from four road points round `centre` and their pixels, as calibrate.html marks them."""
    world = [[centre[0] + dx * CALIBRATION_M, centre[1] + dy * CALIBRATION_M]
             for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    return road.homography([list(project(x, y, 0.0)) for x, y in world], world)


def class_sizes(vehicles):
    """{type: (median length, median width)} of SinD's own footprints: a tape-measured "vehicle_sizes_m"."""
    dims = {}
    for vid, shapes in vehicles.items():
        a, b, _, d = next(iter(shapes.values()))  # load() lists the corners round the vehicle, front first
        dims.setdefault(vid.split("#")[0], []).append((math.dist(a, d), math.dist(a, b)))
    return {kind: (statistics.median(l for l, _ in d), statistics.median(w for _, w in d)) for kind, d in dims.items()}


def oblique_rows(people, vehicles, height, back):
    """[(method, vehicle shapes)]: SinD's footprints on the frames the simulated phone sees, the lower box edge, the
    car-shaped footprint, and the footprint again with noisy boxes or lengths SIZE_ERROR times too long."""
    centre = road.median_point([p for t in people.values() for p in t.values()])
    project = camera(centre, height, back)
    H = calibration(project, centre)
    boxes = {vid: {f: b for f, s in shapes.items() if (b := box(project, s, HEIGHT_M[vid.split("#")[0]]))}
             for vid, shapes in vehicles.items()}
    rng = random.Random(1)
    noisy = {vid: {f: [v + rng.gauss(0, BOX_NOISE_PX) for v in b] for f, b in t.items()} for vid, t in boxes.items()}
    sizes = class_sizes(vehicles)
    long = {kind: (length * SIZE_ERROR, width) for kind, (length, width) in sizes.items()}
    fitted = lambda tracks, size: {vid: road.vehicle_footprints(t, H, size[vid.split("#")[0]], FPS)
                                   for vid, t in tracks.items()}
    return [("SinD footprints (truth)", {vid: {f: vehicles[vid][f] for f in t} for vid, t in boxes.items()}),
            ("lower box edge (before)", {vid: road.vehicle_edges(t, H) for vid, t in boxes.items()}),
            ("car-shaped footprint", fitted(boxes, sizes)),
            (f"footprint, boxes off by {BOX_NOISE_PX:g} px", fitted(noisy, sizes)),
            (f"footprint, lengths {SIZE_ERROR - 1:.0%} too long", fitted(boxes, long))]


def oblique_table(people, rows):
    """Markdown table: each method's conflicts against those from the true footprints (the first row)."""
    found = [(name, {(e["person"], e["vehicle"]): e for e in road.conflicts(people, shapes, FPS)})
             for name, shapes in rows]
    truth = found[0][1]
    serious = lambda events: {k for k, e in events.items() if e["tier"] == "serious"}
    lines = ["| Vehicle shape | Conflicts | Serious | Serious missed | Serious extra | PET vs truth (mean) |",
             "|---|---|---|---|---|---|"]
    for name, events in found:
        diffs = [events[k]["pet_s"] - truth[k]["pet_s"] for k in events.keys() & truth.keys()]
        pet = f"{statistics.mean(diffs):+.2f} s" if diffs else "-"
        lines.append(f"| {name} | {len(events)} | {len(serious(events))} | {len(serious(truth) - serious(events))} | "
                     f"{len(serious(events) - serious(truth))} | {pet} |")
    return "\n".join(lines)


def camera_place(text):
    height, back = (float(v) for v in text.split(","))
    if not (height > 0 and back > 0):
        raise ValueError
    return height, back


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--oblique", type=camera_place, metavar="HEIGHT,BACK",
                        help="simulate a phone HEIGHT m up and BACK m back and compare vehicle shapes (prints only)")
    args = parser.parse_args()
    if not (args.folder / "Ped_smoothed_tracks.csv").is_file():
        sys.exit(f"validate_sind.py: no Ped_smoothed_tracks.csv in {args.folder}; download SinD's public sample from "
                 "github.com/SOTIF-AVLab/SinD (non-commercial) into that folder")
    people, vehicles, true_speed = load(args.folder)
    if args.oblique:
        print(f"phone {args.oblique[0]:g} m up, {args.oblique[1]:g} m back:")
        print(oblique_table(people, oblique_rows(people, vehicles, *args.oblique)))
        return
    started = time.time()
    events = road.conflicts(people, vehicles, FPS)
    seconds = time.time() - started
    rows = compare(people, vehicles, events)
    summary = summarise(people, vehicles, events, rows, seconds, speed_error(vehicles, true_speed))
    out = Path("out/sind")
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps({"summary": summary, "events": rows}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
