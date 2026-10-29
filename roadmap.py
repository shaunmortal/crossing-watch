"""Bird's-eye map of the near-misses, in road metres: the measured calibration area, each event's pedestrian and
vehicle paths around the moment, and where they met. It shows what SAM's boxes became after the homography, and
tells a road engineer *where* on the crossing the danger is."""
import html
import math

WIDTH_PX = 640
MARGIN_M = 2.0
PATH_S = 2.0        # path drawn this long either side of the moment
GRID_M = 5.0


def path_around(track, frame, fps, step=2):
    """[[x, y], ...] of a track's points within PATH_S of `frame`, every `step` frames, rounded to 0.1 m."""
    reach = round(PATH_S * fps)
    return [[round(p[0], 1), round(p[1], 1)] for f, p in sorted(track.items()) if abs(f - frame) <= reach and f % step == 0]


def bounds(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs) - MARGIN_M, min(ys) - MARGIN_M, max(xs) + MARGIN_M, max(ys) + MARGIN_M


def svg(events, area, shown=5):
    """The map as inline SVG (empty without events that carry a "where"). `area` is the calibration quad in metres;
    the first `shown` events are numbered like the cards on the page."""
    placed = [e for e in events if e.get("where")]
    if not placed:
        return ""
    points = [p for e in placed for p in [e["where"], *e.get("path_person", []), *e.get("path_vehicle", [])]] + list(area)
    x0, y0, x1, y1 = bounds(points)
    scale = WIDTH_PX / (x1 - x0)
    height = max(1, round((y1 - y0) * scale))
    sx, sy = (lambda x: f"{(x - x0) * scale:.1f}"), (lambda y: f"{(y - y0) * scale:.1f}")
    at = lambda p: f"{sx(p[0])},{sy(p[1])}"
    grid = "".join(f'<line x1="{sx(g)}" y1="0" x2="{sx(g)}" y2="{height}"/>'
                   for g in (GRID_M * k for k in range(math.ceil(x0 / GRID_M), math.floor(x1 / GRID_M) + 1)))
    grid += "".join(f'<line x1="0" y1="{sy(g)}" x2="{WIDTH_PX}" y2="{sy(g)}"/>'
                    for g in (GRID_M * k for k in range(math.ceil(y0 / GRID_M), math.floor(y1 / GRID_M) + 1)))
    marks = []
    for e in placed:
        for key, cls in (("path_vehicle", "veh"), ("path_person", "ped")):
            if len(e.get(key, [])) > 1:
                marks.append(f'<polyline class="{cls}" points="{" ".join(at(p) for p in e[key])}"/>')
    for i, e in enumerate(events):  # dots on top of every path, numbered like the cards even when one has no "where"
        if not e.get("where"):
            continue
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
            f'road metres"><g class="grid">{grid}</g><polygon class="area" points="{" ".join(at(p) for p in area)}"/>'
            f'{"".join(marks)}{scale_bar}</svg>')


STYLE = """
.map { width: 100%; height: auto; border: 1px solid var(--line); border-radius: 6px; }
.map .grid line { stroke: var(--line); stroke-width: 1; }
.map .area { fill: none; stroke: var(--muted); stroke-dasharray: 6 4; }
.map .ped { fill: none; stroke: #2f7de1; stroke-width: 2.5; }
.map .veh { fill: none; stroke: var(--accent); stroke-width: 2.5; opacity: 0.6; }
.map .hit { fill: var(--accent); } .map .near { fill: none; stroke: #d98a00; stroke-width: 2.5; }
.map text { fill: var(--ink); font: 12px system-ui, sans-serif; } .map .bar { stroke: var(--ink); stroke-width: 2; }
"""
