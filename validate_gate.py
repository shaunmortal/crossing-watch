"""Speed check on our own gate camera (gate G6 in GATES.md): each vehicle's speed as Crossing Watch measured it,
against the time it took between two lines taped across the road, logged by hand frame by frame.

The site file's "trap" holds the four tape marks, two on each kerb, clicked in the calibration frame going round as
calibrate.html marks a rectangle (line A near kerb, line B near kerb, line B far kerb, line A far kerb), and the
taped distance between the two lines:  "trap": {"image_points": [[x, y], [x, y], [x, y], [x, y]], "distance_m": 15}
The log is a CSV with the columns line_a_s and line_b_s (others are ignored), one row per vehicle: the seconds into
the video given to analyze.py, read on that file at its own frame rate (never on clip.mp4), when the vehicle's front
wheel touched line A and line B, in either order.
$0: the run's tracks are rebuilt from its cached SAM replies (validate_dut.our_tracks); a cache miss stops the check.
Run: python3 validate_gate.py SITE.json OUT_DIR TRAP.csv     (OUT_DIR: the analyze.py run's --out folder)
"""
import argparse
import csv
import math
import statistics
from pathlib import Path

import analyze
import crowd
import road
import sam
import validate_dut
import validate_offline

MATCH_M = 1.5         # a track is the logged vehicle when its shape is this close to each line at the logged moment
MIN_SPEEDS = 3        # frames with a measured speed needed between the two moments
# G6, pre-registered in GATES.md before any trap footage; never changed after it arrives:
BAND_PCT, BAND_KMH = 15.0, 2.0  # a vehicle agrees within the larger of these
PASS_SHARE = 0.8      # at least this share of matched vehicles agree...
MAX_LEAN_PCT = 10.0   # ...and their median signed error is within this
MIN_VEHICLES = 20     # fewer matched vehicles than this: G6 is not tested


def trap_lines(site, H):
    """(line A, line B) in road metres, each as its (near kerb, far kerb) marks."""
    a_near, b_near, b_far, a_far = marks = [road.to_ground(H, *p) for p in site["trap"]["image_points"]]
    if None in marks or a_near == a_far or b_near == b_far:
        raise SystemExit("trap: click four different tape marks on the road, below the horizon")
    return (a_near, a_far), (b_near, b_far)


def signed_m(p, line):
    """Signed distance in metres from p to the line through two marks."""
    (ax, ay), (bx, by) = line
    return ((bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)) / math.dist(*line)


def line_gap(shape, line):
    """Metres from a vehicle shape to a line across the road, 0 when the line runs through it."""
    d = [signed_m(q, line) for q in shape]
    return 0.0 if min(d) <= 0 <= max(d) else min(map(abs, d))


def lines_apart(a, b):
    """How far apart the calibration puts the two lines: each line's marks from the other line, averaged."""
    return statistics.mean([abs(signed_m(p, b)) for p in a] + [abs(signed_m(p, a)) for p in b])


def read_log(path):
    """[(seconds at line A, seconds at line B)] per logged vehicle."""
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    log = []
    for n, row in enumerate(rows, 2):
        try:
            times = (float(row["line_a_s"]), float(row["line_b_s"]))
        except (KeyError, TypeError, ValueError):
            raise SystemExit(f"{path} line {n}: line_a_s and line_b_s must be seconds") from None
        if not all(math.isfinite(t) and t >= 0 for t in times) or times[0] == times[1]:
            raise SystemExit(f"{path} line {n}: two different times of 0 s or more are needed")
        log.append(times)
    return log


def on_line(shapes, line, t, fps):
    """True when a track's shape at `t` seconds is within MATCH_M of the line."""
    shape = shapes.get(round(t * fps))
    return shape is not None and line_gap(shape, line) <= MATCH_M


def check(vehicles, lines, distance_m, log, fps=analyze.FPS):
    """Per logged vehicle: its trap speed and, when exactly one track was on line A and on line B at the logged
    moments, that track and its median measured speed between them (km/h); else why not."""
    speed_of = {vid: road.speeds(shapes, fps) for vid, shapes in vehicles.items()}
    rows = []
    for t_a, t_b in log:
        row = {"line_a_s": t_a, "line_b_s": t_b, "trap_kmh": distance_m / abs(t_b - t_a) * 3.6, "vehicle": None,
               "ours_kmh": None}
        fits = [vid for vid, shapes in vehicles.items()
                if on_line(shapes, lines[0], t_a, fps) and on_line(shapes, lines[1], t_b, fps)]
        if len(fits) != 1:
            rows.append({**row, "why": "no track on both lines" if not fits else f"{len(fits)} tracks on both lines"})
            continue
        lo, hi = sorted((round(t_a * fps), round(t_b * fps)))
        measured = [v for f, v in speed_of[fits[0]].items() if lo <= f <= hi]
        if len(measured) < MIN_SPEEDS:
            rows.append({**row, "vehicle": fits[0], "why": "too few measured speeds"})
            continue
        rows.append({**row, "vehicle": fits[0], "ours_kmh": statistics.median(measured) * 3.6, "why": None})
    return rows


def agrees(trap_kmh, ours_kmh):
    return abs(ours_kmh - trap_kmh) <= max(BAND_PCT / 100 * trap_kmh, BAND_KMH)


def g6(pairs):
    """G6's verdict on the matched (trap km/h, our km/h) pairs, by the rule pre-registered in GATES.md."""
    if len(pairs) < MIN_VEHICLES:
        return f"G6 NOT TESTED: {len(pairs)} matched vehicles, {MIN_VEHICLES} needed"
    agree = sum(agrees(t, o) for t, o in pairs)
    lean = statistics.median(100 * (o - t) / t for t, o in pairs)
    passed = agree >= PASS_SHARE * len(pairs) and abs(lean) <= MAX_LEAN_PCT
    return (f"G6 {'PASS' if passed else 'FAIL'}: {agree} of {len(pairs)} within {BAND_PCT:.0f}% or {BAND_KMH:.0f} km/h "
            f"({PASS_SHARE:.0%} needed), median error {lean:+.1f}% (within ±{MAX_LEAN_PCT:.0f}% needed)")


def report(rows, apart_m, distance_m):
    for r in rows:
        ours = (f"ours {r['ours_kmh']:.1f} km/h ({r['vehicle']}), {r['ours_kmh'] - r['trap_kmh']:+.1f}" if r["why"] is None
                else r["why"] + (f" ({r['vehicle']})" if r["vehicle"] else ""))
        print(f"  {r['line_a_s']:.2f} s -> {r['line_b_s']:.2f} s: trap {r['trap_kmh']:.1f} km/h, {ours}")
    pairs = [(r["trap_kmh"], r["ours_kmh"]) for r in rows if r["why"] is None]
    print(f"{len(pairs)} of {len(rows)} logged vehicles matched to one track")
    if pairs:
        errors = sorted(abs(o - t) for t, o in pairs)
        print(f"ours minus trap: mean {statistics.mean(o - t for t, o in pairs):+.2f} km/h, median |error| "
              f"{statistics.median(errors):.2f}, 95th percentile {road.percentile(errors, 0.95):.2f}, "
              f"worst {errors[-1]:.2f} km/h")
    print(f"the calibration puts the lines {apart_m:.2f} m apart; the tape says {distance_m} m "
          f"({100 * (apart_m / distance_m - 1):+.1f}%)")
    print(g6(pairs))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", help="the site file of the run, with its \"trap\"")
    parser.add_argument("out", type=Path, help="the analyze.py run's --out folder")
    parser.add_argument("log", type=Path, help="CSV of hand-logged line times")
    args = parser.parse_args()
    site = analyze.load_site(args.site)
    if "trap" not in site:
        raise SystemExit(f"{args.site} has no \"trap\": see this script's first lines")
    sam.request = crowd.request = analyze.encode = validate_offline.offline  # $0: never call SAM or re-encode
    lines = trap_lines(site, road.homography(site["image_points"], site["world_points"]))
    *_, vehicles, _ = validate_dut.our_tracks(site, args.out)
    distance_m = site["trap"]["distance_m"]
    report(check(vehicles, lines, distance_m, read_log(args.log)), lines_apart(*lines), distance_m)


if __name__ == "__main__":
    main()
