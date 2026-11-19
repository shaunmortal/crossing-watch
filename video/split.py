"""Hero split shot for the video: the blurred evidence clip on the left and, on the right, the same frames seen from
above in road metres: the pedestrian's footsteps and feet (cyan), the vehicle's footprint (red), the 1 m ring round
the spot from when the first of the two got there (yellow) and the gap clock, which freezes in red like the page's.
Run: python3 video/split.py OUT_DIR N [--to FILE]   (N as in eventN.mp4; needs that event's "replay" from analyze.py)
The map frames are SVG tiles on one page, screenshotted once by headless Chrome; ffmpeg then steps through the tiles,
one per frame, beside the clip. Chrome is looked for in the usual places; elsewhere set CHROME=/path/to/chrome (any
Chromium works). No sound: a horn, only if Muse Wonder heard one, is laid in by the editor."""
import argparse
import html
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the repo's modules, however this is run
import overlay  # noqa: E402
import render  # noqa: E402
import road  # noqa: E402
import roadmap  # noqa: E402

TILE = (960, 540)     # each half of the shot; the clip is scaled to this height, so the two make 1920 wide
HEADER_PX, FOOTER_PX = 78, 48  # bands of the tile kept clear of the map for the clock, and for the scale bar
COLS = 8              # tiles per row of the screenshot page (8 x 960 px stays well under Chrome's size limits)
SLACK_S = 0.01        # the page clock's float allowance, so both clocks freeze on the same frame
CHROME_TIMEOUT_S = 120  # a full sheet takes a few seconds; past this Chrome has hung
CHROMES = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium",
           "chromium-browser")
STYLE = ("body{margin:0}svg{display:block;float:left;background:#161616;font:600 28px ui-monospace,monospace}"
         ".grid{stroke:#333}.steps{fill:none;stroke:cyan;stroke-width:4;opacity:.6}.feet{fill:cyan}"
         ".drive{fill:none;stroke:red;stroke-width:4;opacity:.5}"
         ".veh{fill:rgba(255,0,0,.35);stroke:red;stroke-width:10;stroke-linejoin:round}"
         ".ring{fill:none;stroke:yellow;stroke-width:3}.clock{fill:rgba(0,0,0,.65)}.frozen{fill:#c0392b}"
         "text{fill:#fff}.small{font:400 20px system-ui,sans-serif;fill:#aaa}.bar{stroke:#aaa;stroke-width:3}")


def clock(e, since):
    """The gap clock `since` seconds after the first of the two reached the spot, read as the evidence page's clock:
    (text, frozen), or None before then."""
    if since < -SLACK_S:
        return None
    if since >= e["pet_s"] - SLACK_S:
        return f'{e["pet_s"]:.1f} s, {overlay.tier_word(e)}', True
    return f"{math.floor(max(0, since + SLACK_S) * 10) / 10:.1f} s", False


def held(replay, n, key):
    """Frame n's measured point or shape, else the one just before it within render.HOLD_FRAMES (crowd mode finds
    people every 2nd frame), else None."""
    return next((replay[k][key] for k in range(n, max(-1, n - render.HOLD_FRAMES - 1), -1) if replay[k][key]), None)


def fit(e):
    """(metres -> (x, y) tile pixels, pixels per metre, visible (x0, y0, x1, y1) in metres): everything the replay
    measured and the spot, with roadmap's margin, centred in the tile between its header and footer."""
    (w, h), band = TILE, TILE[1] - HEADER_PX - FOOTER_PX
    points = [p for r in e["replay"] for p in ([r["person"]] if r["person"] else []) + (r["vehicle"] or [])]
    x0, y0, x1, y1 = roadmap.bounds(points + ([e["where"]] if e.get("where") else []))
    scale = min(w / (x1 - x0), band / (y1 - y0))
    x0, y0 = (x0 + x1 - w / scale) / 2, (y0 + y1 - band / scale) / 2 - HEADER_PX / scale
    return (lambda p: ((p[0] - x0) * scale, (p[1] - y0) * scale)), scale, (x0, y0, x0 + w / scale, y0 + h / scale)


def tile(e, n, fps, px, scale, view):
    """The SVG of replay frame n: a grid every roadmap.GRID_M, the vehicle's earlier footprints (faint) and the
    pedestrian's footsteps so far, the ring, the footprint and feet now, the clock."""
    replay, (w, h), grid = e["replay"], TILE, roadmap.GRID_M
    points = lambda ps: " ".join(f"{x:.1f},{y:.1f}" for x, y in map(px, ps))
    feet, shape = held(replay, n, "person"), held(replay, n, "vehicle")
    shown = clock(e, replay[n]["frame"] / fps - min(e["t_person_s"], e["t_vehicle_s"]))
    xs = [px((grid * k, 0))[0] for k in range(math.ceil(view[0] / grid), math.floor(view[2] / grid) + 1)]
    ys = [px((0, grid * k))[1] for k in range(math.ceil(view[1] / grid), math.floor(view[3] / grid) + 1)]
    lines = "".join(f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{h}"/>' for x in xs) + "".join(
        f'<line x1="0" y1="{y:.1f}" x2="{w}" y2="{y:.1f}"/>' for y in ys)
    drive = "".join(f'<polygon class="drive" points="{points(r["vehicle"])}"/>' for r in replay[:n] if r["vehicle"])
    steps = points(r["person"] for r in replay[:n + 1] if r["person"])
    marks = [f'<g class="grid">{lines}</g>{drive}<polyline class="steps" points="{steps}"/>']
    if shown and e.get("where"):
        marks.append('<circle class="ring" cx="{:.1f}" cy="{:.1f}" r="{:.1f}"/>'.format(
            *px(e["where"]), road.CONFLICT_RADIUS_M * scale))
    if shape:
        marks.append(f'<polygon class="veh" points="{points(shape)}"/>')
    if feet:
        marks.append('<circle class="feet" cx="{:.1f}" cy="{:.1f}" r="9"/>'.format(*px(feet)))
    if shown:
        text, frozen = shown
        marks.append(f'<rect class="clock{" frozen" if frozen else ""}" x="16" y="16" rx="6" height="46" '
                     f'width="{24 + 17 * len(text)}"/><text x="28" y="50">{html.escape(text)}</text>')
    marks.append(f'<line class="bar" x1="16" y1="{h - 20}" x2="{16 + grid * scale:.1f}" y2="{h - 20}"/>'
                 f'<text class="small" x="16" y="{h - 30}">{grid:g} m</text><text class="small" x="{w - 16}" '
                 f'y="{h - 20}" text-anchor="end">Seen from above, in road metres</text>')
    return f'<svg width="{w}" height="{h}">{"".join(marks)}</svg>'


def page(e, fps):
    """One HTML page with every frame's tile, COLS to a row, for a single screenshot."""
    px, scale, view = fit(e)
    tiles = "".join(tile(e, n, fps, px, scale, view) for n in range(len(e["replay"])))
    return f'<!doctype html><meta charset="utf-8"><style>{STYLE}</style><body style="width:{COLS * TILE[0]}px">{tiles}'


def screenshot(page_file, png, frames):
    """One headless-Chrome screenshot of the tile page, one image pixel per CSS pixel, in a throwaway profile."""
    chrome = os.environ.get("CHROME") or next((c for c in map(shutil.which, CHROMES) if c), None)
    if not chrome:
        raise SystemExit("no Chrome or Chromium found for the map frames: set CHROME=/path/to/chrome")
    size = COLS * TILE[0], math.ceil(frames / COLS) * TILE[1]
    try:
        with tempfile.TemporaryDirectory() as profile:
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            "--force-device-scale-factor=1", f"--user-data-dir={profile}",
                            f"--window-size={size[0]},{size[1]}", f"--screenshot={png}",
                            Path(page_file).resolve().as_uri()], check=True, capture_output=True, timeout=CHROME_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as err:
        raise SystemExit(f"headless Chrome failed ({err}); set CHROME=/path/to/chrome") from err
    if not Path(png).exists():
        raise SystemExit(f"{chrome} wrote no screenshot of {page_file}")


def stack(clip, sheet, frames, fps, out_path):
    """The clip, scaled to the tile height, beside tile n of the sheet on frame n (ffmpeg crop is evaluated per frame)."""
    w, h = TILE
    step = f"crop={w}:{h}:'mod(n,{COLS})*{w}':'floor(n/{COLS})*{h}'"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-loop", "1", "-framerate", str(fps),
                    "-i", str(sheet), "-filter_complex", f"[0:v]scale=-2:{h},setsar=1,format=yuv420p[l];"
                    f"[1:v]{step},setsar=1,format=yuv420p[r];[l][r]hstack=shortest=1", "-frames:v", str(frames),
                    "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)],
                   check=True)
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", help="the analysis folder analyze.py wrote")
    parser.add_argument("event", type=int, help="N of the evidence clip eventN.mp4")
    parser.add_argument("--to", help="output video (default FOLDER/eventN-hero.mp4)")
    args = parser.parse_args()
    folder = Path(args.folder)
    data = json.loads((folder / "events.json").read_text())
    e = next((e for e in data["events"] if e.get("clip") == f"event{args.event}.mp4"), None)
    if not (e and e.get("replay")):
        raise SystemExit(f"event{args.event}.mp4 in {folder}/events.json has no replay: re-run analyze.py there "
                         "(SAM replies are cached)")
    out_path = Path(args.to or folder / f"event{args.event}-hero.mp4")
    with tempfile.TemporaryDirectory() as tmp:
        page_file, sheet = Path(tmp) / "tiles.html", Path(tmp) / "tiles.png"
        page_file.write_text(page(e, data["fps"]))
        screenshot(page_file, sheet, len(e["replay"]))
        print(stack(folder / e["clip"], sheet, len(e["replay"]), data["fps"], out_path))


if __name__ == "__main__":
    main()
