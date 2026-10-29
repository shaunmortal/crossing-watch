"""Bird's-eye map of the near-misses, in road metres: the measured calibration area, each event's pedestrian and
vehicle paths around the moment, and where they met, over the street photo seen from above. It shows what SAM's
boxes became after the homography, and tells a road engineer *where* on the crossing the danger is."""
import base64
import html
import math
import subprocess
import sys

import fixband
import road

WIDTH_PX = 640
MARGIN_M = 2.0
PATH_S = 2.0        # path drawn this long either side of the moment
GRID_M = 5.0
GROUND = "map-ground.jpg"  # the street photo seen from above, written next to the page and embedded in it
GROUND_ZOOM = 2     # ground pixels per map pixel, sharp on high-density screens
BISECT_STEPS = 20   # halvings when fitting the ground into the photo: a millionth of the map


def path_around(track, frame, fps, step=2):
    """[[x, y], ...] of a track's points within PATH_S of `frame`, every `step` frames, rounded to 0.1 m."""
    reach = round(PATH_S * fps)
    return [[round(p[0], 1), round(p[1], 1)] for f, p in sorted(track.items()) if abs(f - frame) <= reach and f % step == 0]


def bounds(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs) - MARGIN_M, min(ys) - MARGIN_M, max(xs) + MARGIN_M, max(ys) + MARGIN_M


def extent(events, area):
    """(x0, y0, x1, y1) in road metres that the map shows, or None without events that carry a "where"."""
    placed = [e for e in events if e.get("where")]
    if not placed:
        return None
    return bounds([p for e in placed for p in [e["where"], *e.get("path_person", []), *e.get("path_vehicle", [])]]
                  + list(area))


def svg(events, area, shown=5, ground=None):
    """The map as inline SVG (empty without events that carry a "where"). `area` is the calibration quad in metres;
    the first `shown` events are numbered like the cards on the page. `ground` is ground()'s (picture, rectangle)."""
    box = extent(events, area)
    if not box:
        return ""
    placed = [e for e in events if e.get("where")]
    x0, y0, x1, y1 = box
    scale = WIDTH_PX / (x1 - x0)
    height = max(1, round((y1 - y0) * scale))
    sx, sy = (lambda x: f"{(x - x0) * scale:.1f}"), (lambda y: f"{(y - y0) * scale:.1f}")
    at = lambda p: f"{sx(p[0])},{sy(p[1])}"
    under = ""
    if ground:
        picture, (gx0, gy0, gx1, gy1) = ground
        under = (f'<image class="ground" href="{html.escape(picture)}" x="{sx(gx0)}" y="{sy(gy0)}" '
                 f'width="{(gx1 - gx0) * scale:.1f}" height="{(gy1 - gy0) * scale:.1f}" preserveAspectRatio="none"/>')
    grid = "".join(f'<line x1="{sx(g)}" y1="0" x2="{sx(g)}" y2="{height}"/>'
                   for g in (GRID_M * k for k in range(math.ceil(x0 / GRID_M), math.floor(x1 / GRID_M) + 1)))
    grid += "".join(f'<line x1="0" y1="{sy(g)}" x2="{WIDTH_PX}" y2="{sy(g)}"/>'
                    for g in (GRID_M * k for k in range(math.ceil(y0 / GRID_M), math.floor(y1 / GRID_M) + 1)))
    marks = []
    for e in placed:
        for key, cls in (("path_vehicle", "veh"), ("path_person", "ped")):
            if len(e.get(key, [])) > 1:  # pathLength 1 lets the page draw each path in, whatever its length
                marks.append(f'<polyline class="{cls}" pathLength="1" points="{" ".join(at(p) for p in e[key])}"/>')
    for i, e in enumerate(placed):  # dots on top of every path
        serious = e.get("tier", "serious") == "serious"
        label = html.escape(f'{e.get("tier", "serious")}: {e["vehicle"].split("#")[0]} at {e["vehicle_kmh"]} km/h, '
                            f'{e["pet_s"]:.1f} s apart')
        x, y = sx(e["where"][0]), sy(e["where"][1])
        marks.append(f'<circle class="{"hit" if serious else "near"}" cx="{x}" cy="{y}" r="{6 if serious else 4}">'
                     f'<title>{label}</title></circle>')
        if i < shown:
            marks.append(f'<text x="{float(x) + 8:.1f}" y="{float(y) - 6:.1f}">#{i + 1}</text>')
    scale_bar = (f'<line class="bar" x1="10" y1="{height - 12}" x2="{10 + GRID_M * scale:.1f}" y2="{height - 12}"/>'
                 f'<text x="10" y="{height - 18}">{GRID_M:g} m</text>')
    return (f'<svg class="map" viewBox="0 0 {WIDTH_PX} {height}" role="img" aria-label="Map of the near-misses in '
            f'road metres">{under}<g class="grid">{grid}</g>'
            f'<polygon class="area" points="{" ".join(at(p) for p in area)}"/>{"".join(marks)}{scale_bar}</svg>')


def corners(rect):
    """A rectangle's corners in ffmpeg perspective's order: top left, top right, bottom left, bottom right."""
    x0, y0, x1, y1 = rect
    return [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]


def in_photo(H, rect, size):
    """The photo pixels of a road rectangle's corners, or None when one is outside the photo or behind the camera."""
    pixels = [road.to_image(H, *c) for c in corners(rect)]
    return pixels if all(p and 0 <= p[0] <= size[0] and 0 <= p[1] <= size[1] for p in pixels) else None


def largest(fits, steps=BISECT_STEPS):
    """Largest t in [0, 1] with fits(t), by bisection, for a fits() that holds from 0 up to some t."""
    if fits(1.0):
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(steps):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid)
    return lo


def push(rect, side, toward, t):
    """`rect` with side `side` (0-3: x0, y0, x1, y1) moved a share `t` of the way to that side of `toward`."""
    return [v + t * (toward[k] - v) if k == side else v for k, v in enumerate(rect)]


def view_rect(H, box, centre, size):
    """The largest part of the map rectangle `box` whose four corners are in the photo: shrunk evenly toward
    `centre`, then each side pushed back out as far as it stays in (what is in view of a camera is convex, so both
    steps can bisect). None when not even the centre is in view."""
    scaled = lambda s: [c + s * (b - c) for b, c in zip(box, (*centre, *centre))]
    s = largest(lambda s: in_photo(H, scaled(s), size) is not None)
    if s == 0:
        return None
    rect = scaled(s)
    for side in range(4):
        rect = push(rect, side, box, largest(lambda t: in_photo(H, push(rect, side, box, t), size) is not None))
    return rect


def ground(photo, site, events, out_dir):
    """The blurred street photo seen from above, under the map: warped once through the inverse homography onto the
    largest part of the map whose corners are all in the photo. Returns (data URI, [x0, y0, x1, y1] in metres): the
    page carries the picture, so a copy of the page needs no extra file. None for a top-down camera (already seen
    from above), without placed events, or when ffmpeg fails."""
    box = extent(events, site["world_points"])
    if site.get("view") == "top-down" or not box:
        return None
    H = road.homography(site["image_points"], site["world_points"])
    xs, ys = zip(*site["world_points"])
    try:
        size = fixband.image_size(photo)
        rect = view_rect(H, box, (sum(xs) / len(xs), sum(ys) / len(ys)), size)
        if not rect:
            return None
        scale = GROUND_ZOOM * WIDTH_PX / (box[2] - box[0])
        out = (max(2, round((rect[2] - rect[0]) * scale)), max(2, round((rect[3] - rect[1]) * scale)))
        work = (max(out[0], size[0]), max(out[1], size[1]))  # enlarge first, so the warp never samples a shrunk photo
        warp = ":".join(f"x{i}={x * work[0] / size[0]:.2f}:y{i}={y * work[1] / size[1]:.2f}"
                        for i, (x, y) in enumerate(in_photo(H, rect, size)))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(photo), "-vf",
                        f"scale={work[0]}:{work[1]},perspective={warp}:interpolation=cubic:sense=source,"
                        f"scale={out[0]}:{out[1]}", "-frames:v", "1", "-q:v", "3", str(out_dir / GROUND)], check=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as err:
        print(f"no street photo under the map: {err}", file=sys.stderr)
        return None
    data = base64.b64encode((out_dir / GROUND).read_bytes()).decode()
    return f"data:image/jpeg;base64,{data}", [round(v, 2) for v in rect]


STYLE = """
.map { width: 100%; height: auto; border: 1px solid var(--line); border-radius: 6px; }
.map .ground { opacity: 0.85; }
.map .grid line { stroke: var(--line); stroke-width: 1; }
.map .area { fill: none; stroke: var(--muted); stroke-dasharray: 6 4; }
.map .ped { fill: none; stroke: #2f7de1; stroke-width: 2.5; }
.map .veh { fill: none; stroke: var(--accent); stroke-width: 2.5; opacity: 0.6; }
.map .ped, .map .veh { stroke-dasharray: 1; animation: map-draw 4s linear infinite; }
@keyframes map-draw { from { stroke-dashoffset: 1; } 60%, to { stroke-dashoffset: 0; } }
@media (prefers-reduced-motion: reduce) { .map .ped, .map .veh { animation: none; } }
.map .hit { fill: var(--accent); } .map .near { fill: none; stroke: #d98a00; stroke-width: 2.5; }
.map text { fill: var(--ink); font: 12px system-ui, sans-serif; }
.map text { paint-order: stroke; stroke: var(--bg); stroke-width: 3px; }
.map .bar { stroke: var(--ink); stroke-width: 2; }
"""
