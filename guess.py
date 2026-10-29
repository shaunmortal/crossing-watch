"""People vs the machine: the X replies to "How fast was this bike? Guess in km/h." against the measured speed.
Copy one reply per line into replies.txt, then: python3 guess.py replies.txt out/VIDEO/events.json --event 1"""
import argparse
import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path

MIN_KMH, MAX_KMH = 5, 150  # a reply outside this is a joke or a typo, not a guess
BIN_KMH = 10               # one bar per 10 km/h
TICK_KMH = 30              # an axis label every 30 km/h
WIDTH_PX, HEIGHT_PX = 640, 320
LEFT_PX, RIGHT_PX, TOP_PX, BOTTOM_PX = 20, 20, 72, 32  # room for the caption above and the axis below
RED = "#c0392b"            # the evidence page's accent red
NUMBER = re.compile(r"\d+(?:\.\d+)?")
HANDLE = re.compile(r"@\w+")  # "@ravi99 40" guessed 40, not 99


def guesses(text):
    """km/h guesses, one reply per line: the first number on each line, kept only from MIN_KMH to MAX_KMH."""
    found = (NUMBER.search(HANDLE.sub("", line)) for line in text.splitlines())
    return [float(m[0]) for m in found if m and MIN_KMH <= float(m[0]) <= MAX_KMH]


def caption(kept, measured_kmh):
    return f"{len(kept)} guesses, median {statistics.median(kept):g} km/h. Measured: {measured_kmh:g} km/h."


def svg(kept, measured_kmh):
    """A standalone SVG: the guesses as bars per BIN_KMH, a red line at the measured speed, the caption on top."""
    top = max(MAX_KMH, math.ceil(measured_kmh / BIN_KMH) * BIN_KMH)
    width, height = WIDTH_PX - LEFT_PX - RIGHT_PX, HEIGHT_PX - TOP_PX - BOTTOM_PX
    x = lambda kmh: LEFT_PX + kmh / top * width
    bins = Counter(int(min(g, top - BIN_KMH) // BIN_KMH) for g in kept)  # exactly 150 joins the 140-150 bar
    unit = height / max(bins.values())
    bars = "".join(f'<rect class="bar" x="{x(b * BIN_KMH) + 1:.1f}" y="{TOP_PX + height - n * unit:.1f}" '
                   f'width="{x(BIN_KMH) - LEFT_PX - 2:.1f}" height="{n * unit:.1f}" fill="#2f7de1"/>'
                   for b, n in sorted(bins.items()))
    counts = "".join(f'<text x="{x((b + 0.5) * BIN_KMH):.1f}" y="{TOP_PX + height - n * unit - 4:.1f}" '
                     f'stroke="#fafaf7" stroke-width="4" paint-order="stroke">{n}</text>' for b, n in bins.items())
    ticks = "".join(f'<text x="{x(t):.1f}" y="{HEIGHT_PX - 10}">{t}</text>' for t in range(0, top + 1, TICK_KMH))
    at = f"{x(measured_kmh):.1f}"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH_PX} {HEIGHT_PX}" role="img" '
            f'aria-label="{caption(kept, measured_kmh)}" font-family="system-ui, sans-serif" font-size="13" '
            f'text-anchor="middle"><rect width="100%" height="100%" fill="#fafaf7"/>'
            f'<text x="{LEFT_PX}" y="28" font-size="18" font-weight="bold" text-anchor="start">'
            f'{caption(kept, measured_kmh)}</text>{bars}{ticks}'
            f'<line x1="{LEFT_PX}" y1="{TOP_PX + height}" x2="{WIDTH_PX - RIGHT_PX}" y2="{TOP_PX + height}" '
            f'stroke="#1d1d1b"/><line class="measured" x1="{at}" y1="{TOP_PX - 10}" x2="{at}" y2="{TOP_PX + height}" '
            f'stroke="{RED}" stroke-width="3"/><text x="{at}" y="{TOP_PX - 16}" fill="{RED}" font-weight="bold">'
            f'measured {measured_kmh:g} km/h</text>{counts}</svg>')  # counts last, so the red line never hides one


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("replies", type=Path, help="one X reply per line, copied by hand")
    parser.add_argument("events", type=Path, help="events.json of the video in the post")
    parser.add_argument("--event", type=int, default=1, help="card number of the near-miss in the post (#1 first)")
    parser.add_argument("--out", type=Path, help="default: guess.svg next to the replies")
    args = parser.parse_args()
    text = args.replies.read_text(encoding="utf-8")
    kept = guesses(text)
    events = json.loads(args.events.read_text())["events"]
    if not kept:
        raise SystemExit(f"no guesses from {MIN_KMH} to {MAX_KMH} km/h in {args.replies}")
    if not 1 <= args.event <= len(events):
        raise SystemExit(f"{args.events} has events #1 to #{len(events)}, not #{args.event}")
    measured = events[args.event - 1]["vehicle_kmh"]
    out = args.out or args.replies.with_name("guess.svg")
    out.write_text(svg(kept, measured))
    replies = sum(1 for line in text.splitlines() if line.strip())
    print(f"{caption(kept, measured)} {len(kept)} of {replies} replies kept. Chart: {out}")


if __name__ == "__main__":
    main()
