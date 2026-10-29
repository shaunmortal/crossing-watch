"""Bird's-eye map of the near-misses, in road metres: the measured calibration area, everyone's desire line (where
they actually crossed), each event's pedestrian and vehicle paths around the moment, and where they met, over the
street photo seen from above. It shows what SAM's boxes became after the homography, and tells a road engineer
*where* on the crossing people walk and the danger is.
Also the gap barcode: the whole recording as one bar of the moments a vehicle was on the crossing and the gaps."""
import base64
import bisect
import html
import math
import statistics
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
DOTS_PX, BAR_PX, AXIS_PX = 16, 24, 16  # the gap barcode's rows: near-miss dots, the bar, time labels
LABEL_STEPS_S = (5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600)  # time labels every so many seconds...
MAX_LABELS = 8      # ...the first step that needs no more labels than this
STRIP_M = 2.0       # desire lines are counted in stretches of road this long, and "outside" a marked crossing past it
# IRC:103-2012 verbatim (cl. 6.7.1 and 6.1.9.2 (iii), "Schools/Colleges"), for the letter's facts beside the counts
IRC_DESIRE = ('IRC:103-2012 cl. 6.7.1: "Pedestrian must be given the shortest possible direct route to cross the '
              'street". Cl. 6.1.9.2 (iii), schools and colleges: "Provision of guard-rails near schools where children '
              'would other-wise run straight into the road is essential. If there is a pedestrian crossing or a school '
              'crossing nearby, the guard-rails must be extended up to it."')


def path_around(track, frame, fps, step=2):
    """[[x, y], ...] of a track's points within PATH_S of `frame`, every `step` frames, rounded to 0.1 m."""
    reach = round(PATH_S * fps)
    return [[round(p[0], 1), round(p[1], 1)] for f, p in sorted(track.items()) if abs(f - frame) <= reach and f % step == 0]


def bounds(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs) - MARGIN_M, min(ys) - MARGIN_M, max(xs) + MARGIN_M, max(ys) + MARGIN_M


def trails(paths):
    """Every piece of every desire line (road.crossing_paths()), as [[x, y], ...] lists."""
    return [piece for pieces in (paths or {}).values() for piece in pieces]


def extent(events, area, paths=None):
    """(x0, y0, x1, y1) in road metres that the map shows: the measured area, the desire lines and every event that
    carries a "where"."""
    placed = [e for e in events if e.get("where")]
    return bounds([p for e in placed for p in [e["where"], *e.get("path_person", []), *e.get("path_vehicle", []),
                                               *e.get("footprint", [])]]
                  + [p for piece in trails(paths) for p in piece] + list(area))


def svg(events, area, shown=5, ground=None, paths=None):
    """The map as inline SVG, never empty: `area` is the calibration quad in metres, `paths` the desire lines drawn as
    faint trails, and the events that carry a "where" go on top, the first `shown` numbered like the cards on the
    page. `ground` is ground()'s (picture, rectangle)."""
    placed = [e for e in events if e.get("where")]
    x0, y0, x1, y1 = extent(events, area, paths)
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
    marks = [f'<polyline class="trail" points="{" ".join(at(p) for p in piece)}"/>' for piece in trails(paths)]
    for e in placed:
        for key, cls in (("path_vehicle", "veh"), ("path_person", "ped")):
            if len(e.get(key, [])) > 1:  # pathLength 1 lets the page draw each path in, whatever its length
                marks.append(f'<polyline class="{cls}" pathLength="1" points="{" ".join(at(p) for p in e[key])}"/>')
        if e.get("footprint"):  # the vehicle's footprint (or lower box edge) at its moment
            marks.append(f'<polygon class="foot" points="{" ".join(at(p) for p in e["footprint"])}"/>')
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
    return (f'<svg class="map" viewBox="0 0 {WIDTH_PX} {height}" role="img" aria-label="Map of where people crossed '
            f'and the near-misses, in road metres">{under}<g class="grid">{grid}</g>'
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


def ground(photo, site, events, out_dir, paths=None):
    """The blurred street photo seen from above, under the map: warped once through the inverse homography onto the
    largest part of the map whose corners are all in the photo. Returns (data URI, [x0, y0, x1, y1] in metres): the
    page carries the picture, so a copy of the page needs no extra file. None for a top-down camera (already seen
    from above) or when ffmpeg fails."""
    if site.get("view") == "top-down":
        return None
    box = extent(events, site["world_points"], paths)
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


def desire_lines(paths, site):
    """Where people crossed, as sentences for the page and the letter's facts ([] when nobody did): how many crossed
    and how many of them within the busiest STRIP_M of road, measured along the road (across the way they walked).
    With the site's marked crossing ("zebra_m", its corners in metres) also how many crossed more than STRIP_M
    outside it; with "zebra_m": [] (none marked) and the gate's two posts ("gate_m"), how many crossed in line with
    the gate. Then IRC:103-2012's words on both."""
    walk = fixband.heading(trails(paths))
    if walk is None:
        return []
    along = lambda p: walk[0] * p[1] - walk[1] * p[0]
    at = sorted(statistics.median(along(p) for piece in pieces for p in piece) for pieces in paths.values())
    n, busiest = len(at), max(bisect.bisect_right(at, a + STRIP_M) - i for i, a in enumerate(at))
    lines = [f"Where people crossed: {n} {'person' if n == 1 else 'people'} walked {road.MIN_CROSSING_M:g} m or more, "
             f"mostly across the road; {busiest} of them within the busiest {STRIP_M:g} m stretch of road."]
    outside = lambda corners, a: not (min(map(along, corners)) - STRIP_M <= a <= max(map(along, corners)) + STRIP_M)
    zebra, gate = site.get("zebra_m"), site.get("gate_m")
    if zebra:
        k = sum(outside(zebra, a) for a in at)
        lines.append(f"{k} of {n} ({round(100 * k / n)}%) crossed more than {STRIP_M:g} m outside the marked crossing.")
    elif zebra == [] and gate:
        k = sum(not outside(gate, a) for a in at)
        lines.append(f"No marked crossing; {k} of {n} crossed straight out of the gate (within {STRIP_M:g} m of it "
                     "along the road).")
    return lines + [IRC_DESIRE]


def clock(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def time_labels(total):
    """Seconds to label under the barcode: every LABEL_STEPS_S step that gives at most MAX_LABELS labels."""
    step = next((s for s in LABEL_STEPS_S if total / s <= MAX_LABELS), LABEL_STEPS_S[-1])
    return [step * k for k in range(int(total // step) + 1)]


def strip_caption(total, gaps, n_events, shown, full):
    """What the barcode shows, and the longest anyone needing a road.GAP_ADULT_S gap would have waited."""
    longest = road.longest_without(gaps, total)
    whole = ", the whole recording, so a real wait may be longer" if longest >= round(total, 1) else ""
    missed = (" SAM reached its object limit, so some people or vehicles were not tracked: real gaps may be shorter."
              if full and full[0] else "")
    dots = (f" Dots: near-misses (filled: serious; rings: close passes); the first {min(shown, n_events)} link to "
            "their cards below." if n_events else "")
    return (f"The whole {clock(total)} of video, left to right. Red: a moving vehicle where people crossed. Green: a "
            f"gap of {road.GAP_SLOW_S:g} s or more; amber: {road.GAP_ADULT_S:g}-{road.GAP_SLOW_S:g} s (see the UK "
            f"Traffic Signs Manual line above). Hatched: cut short by the start or end of the video.{dots} Longest "
            f"stretch with no gap of {road.GAP_ADULT_S:g} s: {longest:g} s{whole}.{missed}")


def gap_strip(timeline, events, shown=5, full=None):
    """The whole recording as one bar: red while a moving vehicle was on the crossing, gaps of road.GAP_SLOW_S or
    more green, of road.GAP_ADULT_S or more amber, the first and last gaps hatched (the video cut them short), and a
    dot per near-miss, the first `shown` linked to their cards. '' without a timeline (older events.json files)."""
    if not timeline or not timeline.get("duration_s"):
        return ""
    total, spans = timeline["duration_s"], timeline["busy_s"]
    gaps = road.gaps_between(spans, total)
    at = lambda t: f"{min(max(t, 0), total) * WIDTH_PX / total:.1f}"
    length = lambda a, b: round(b - a, 2)
    bar = lambda a, b, cls: (f'<rect class="{cls}" x="{at(a)}" y="{DOTS_PX}" height="{BAR_PX}" '
                             f'width="{max(1.0, length(a, b) * WIDTH_PX / total):.1f}"/>')  # a tenth of a second shows
    marks = [bar(a, b, "gap12" if length(a, b) >= road.GAP_SLOW_S else "gap6")
             for a, b in gaps if length(a, b) >= road.GAP_ADULT_S]
    marks += [bar(a, b, "busy") for a, b in spans] + [bar(a, b, "cut") for a, b in gaps if a == 0 or b == total]
    for i, e in reversed(list(enumerate(events))):  # the linked first few drawn last, on top
        tier = e.get("tier", "serious")
        label = html.escape(f'#{i + 1}, {tier} at {e["t_person_s"]:.1f} s: {e["vehicle"].split("#")[0]}, '
                            f'{e["pet_s"]:.1f} s apart')
        dot = (f'<circle class="{"hit" if tier == "serious" else "near"}" cx="{at(e["t_person_s"])}" '
               f'cy="{DOTS_PX / 2:g}" r="4"><title>{label}</title></circle>')
        marks.append(f'<a href="#event-{i + 1}">{dot}</a>' if i < shown else dot)
    y = DOTS_PX + BAR_PX + AXIS_PX - 3
    anchor = lambda t: "start" if t == 0 else "end" if t > 0.95 * total else "middle"  # no label past an edge
    marks += [f'<text x="{at(t)}" y="{y}" text-anchor="{anchor(t)}">{clock(t)}</text>' for t in time_labels(total)]
    caption = strip_caption(total, gaps, len(events), shown, full)
    return (f'<section><h2>Gaps in traffic</h2><svg class="gaps" viewBox="0 0 {WIDTH_PX} {y + 3}" role="img" '
            f'aria-label="Gaps in traffic across the whole video"><defs><pattern id="gap-cut" width="6" height="6" '
            f'patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6"/>'
            f'</pattern></defs><rect class="base" y="{DOTS_PX}" width="{WIDTH_PX}" height="{BAR_PX}"/>'
            f'{"".join(marks)}</svg><p class="note">{html.escape(caption)}</p></section>')


STYLE = """
.map { width: 100%; height: auto; border: 1px solid var(--line); border-radius: 6px; }
.map .ground { opacity: 0.85; }
.map .grid line { stroke: var(--line); stroke-width: 1; }
.map .area { fill: none; stroke: var(--muted); stroke-dasharray: 6 4; }
.map .trail { fill: none; stroke: #2f7de1; stroke-width: 2; stroke-linecap: round; opacity: 0.45; }
.map .ped { fill: none; stroke: #2f7de1; stroke-width: 2.5; }
.map .veh { fill: none; stroke: var(--accent); stroke-width: 2.5; opacity: 0.6; }
.map .foot { fill: var(--accent); fill-opacity: 0.2; stroke: var(--accent); stroke-width: 1.5; }
.map .ped, .map .veh { stroke-dasharray: 1; animation: map-draw 4s linear infinite; }
@keyframes map-draw { from { stroke-dashoffset: 1; } 60%, to { stroke-dashoffset: 0; } }
@media (prefers-reduced-motion: reduce) { .map .ped, .map .veh { animation: none; } }
.map .hit { fill: var(--accent); } .map .near { fill: none; stroke: #d98a00; stroke-width: 2.5; }
.map text { fill: var(--ink); font: 12px system-ui, sans-serif; }
.map text { paint-order: stroke; stroke: var(--bg); stroke-width: 3px; }
.map .bar { stroke: var(--ink); stroke-width: 2; }
.gaps { width: 100%; height: auto; } .gaps .base { fill: var(--line); } .gaps .busy { fill: var(--accent); }
.gaps .gap12 { fill: #2e9e5b; } .gaps .gap6 { fill: #d98a00; } .gaps .cut { fill: url(#gap-cut); }
.gaps pattern line { stroke: var(--bg); stroke-width: 2; opacity: 0.7; }
.gaps .hit { fill: var(--accent); } .gaps .near { fill: none; stroke: #d98a00; stroke-width: 2; }
.gaps text { fill: var(--muted); font: 11px system-ui, sans-serif; }
"""
