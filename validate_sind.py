"""Check the near-miss maths on real ground-truth trajectories: the SinD public sample (Tianjin, drone, 20 min,
pedestrians and mixed traffic in metres). Our PET is compared with the textbook conflict-zone PET (Allen et al.
1978: time from the first road user leaving the conflict spot to the second arriving), computed independently.

Data (non-commercial; not in this repo): https://github.com/SOTIF-AVLab/SinD, Data/Tianjin/8_2_1/
Run: python3 validate_sind.py data/sind
"""
import argparse
import csv
import json
import math
import statistics
import time
from pathlib import Path

import road

FPS = 10
ZONE_M = road.CONFLICT_RADIUS_M  # conflict spot radius, the same 1 m both methods use
WINDOW_S = 10                    # textbook PET looks at the vehicle this long either side of the event


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
    """Our speed (median of position steps) against SinD's own velocity, km/h: (mean, 95th percentile)."""
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


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    people, vehicles, true_speed = load(args.folder)
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
