"""The fix drawn where people cross. A magenta band marks the strip of road where the near-misses were measured;
Muse Image is asked to draw the fix inside it, and only the band's pixels are kept (never the people in it), so every
other pixel stays the real, blurred street. Over that go the near-miss dots, the walked paths and the band's size in
metres, all placed by the road geometry, not by the model.

Kill test, one or two Muse Image calls ($0.01 each), with a band given in road metres:
python3 fixband.py OUT_DIR SITE.json DEST --band="x,y x,y x,y x,y"
"""
import argparse
import base64
import html
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import ailabel
import road
import sam

BAND_MARGIN_M = 1.0     # the band runs this far past the walked paths and the near-miss spots
BAND_MIN_WIDTH_M = 3.0  # and is at least this wide along the road (room to draw a crossing, not a design width)
GUIDE_OPACITY = 0.6     # magenta over the road, which still shows through so Muse Image sees what it replaces
FEATHER_PX = 2          # gblur sigma on the band's edge, so the seam does not show
SSIM_MIN = 0.5          # outside the band, kids-cctv's earlier Muse Image edit scores 0.65; moved 8 px, 0.36
SHARE_STEP_PX = 4       # the band's share of the photo is counted on this grid
MARK_SHARE = 0.011      # near-miss dot radius, as a share of the photo's width
TEXT_SHARE = 0.026      # label height, as a share of the photo's width
ROWS, COLS = ("top", "middle", "bottom"), ("left", "centre", "right")
FIX = "a raised zebra crossing"  # the kill test's fix
STRONGER = (" Do not crop, zoom, shift or redraw anything outside the band: outside it, the picture must match the "
            "photo exactly.")
CAPTION = "AI illustration placed from measurements, not evidence."
GUIDE, PICTURE, RETRY, KEPT = "street-guide.jpg", "street-fixed.webp", "street-fixed-retry.webp", "street-band.jpg"
TODAY, BAND = "street-dots.svg", "street-band.svg"


def heading(walks):
    """Unit vector of the way people walked, either direction counted the same; None if nobody moved."""
    # ponytail: one mean direction, so people crossing two ways at a junction average into a diagonal band
    steps = [(w[-1][0] - w[0][0], w[-1][1] - w[0][1]) for w in walks]
    steps = [(x / math.hypot(x, y), y / math.hypot(x, y)) for x, y in steps if math.hypot(x, y) > 0]
    if not steps:
        return None
    signs = [1 if x * steps[0][0] + y * steps[0][1] >= 0 else -1 for x, y in steps]
    x, y = sum(s * p[0] for s, p in zip(signs, steps)), sum(s * p[1] for s, p in zip(signs, steps))
    return x / math.hypot(x, y), y / math.hypot(x, y)  # never 0: every step agrees with the first


def band(events, margin_m=BAND_MARGIN_M, min_width_m=BAND_MIN_WIDTH_M):
    """[[x, y]] x 4 in road metres: a strip along the way people walked, over every walked path and near-miss spot,
    or None without a measured path. Corners 1-2 run along the walk, 2-3 across it."""
    placed = [e for e in events if e.get("where") and len(e.get("path_person") or []) > 1]
    along = heading([e["path_person"] for e in placed])
    if along is None:
        return None
    across = (-along[1], along[0])
    on = lambda axis, p: axis[0] * p[0] + axis[1] * p[1]
    walked = [on(along, p) for e in placed for p in e["path_person"]]
    spots = [on(across, e["where"]) for e in placed]
    mid, half = (min(spots) + max(spots)) / 2, max(max(spots) - min(spots) + 2 * margin_m, min_width_m) / 2
    corner = lambda a, c: [round(a * along[0] + c * across[0], 2), round(a * along[1] + c * across[1], 2)]
    a0, a1 = min(walked) - margin_m, max(walked) + margin_m
    return [corner(a0, mid - half), corner(a1, mid - half), corner(a1, mid + half), corner(a0, mid + half)]


def pixels(H, quad_m):
    """The band's corners in photo pixels, or None when one is behind the camera."""
    quad = [road.to_image(H, *p) for p in quad_m]
    return None if None in quad else quad


def image_size(image):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(image)], check=True, capture_output=True, text=True).stdout
    return tuple(int(v) for v in out.strip().split(","))


def inside(quad):
    """ffmpeg expression: 1 on pixels inside the (convex) quad, else 0."""
    turn = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(quad, quad[1:] + quad[:1]))
    quad = quad if turn > 0 else quad[::-1]
    return "*".join(f"gte(({x2 - x1:.2f})*(Y-({y1:.2f}))-({y2 - y1:.2f})*(X-({x1:.2f})),0)"
                    for (x1, y1), (x2, y2) in zip(quad, quad[1:] + quad[:1]))


def mask(quad, boxes=(), feather=0):
    """Filter chain from a frame to its merge mask: white inside the band, black outside and on `boxes`."""
    holes = "".join(f"*(1-between(X,{b[0]:.0f},{b[2]:.0f})*between(Y,{b[1]:.0f},{b[3]:.0f}))" for b in boxes)
    return f"format=gray,geq=lum='255*{inside(quad)}{holes}'" + (f",gblur=sigma={feather}" if feather else "") + ",format=gbrp"


def place(quad, size):
    """Where the band sits on a 3 x 3 grid of the photo, in words, e.g. "bottom left"."""
    x, y = sum(p[0] for p in quad) / len(quad), sum(p[1] for p in quad) / len(quad)
    row, col = ROWS[min(2, max(0, int(3 * y / size[1])))], COLS[min(2, max(0, int(3 * x / size[0])))]
    return "centre" if (row, col) == ("middle", "centre") else f"{row} {col}"


def instruction(fix, where):
    return (f"Replace the magenta band in the {where} of the photo with {fix}, on the road surface, filling the band "
            "exactly. Change nothing else: keep every person, vehicle, building, road marking and the camera view as "
            "they are.")


def paint_guide(photo, quad, out_path):
    """The photo with a see-through magenta band over the strip to redraw."""
    test = inside(quad)
    paint = lambda c, to: f"{c}='if({test},{c}(X,Y)+{GUIDE_OPACITY}*({to}-{c}(X,Y)),{c}(X,Y))'"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(photo), "-vf",
                    f"format=rgb24,geq={paint('r', 255)}:{paint('g', 0)}:{paint('b', 255)}", "-frames:v", "1",
                    "-q:v", "2", str(out_path)], check=True)
    return out_path


def band_share(quad, size, step=SHARE_STEP_PX):
    grid = [(x, y) for x in range(0, size[0], step) for y in range(0, size[1], step)]
    return sum(road.in_polygon(p, quad) for p in grid) / len(grid)


def ssim_outside(photo, picture, quad, size):
    """SSIM (1 = the same) of Muse Image's picture against the photo, outside the band. The photo goes back inside
    the band, where it then scores 1, and that part is taken out of the mean by its share of the frame."""
    graph = (f"[1:v]scale={size[0]}:{size[1]},format=gbrp[drawn];[0:v]format=gbrp,split=3[photo][real][m];"
             f"[m]{mask(quad)}[band];[drawn][real][band]maskedmerge[back];[photo][back]ssim")
    log = subprocess.run(["ffmpeg", "-i", str(photo), "-i", str(picture), "-filter_complex", graph, "-f", "null", "-"],
                         check=True, capture_output=True, text=True).stderr
    outside_share = 1 - band_share(quad, size)
    return 1 - (1 - float(re.search(r"All:([\d.]+)", log)[1])) / outside_share if outside_share else 1.0


def keep_band(photo, picture, quad, boxes, size, out_path):
    """The photo with Muse Image's pixels only inside the band, minus the people in it, feathered, and the visible
    AI label burned in (the re-encode drops Meta's AI tag)."""
    graph = (f"[1:v]scale={size[0]}:{size[1]},format=gbrp[drawn];[0:v]format=gbrp,split[photo][m];"
             f"[m]{mask(quad, boxes, FEATHER_PX)}[band];[photo][drawn][band]maskedmerge")
    with tempfile.TemporaryDirectory() as tmp:
        merged = Path(tmp) / "merged.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(photo), "-i", str(picture), "-filter_complex", graph,
                        "-frames:v", "1", str(merged)], check=True)
        return ailabel.burn(merged, out_path)


def to_photo(H, points):
    return [p for p in (road.to_image(H, *q) for q in points) if p]


def dots(events, H, size):
    """Each near-miss where it happened: filled red for serious, an orange ring for a close pass."""
    r, marks = MARK_SHARE * size[0], []
    for e in events:
        for x, y in to_photo(H, [e["where"]] if e.get("where") else []):
            look = ('fill="#c0392b"' if e.get("tier", "serious") == "serious"
                    else f'fill="none" stroke="#ff9f1a" stroke-width="{r / 2:.1f}"')
            marks.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" {look}/>')
    return "".join(marks)


def paths(events, H, size):
    """Where each pedestrian walked, 2 s either side of the moment."""
    lines = [to_photo(H, e.get("path_person") or []) for e in events]
    return "".join(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in line)}" fill="none" stroke="#2f7de1" '
                   f'stroke-width="{MARK_SHARE * size[0] / 2:.1f}"/>' for line in lines if len(line) > 1)


def text(x, y, words, size, anchor="middle"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-size="{TEXT_SHARE * size[0]:.1f}" '
            f'font-family="system-ui, sans-serif" font-weight="700" fill="#fff" stroke="#000" '
            f'stroke-width="{TEXT_SHARE * size[0] / 6:.1f}" paint-order="stroke">{html.escape(words)}</text>')


def outline(quad, quad_m, size):
    """The band's edge, its two sides labelled in metres (computed, not drawn by the model), and the caption."""
    corners = " ".join(f"{x:.1f},{y:.1f}" for x, y in quad)
    sides = "".join(text((quad[i][0] + quad[i + 1][0]) / 2, (quad[i][1] + quad[i + 1][1]) / 2,
                         f"{math.dist(quad_m[i], quad_m[i + 1]):.1f} m", size) for i in (0, 1))
    bar = 1.6 * TEXT_SHARE * size[0]
    return (f'<polygon points="{corners}" fill="none" stroke="#ff00ff" stroke-width="{MARK_SHARE * size[0] / 3:.1f}" '
            f'stroke-dasharray="{MARK_SHARE * size[0]:.1f}"/>{sides}<rect width="{size[0]}" height="{bar:.1f}" '
            f'fill="#000" fill-opacity="0.65"/>' + text(bar / 3, bar * 0.7, CAPTION, size, "start"))


def picture_svg(raster, size, marks, out_path):
    """A standalone SVG: the JPG embedded (a page's <img> loads no other file from an SVG) with `marks` over it."""
    data = base64.b64encode(raster.read_bytes()).decode()
    out_path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size[0]} {size[1]}" width="{size[0]}" '
                        f'height="{size[1]}"><image href="data:image/jpeg;base64,{data}" width="{size[0]}" '
                        f'height="{size[1]}"/>{marks}</svg>')
    return out_path


def draw_in_band(photo, fix, quad_m, quad, events, H, boxes, draw_fix, out_dir):
    """Muse Image draws `fix` over a magenta band, retried once with stronger words if the picture strays outside
    it; returns (street with dots, Muse Image's untouched picture, the band picture) file names, and the SSIM."""
    size = image_size(photo)
    guide = paint_guide(photo, quad, out_dir / GUIDE)
    words = instruction(fix, place(quad, size))
    picture = draw_fix(guide, words, out_dir / PICTURE)
    score = ssim_outside(photo, picture, quad, size)
    if score < SSIM_MIN:
        again = draw_fix(guide, words + STRONGER, out_dir / RETRY)
        retry_score = ssim_outside(photo, again, quad, size)
        if retry_score > score:
            picture, score = again.replace(picture), retry_score
    kept = keep_band(photo, picture, quad, boxes, size, out_dir / KEPT)
    marks = dots(events, H, size)
    today = picture_svg(photo, size, marks, out_dir / TODAY)
    shown = picture_svg(kept, size, outline(quad, quad_m, size) + paths(events, H, size) + marks, out_dir / BAND)
    return (today.name, picture.name, shown.name), score


def draw(photo, plan, events, site, people, draw_fix, out_dir):
    """The page's street pictures. draw_fix(image, instruction, out_path) returns Muse Image's picture. With a
    measured band: (street with dots, Muse Image's picture, band picture); else Muse Image edits the whole photo:
    (photo, picture). `people` are the photo's person tracks; their frame-0 boxes stay real."""
    H = road.homography(site["image_points"], site["world_points"])
    quad_m = band(events)
    quad = pixels(H, quad_m) if quad_m else None
    if not quad:
        return photo.name, draw_fix(photo, plan["image_prompt"], out_dir / PICTURE).name
    boxes = [t[0] for t in people if 0 in t]
    images, score = draw_in_band(photo, plan["fix"], quad_m, quad, events, H, boxes, draw_fix, out_dir)
    print(f"fix drawn inside the band; outside it Muse Image's picture matches the photo at SSIM {score:.2f}"
          + ("" if score >= SSIM_MIN else f", under {SSIM_MIN}: check the band picture by eye"), file=sys.stderr)
    return images


def figure(images):
    """The band picture, under the before/after pair, when there is one."""
    if not images or len(images) < 3:
        return ""
    return (f'<section><h2>Where the fix goes</h2><figure><img src="{html.escape(images[2])}" alt="The proposed fix '
            f'drawn only inside the measured band on the real street"><figcaption>{html.escape(CAPTION)} Muse Image '
            "drew only inside the magenta outline; the people in it and every pixel outside it are the real, blurred "
            "street. Red: serious near-misses; orange rings: close passes; blue: where each pedestrian walked; sizes "
            "in metres from the road geometry.</figcaption></figure></section>")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", help="an analyze.py output folder with clip.mp4 and street.jpg")
    parser.add_argument("site")
    parser.add_argument("dest", help="folder for the guide, Muse Image's picture and the band pictures")
    parser.add_argument("--band", required=True, help='four road points in metres going round, "x,y x,y x,y x,y"')
    parser.add_argument("--fix", default=FIX)
    args = parser.parse_args()
    import pack  # pack imports this module, so only the command line imports pack
    out_dir, dest, site = Path(args.out_dir), Path(args.dest), json.loads(Path(args.site).read_text())
    try:
        quad_m = [[float(v) for v in p.split(",")] for p in args.band.split()]
    except ValueError:
        quad_m = []
    H = road.homography(site["image_points"], site["world_points"])
    quad = pixels(H, quad_m) if len(quad_m) == 4 and all(len(p) == 2 for p in quad_m) else None
    if not quad:
        raise SystemExit("--band needs four road points x,y in metres, going round, all in front of the camera")
    events_file = out_dir / "events.json"
    events = pack.confirmed(json.loads(events_file.read_text())["events"]) if events_file.exists() else []
    people = pack.photo_people(out_dir / "clip.mp4", site.get("person", "person"), site.get("person_mode") == "crowd")
    key = sam.load_api_key()
    dest.mkdir(parents=True, exist_ok=True)
    images, score = draw_in_band(out_dir / "street.jpg", args.fix, quad_m, quad, events, H, [t[0] for t in people if 0 in t],
                                 lambda image, words, path: pack.draw_fix(image, words, key, path), dest)
    print(f"SSIM outside the band {score:.2f} (redrawn once below {SSIM_MIN}); wrote {', '.join(images)} in {dest}")


if __name__ == "__main__":
    main()
