"""Road-plane geometry for Crossing Watch: image pixels to metres on the road, and near-misses between
pedestrians and moving vehicles measured as post-encroachment time (PET).

Map frame: metres on the road surface, set by four calibration points the user marks on the video.
"""
import bisect
import math
import statistics

CONFLICT_RADIUS_M = 1.0   # a vehicle edge this close to where a pedestrian stood counts as the same spot
PET_MAX_S = 1.5           # traffic-conflict studies treat PET under ~1.5 s as a serious conflict
CLOSE_PASS_S = 3.0        # 1.5-3 s is reported as a "close pass": never let a short video read as "safe"
UNSEEN_S = 0.5            # SAM missed the person or vehicle this long around its moment: crowd mode inferred its position
BEFORE_S = 2.0            # kmh_2s_before: the vehicle's speed this long before it reached the spot
SLOWDOWN_KMH = 3.0        # person first, a vehicle less than this slower than then: "no slowdown measured" (SinD: none
                          # of 18 person-first vehicles slowed by 3 km/h or more; our speeds agree within 0.3 km/h)
MIN_CROSSING_M = 2.0      # a pedestrian piece that moves this far counts as one crossing (exposure)
MOVING_MPS = 10 / 3.6     # slower than this the vehicle is parked, queued or creeping, not a serious threat
SPEED_WINDOW_S = 1.0
STATIC_SPREAD_M = 0.75    # a "pedestrian" that stays this close to one spot is a pole, sign or someone waiting
STATIC_WINDOW_S = 3.0     # stillness is judged per window of this length
STILL_RUN_S = 15.0        # still this long in one spot: a pole, sign or someone waiting; those frames are dropped
MAX_GAP_FRAMES = 5        # across longer tracking gaps, judge a jump as if it happened within this many frames
MAX_PLAUSIBLE_MPS = 120 / 3.6  # faster than this at a crossing is a tracking or geometry glitch, not a car
ZONE_MARGIN_M = 10.0      # analyse only this far around the calibration points; far pixels blow up into huge metres
BORDER_PX = 1             # a box touching the frame edge is cut off, so its lower edge is not the vehicle's
MIN_SPEED_STEPS = 3       # a speed needs this many frame-to-frame steps in its window; one jump is noise
RIDER_OVERLAP = 0.6       # a "person" box this much inside a vehicle box is its rider or driver, not a pedestrian
RIDER_FEET_PX = 3         # ...if their feet are not below the vehicle's (a pedestrian in front has lower feet)
MIN_PIECE_S = 1.0         # a pedestrian or vehicle piece shorter than this has no trustworthy path, timing or speed
MAX_WALK_MPS = 10.0       # faster than a sprint: the track's ID has jumped to someone (or something) else
GRID_M = 2.0              # spatial index cell; any size >= 0 gives the same answers, this one is fast
GAP_ADULT_S = 6.0         # UK Traffic Signs Manual ch. 6, 13.5.2: an acceptable gap is 4-6 s at urban speeds...
GAP_SLOW_S = 12.0         # ..."other groups may require larger gaps, of 10 - 12 s or longer"
PV2_UNDIVIDED, PV2_DIVIDED = 1e8, 2e8  # IRC:103-2012 6.7.4.1.2: peak-hour PV^2 above this "may" warrant control
SPEED_LIMITS_KMH = (30, 20)  # replayed "what if this street had a limit" scenarios
# Both favour the driver, so replayed impact speeds are not understated: 1.5 s is a typical perception-reaction
# time for an unexpected hazard (road design uses 2.5 s), 7 m/s^2 is hard braking on dry asphalt.
REACTION_S = 1.5
BRAKING_MPS2 = 7.0
# Rosén & Sander 2009, Accid Anal Prev 41(3):536-542, Eq. 2: P(death) = 1 / (1 + exp(6.9 - 0.090 v)), v in km/h.
# Adults 15+ hit by a car front (German GIDAS data); the lower of the two curves we checked (Tefft 2013 is higher),
# so risks are not overstated. Children are not covered by the study.
DEATH_RISK_INTERCEPT = 6.9
DEATH_RISK_PER_KMH = 0.090
# Car-shaped footprints for a camera at an angle: (length, width) in metres per vehicle concept; a site's
# "vehicle_sizes_m" (tape-measured) overrides these. Other concepts keep the lower box edge.
VEHICLE_SIZES_M = {"car": (4.6, 1.8), "motorcycle": (1.7, 0.8), "auto rickshaw": (2.4, 1.1)}
HEADING_S = 0.5       # direction of travel from where the vehicle was this long before and after
MIN_HEADING_M = 0.3   # ...when it moved at least this far; otherwise the nearest frame's heading is carried
SMOOTH_FRAMES = 2     # footprint centre: median over this many frames either side
FIT_STEPS = 8         # Gauss-Newton steps placing a footprint under its SAM box
FIT_STEP_M = 0.01     # finite-difference step for the fit's slopes
FIT_DONE_M = 0.001    # the fit stops once a step moves the centre less than this


def solve(rows, rhs):
    """Solve a small square linear system by Gauss-Jordan elimination with partial pivoting."""
    n = len(rhs)
    m = [row[:] + [rhs[i]] for i, row in enumerate(rows)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            raise ValueError("calibration points must not lie on one line")
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [a - f * c for a, c in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def homography(image_points, world_points):
    """3x3 matrix taking image (x, y) to road (x, y) metres, from four point pairs."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(image_points, world_points):
        rows += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        rhs += [u, v]
    h = solve(rows, rhs) + [1.0]
    # Scale is free; pick the sign that puts the calibration points on the visible side of the horizon (w > 0).
    x, y = image_points[0]
    sign = 1.0 if h[6] * x + h[7] * y + h[8] > 0 else -1.0
    H = [[sign * v for v in h[i:i + 3]] for i in (0, 3, 6)]
    for (x, y), want in zip(image_points, world_points):
        got = to_ground(H, x, y)
        if got is None or math.dist(got, want) > 1e-3:
            raise ValueError("calibration points are out of order: list them going round the area in one direction")
    return H


def to_ground(H, x, y):
    """Road point under image pixel (x, y), or None when the pixel is at or above the horizon."""
    w = H[2][0] * x + H[2][1] * y + H[2][2]
    if w <= 0:
        return None
    return ((H[0][0] * x + H[0][1] * y + H[0][2]) / w, (H[1][0] * x + H[1][1] * y + H[1][2]) / w)


def to_image(H, u, v):
    """Image pixel over road point (u, v), the inverse of to_ground, or None when the point is behind the camera."""
    x, y, w = solve(H, [u, v, 1.0])  # to_ground divides by 1 / w at that pixel, so w <= 0 is never in view
    return None if w <= 0 else (x / w, y / w)


def inverse(H):
    """H inverted once: to_ground(inverse(H), u, v) is to_image(H, u, v) without a solve per point."""
    columns = [solve(H, [float(i == j) for i in range(3)]) for j in range(3)]
    return [[columns[j][i] for j in range(3)] for i in range(3)]


def zone_around(world_points, margin=ZONE_MARGIN_M):
    """(x_min, y_min, x_max, y_max) in road metres: the calibration area plus a margin."""
    xs, ys = [p[0] for p in world_points], [p[1] for p in world_points]
    return (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)


def in_zone(p, zone):
    return p is not None and (zone is None or (zone[0] <= p[0] <= zone[2] and zone[1] <= p[1] <= zone[3]))


def in_polygon(p, polygon):
    """Even-odd rule point-in-polygon test, polygon as [[x, y], ...] in road metres."""
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > p[1]) != (y2 > p[1]) and p[0] < x1 + (p[1] - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def inside_share(inner, outer):
    """Fraction of box `inner` covered by box `outer` (pixels)."""
    w = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    h = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    return w * h / ((inner[2] - inner[0]) * (inner[3] - inner[1]))


def without_riders(person_track, vehicle_tracks, share=RIDER_OVERLAP):
    """The person track minus frames where the box sits inside some vehicle's box with the feet no lower than the
    vehicle's: a rider or driver. Someone crossing in front of a bus overlaps it too, but stands lower in the frame."""
    return {f: b for f, b in person_track.items()
            if not any(f in v and inside_share(b, v[f]) >= share and b[3] <= v[f][3] + RIDER_FEET_PX
                       for v in vehicle_tracks)}


def person_points(track, H, zone=None, roadway=None, frame_size=None, top_down=False):
    """frame -> road point under a pedestrian's feet (bottom centre of the box; the box centre when the camera looks
    straight down), inside the zone and, when the site marks the carriageway, on it (people waiting on the pavement
    are not in a vehicle's path). Boxes cut off at the bottom of the frame are skipped: their feet are out of view."""
    feet = {f: to_ground(H, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2 if top_down else b[3]) for f, b in track.items()
            if not (frame_size and (b[3] >= frame_size[1] - 1 - BORDER_PX or (top_down and b[1] <= BORDER_PX)))}
    return {f: p for f, p in feet.items() if in_zone(p, zone) and (roadway is None or in_polygon(p, roadway))}


def split_at_jumps(feet, fps, max_mps=MAX_WALK_MPS):
    """A pedestrian track cut wherever it moves faster than anyone can, i.e. where SAM moved the ID to another
    object; each piece is then judged on its own."""
    pieces, current, last = [], {}, None
    for f in sorted(feet):
        if last is not None and math.dist(feet[last], feet[f]) * fps / min(f - last, MAX_GAP_FRAMES) > max_mps:
            pieces.append(current)
            current = {}
        current[f] = feet[f]
        last = f
    return [p for p in pieces + [current] if p]


def median_point(points):
    return (statistics.median(p[0] for p in points), statistics.median(p[1] for p in points))


def moving_frames(feet, fps, spread_m=STATIC_SPREAD_M, window_s=STATIC_WINDOW_S, still_run_s=STILL_RUN_S):
    """The track minus its long still stretches: runs of consecutive windows, `still_run_s` or longer in total,
    where 90% of the points stay within `spread_m` of the window's median spot. SAM sometimes tracks a pole as a
    person, and a pedestrian waiting at the kerb is in no vehicle's path; a person who then crosses keeps the
    crossing frames, and short pauses are kept."""
    # ponytail: also drops someone standing still in the road for 15 s or more; revisit if that case matters
    size = max(1, round(window_s * fps))
    windows = {}
    for f in sorted(feet):
        windows.setdefault(f // size, []).append(f)

    def still(frames):
        if len(frames) < size // 2:
            return False
        centre = median_point([feet[f] for f in frames])
        spread = sorted(math.dist(centre, feet[f]) for f in frames)
        return spread[int(0.9 * (len(spread) - 1))] < spread_m

    dropped, run = set(), []
    for w in sorted(windows) + [None]:  # None closes the last run
        if w is not None and still(windows[w]) and (not run or w == run[-1] + 1):
            run.append(w)
            continue
        if len(run) * window_s >= still_run_s:
            dropped.update(f for r in run for f in windows[r])
        run = [w] if w is not None and still(windows[w]) else []
    return {f: p for f, p in feet.items() if f not in dropped}


def vehicle_edges(track, H, zone=None, frame_size=None, top_down=False):
    """frame -> road shape of the vehicle inside the zone: the segment under its lower box edge, or, when the camera
    looks straight down, the whole box (it is the footprint). Boxes cut off by the frame edge are skipped, since
    their edge is the frame's, not the vehicle's."""
    # ponytail: at an angle the lower box edge only stands in for the footprint; vehicle_footprints replaces it for
    # concepts with a size
    edges = {}
    for f, b in track.items():
        if frame_size and (b[0] <= BORDER_PX or b[2] >= frame_size[0] - 1 - BORDER_PX
                           or b[3] >= frame_size[1] - 1 - BORDER_PX or (top_down and b[1] <= BORDER_PX)):
            continue
        corners = ((b[0], b[3]), (b[2], b[3])) + (((b[2], b[1]), (b[0], b[1])) if top_down else ())
        shape = tuple(to_ground(H, x, y) for x, y in corners)
        if all(in_zone(q, zone) for q in shape):
            edges[f] = shape
    return edges


def rectangle(centre, heading, size):
    """Corners, in order round it, of a (length, width) rectangle on the road turned to `heading` (radians)."""
    c, s = math.cos(heading), math.sin(heading)
    half_l, half_w = size[0] / 2, size[1] / 2
    return tuple((centre[0] + dx * c - dy * s, centre[1] + dx * s + dy * c)
                 for dx, dy in ((half_l, half_w), (half_l, -half_w), (-half_l, -half_w), (-half_l, half_w)))


def headings(mids, fps, half_s=HEADING_S, min_m=MIN_HEADING_M):
    """frame -> direction of travel (radians) from where the vehicle was `half_s` before and after; a frame where it
    moved less than `min_m` in that time takes the nearest such frame's heading. Empty if it never moved that far."""
    frames, half = sorted(mids), max(1, round(half_s * fps))
    known = {}
    for f in frames:
        lo = mids[frames[bisect.bisect_left(frames, f - half)]]
        hi = mids[frames[bisect.bisect_right(frames, f + half) - 1]]
        if math.dist(lo, hi) >= min_m:
            known[f] = math.atan2(hi[1] - lo[1], hi[0] - lo[0])
    order = sorted(known)

    def nearest(f):
        i = bisect.bisect_left(order, f)
        return min(order[max(0, i - 1):i + 1], key=lambda k: abs(k - f))
    return {f: known[nearest(f)] for f in frames} if known else {}


def fit_centre(H_inv, box, heading, size, start):
    """Road point where a `size` rectangle turned to `heading` stands so that its image fits the SAM box: lowest
    corner on the box's bottom edge, corners centred on the box's centre. Gauss-Newton on the two unknowns from
    `start`; None if the rectangle leaves the camera's view. `H_inv` is inverse(H)."""
    def residual(c):
        pixels = [to_ground(H_inv, *q) for q in rectangle(c, heading, size)]
        if None in pixels:
            return None
        return (max(p[1] for p in pixels) - box[3], sum(p[0] for p in pixels) / 4 - (box[0] + box[2]) / 2)

    c = start
    for _ in range(FIT_STEPS):
        r, rx, ry = residual(c), residual((c[0] + FIT_STEP_M, c[1])), residual((c[0], c[1] + FIT_STEP_M))
        if None in (r, rx, ry):
            return None
        a, b = (rx[0] - r[0]) / FIT_STEP_M, (ry[0] - r[0]) / FIT_STEP_M  # bottom pixel per metre in x, y
        d, e = (rx[1] - r[1]) / FIT_STEP_M, (ry[1] - r[1]) / FIT_STEP_M  # centre pixel per metre in x, y
        det = a * e - b * d
        if abs(det) < 1e-9:
            return None
        dx, dy = (e * r[0] - b * r[1]) / det, (a * r[1] - d * r[0]) / det
        c = (c[0] - dx, c[1] - dy)
        if math.hypot(dx, dy) < FIT_DONE_M:
            break
    return c


def vehicle_footprints(track, H, size, fps, zone=None, frame_size=None):
    """frame -> road footprint of a vehicle seen at an angle: a `size` (length, width) rectangle turned to its
    heading and placed where its image fits the SAM box (fit_centre), the centre median-smoothed over
    +-SMOOTH_FRAMES frames. The lower box edge (vehicle_edges) lies along the near side of the vehicle's bulk, not
    under it: in a SinD simulation of a phone at an angle it nearly doubled the serious conflicts. A track that never
    moves far enough for a heading keeps its lower edges, so no track mixes the two shapes."""
    edges = vehicle_edges(track, H, zone, frame_size)
    turn = headings({f: centroid(e) for f, e in edges.items()}, fps)
    if not turn:
        return edges
    H_inv = inverse(H)
    centres = {f: c for f in edges if (c := fit_centre(H_inv, track[f], turn[f], size, centroid(edges[f])))}
    # ponytail: the window is one-sided at a track's ends, pulling them in by up to a frame of travel; narrowing it
    # there measured no closer to SinD's truth (validate_sind --oblique). The zone was checked on the lower edge: a
    # footprint behind it crossing the zone's far side must not cut the track short.
    near = lambda f: [centres[g] for g in range(f - SMOOTH_FRAMES, f + SMOOTH_FRAMES + 1) if g in centres]
    return {f: rectangle(median_point(near(f)), turn[f], size) for f in centres}


def segment_distance(p, a, b):
    ax, ay = b[0] - a[0], b[1] - a[1]
    length2 = ax * ax + ay * ay
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / length2))
    return math.dist(p, (a[0] + t * ax, a[1] + t * ay))


def footprint_distance(p, shape):
    """Distance from p to a vehicle shape: a segment (its lower box edge) or a polygon (a full footprint, 0 inside)."""
    if len(shape) > 2 and in_polygon(p, list(shape)):
        return 0.0
    sides = [shape] if len(shape) == 2 else list(zip(shape, shape[1:] + shape[:1]))
    return min(segment_distance(p, a, b) for a, b in sides)


def centroid(shape):
    return (sum(q[0] for q in shape) / len(shape), sum(q[1] for q in shape) / len(shape))


def speeds(edges, fps, window_s=SPEED_WINDOW_S):
    """frame -> vehicle speed in m/s: the least-squares slope of the edge midpoint against time over about
    `window_s`. Unlike a median of frame-to-frame steps it reads true when the steps are uneven: a 24 fps video
    resampled to 10 fps steps 2,2,3,2,3 source frames, and the median read 0.83 x the true speed. The track is cut
    where a step is faster than MAX_PLAUSIBLE_MPS (SAM swapping the ID onto another vehicle), and a piece shorter
    than MIN_PIECE_S gets no speed: a fragment that short is a tracking glitch, not a measured vehicle."""
    mid = {f: centroid(shape) for f, shape in edges.items()}
    half = max(1, round(window_s * fps / 2))
    out = {}
    for piece in split_at_jumps(mid, fps, MAX_PLAUSIBLE_MPS):
        frames = sorted(piece)
        if len(frames) < MIN_PIECE_S * fps:
            continue
        for f in frames:
            near = frames[bisect.bisect_left(frames, f - half):bisect.bisect_right(frames, f + half)]
            if len(near) > MIN_SPEED_STEPS:
                t = [g / fps for g in near]
                vx = statistics.linear_regression(t, [piece[g][0] for g in near]).slope
                vy = statistics.linear_regression(t, [piece[g][1] for g in near]).slope
                out[f] = math.hypot(vx, vy)
    return out


def impact_mps(speed_mps, distance_m, reaction_s=REACTION_S, braking=BRAKING_MPS2):
    """Speed when reaching an obstacle `distance_m` ahead, after reacting and then braking hard."""
    braking_m = max(0.0, distance_m - speed_mps * reaction_s)
    return math.sqrt(max(0.0, speed_mps ** 2 - 2 * braking * braking_m))


def death_risk(impact_kmh):
    """Probability an adult pedestrian dies when hit by a car front at this speed (Rosén & Sander 2009)."""
    if impact_kmh <= 0:
        return 0.0
    return 1 / (1 + math.exp(DEATH_RISK_INTERCEPT - DEATH_RISK_PER_KMH * impact_kmh))


def with_limits(speed_mps, pet_s, limits_kmh=SPEED_LIMITS_KMH):
    """Replay of the event under each speed limit: the same vehicle, at the same place when the pedestrian was on
    the spot (speed * PET metres away), but no faster than the limit. Had the pedestrian still been there, how hard
    would it have hit?"""
    distance_m = speed_mps * pet_s
    out = {}
    for limit in limits_kmh:
        hit_kmh = impact_mps(min(speed_mps, limit / 3.6), distance_m) * 3.6
        out[str(limit)] = {"impact_kmh": round(hit_kmh, 1), "death_risk_pct": round(100 * death_risk(hit_kmh), 1)}
    return out


def build_index(vehicles, fps, radius, bucket, min_speed=MOVING_MPS):
    """(index, speeds): (grid cell x, cell y, time bucket) -> [(frame, vehicle id)] for every moving vehicle frame,
    registered in every cell its shape (grown by `radius`) touches; so a pedestrian point only checks nearby
    vehicles at nearby times. Same answers as checking every pair, fast enough for hours of footage."""
    index, speed_of = {}, {}
    for vid, shapes in vehicles.items():
        speed_of[vid] = speeds(shapes, fps)
        for f, shape in shapes.items():
            if speed_of[vid].get(f, 0.0) < min_speed:
                continue
            xs, ys = [q[0] for q in shape], [q[1] for q in shape]
            for cx in range(math.floor((min(xs) - radius) / GRID_M), math.floor((max(xs) + radius) / GRID_M) + 1):
                for cy in range(math.floor((min(ys) - radius) / GRID_M), math.floor((max(ys) + radius) / GRID_M) + 1):
                    index.setdefault((cx, cy, f // bucket), []).append((f, vid))
    return index, speed_of


def best_passes(feet, vehicles, index, speed_of, fps, bucket, radius=CONFLICT_RADIUS_M, pet_max=PET_MAX_S):
    """vehicle id -> the most dangerous moment between this pedestrian and that moving vehicle.

    PET here: the time between the pedestrian standing on a spot and the moving vehicle passing within
    `radius` of it (either order), strictly under `pet_max`. 0 s means both were there at once.
    """
    reach = round(pet_max * fps)
    best = {}
    for fp, p in feet.items():
        cell = (math.floor(p[0] / GRID_M), math.floor(p[1] / GRID_M))
        for b in range(fp // bucket - 1, fp // bucket + 2):
            for fv, vid in index.get((*cell, b), ()):
                frames = abs(fv - fp)
                if frames >= reach:
                    continue
                gap = footprint_distance(p, vehicles[vid][fv])
                if gap > radius:
                    continue
                if vid not in best or (frames, gap) < best[vid][0]:
                    best[vid] = ((frames, gap), fp, fv, gap, speed_of[vid][fv])
    return {vid: event_fields(b, fps, speed_of[vid]) for vid, b in best.items()}


def event_fields(best, fps, speed_mps=None):
    """An event's numbers from its best pass; with the vehicle's speeds (frame -> m/s), also its speed BEFORE_S
    earlier (None where it was not measured)."""
    (frames, _), fp, fv, gap, mps = best
    # Same model as the limit replay: the vehicle was speed * PET metres away; under REACTION_S (every serious
    # event) there is no time to brake, so the hit would be at full speed.
    impact_kmh = impact_mps(mps, mps * frames / fps) * 3.6
    before = (speed_mps or {}).get(fv - round(BEFORE_S * fps))
    return {"pet_s": frames / fps, "t_person_s": fp / fps, "t_vehicle_s": fv / fps,
            "gap_m": round(gap, 2), "vehicle_kmh": round(mps * 3.6, 1), "impact_kmh": round(impact_kmh, 1),
            "death_risk_pct": round(100 * death_risk(impact_kmh), 1), "with_limit": with_limits(mps, frames / fps),
            "first": first_on_spot(fp, fv), "kmh_2s_before": None if before is None else round(before * 3.6, 1)}


def first_on_spot(t_person, t_vehicle):
    """Who reached the conflict spot first: "person", "vehicle", or "both" at the same moment (PET 0)."""
    return "both" if t_person == t_vehicle else "person" if t_person < t_vehicle else "vehicle"


def first_counts(events):
    """How many events the person, or the vehicle, reached the spot first. People first points at drivers not
    yielding; vehicles first at people stepping into gaps."""
    order = [first_on_spot(e["t_person_s"], e["t_vehicle_s"]) for e in events]
    return {"person_first": order.count("person"), "vehicle_first": order.count("vehicle"),
            "both_at_once": order.count("both")}


def unseen_s(detected, frame, fps):
    """Seconds SAM did not detect an object around `frame`: 0 when it did on that frame, else the gap between its
    detections either side, across which crowd mode inferred (crowd.filled) where it was. `detected` holds the
    frames it was detected on."""
    before = max((f for f in detected if f <= frame), default=frame)
    after = min((f for f in detected if f >= frame), default=frame)
    return (after - before) / fps


def first_note(e):
    """The card's line on who reached the spot first. Vehicle first, the impact and risk (event_fields: the vehicle
    speed * PET metres away) are for someone on the spot PET before it came. Person first, the vehicle's speed
    BEFORE_S earlier: what was measured, never what the driver did."""
    vehicle, pet, first = e["vehicle"].split("#")[0], e["pet_s"], first_on_spot(e["t_person_s"], e["t_vehicle_s"])
    if first == "both":
        return f"The person and the {vehicle} were on the spot at the same moment."
    if first == "vehicle":
        return (f"The {vehicle} passed the spot first and the person reached it {pet:.1f} s later: the impact and risk "
                f"are for someone on the spot {pet:.1f} s before the {vehicle} came.")
    before = e.get("kmh_2s_before")
    slowdown = "" if before is None or before - e["vehicle_kmh"] >= SLOWDOWN_KMH else ": no slowdown measured"
    earlier = "" if before is None else f" ({before} km/h two seconds earlier{slowdown})"
    return f"The person was on the spot first; the {vehicle} reached it {pet:.1f} s later at {e['vehicle_kmh']} km/h{earlier}."


def seen_note(e):
    """The card's line on whether SAM saw both at the moment, or for how long one's position was inferred; empty
    for an event from before this was measured."""
    unseen = e.get("unseen_s")
    if not unseen:
        return ""
    who = {"person": "the person", "vehicle": "the " + e["vehicle"].split("#")[0]}
    gaps = [f"{unseen[k]:.1f} s ({who[k]})" for k in ("person", "vehicle") if unseen[k] >= UNSEEN_S]
    if not gaps:
        return "Seen at the moment."
    return f"Not detected for about {' and '.join(gaps)}; position{'s' if len(gaps) > 1 else ''} inferred."


def moment_note(e):
    """first_note and seen_note, for the event card."""
    return " ".join(n for n in (first_note(e), seen_note(e)) if n)


def closest_pass(feet, edges, fps, radius=CONFLICT_RADIUS_M, pet_max=PET_MAX_S, min_speed=MOVING_MPS):
    """The most dangerous moment between one pedestrian and one moving vehicle, or None."""
    bucket = max(1, round(pet_max * fps))
    index, speed_of = build_index({"v": edges}, fps, radius, bucket, min_speed)
    return best_passes(feet, {"v": edges}, index, speed_of, fps, bucket, radius, pet_max).get("v")


def conflicts(people, vehicles, fps, pet_max=CLOSE_PASS_S, radius=CONFLICT_RADIUS_M, min_speed=MOVING_MPS):
    """All pedestrian-vehicle conflicts up to `pet_max`: serious ones (PET < PET_MAX_S) first, then close passes;
    within each tier the highest death risk, then the lowest PET."""
    bucket = max(1, round(pet_max * fps))
    index, speed_of = build_index(vehicles, fps, radius, bucket, min_speed)
    events = []
    for pid, feet in people.items():
        feet = moving_frames(feet, fps)
        for vid, hit in best_passes(feet, vehicles, index, speed_of, fps, bucket, radius, pet_max).items():
            tier = "serious" if hit["pet_s"] < PET_MAX_S else "close pass"
            events.append({"person": pid, "vehicle": vid, "tier": tier, **hit})
    order = sorted(events, key=lambda e: (e["tier"] != "serious", -e["death_risk_pct"], e["pet_s"], e["gap_m"]))
    seen = set()  # one event per real person and vehicle, even when the person's track was split into pieces
    return [e for e in order if (key := (e["person"].split("/")[0], e["vehicle"])) not in seen and not seen.add(key)]


def percentile(values, share):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))] if ordered else None


def crossing_cells(people, fps):
    """The GRID_M road cells where pedestrians actually crossed (moving pieces that went MIN_CROSSING_M or more)."""
    cells = set()
    for feet in people.values():
        moving = moving_frames(feet, fps)
        start = moving[min(moving)] if moving else None
        if moving and max(math.dist(start, p) for p in moving.values()) >= MIN_CROSSING_M:
            cells.update((math.floor(x / GRID_M), math.floor(y / GRID_M)) for x, y in moving.values())
    return cells


def traffic_gaps(vehicles, fps, cells, frames):
    """Lengths in seconds of the stretches with no moving vehicle on the crossing (any of `cells`): the gaps a
    pedestrian could cross in. The first and last are cut short by the video, so they are lower bounds."""
    def on_crossing(shape):
        return any((math.floor(x / GRID_M), math.floor(y / GRID_M)) in cells for x, y in (*shape, centroid(shape)))
    busy = {f for edges in vehicles.values() for f, v in speeds(edges, fps).items()
            if v >= MOVING_MPS and on_crossing(edges[f])}
    gaps, start = [], 0
    for f in sorted(busy) + [frames]:
        if f > start:
            gaps.append((f - start) / fps)
        start = f + 1
    return gaps


def pv2(crossings, vehicles, minutes):
    """PV^2: pedestrians crossing per hour times vehicles per hour squared, scaled from `minutes` of video."""
    per_hour = 60 / minutes
    return crossings * per_hour * (vehicles * per_hour) ** 2


def exposure(people, vehicles, fps, frames):
    """How much was watched, so a short or quiet video is never read as "safe": crossings (people, counted once
    per tracked id however many pieces it was split into), moving vehicles, minutes, and the 85th-percentile
    vehicle speed, each vehicle's speed taken while it was actually moving (the speed traffic engineers quote).
    When someone crossed, also the gaps in traffic where they crossed that are long enough to cross in, and who
    crossed (sorted ids), so a count of people in conflicts can stay inside this one."""
    crossers = {pid.split("/")[0] for pid, feet in people.items() if crossing_cells({pid: feet}, fps)}
    vehicle_speeds = []
    for edges in vehicles.values():
        moving = [v for v in speeds(edges, fps).values() if v >= MOVING_MPS]
        if len(moving) >= fps:  # at least a second of real movement
            vehicle_speeds.append(statistics.median(moving))
    p85 = percentile(vehicle_speeds, 0.85)
    seen = {"minutes": round(frames / fps / 60, 1), "duration_s": round(frames / fps, 1), "crossings": len(crossers), "vehicles": len(vehicle_speeds),
            "speed_85th_kmh": round(p85 * 3.6, 1) if p85 else None, "crossers": sorted(crossers)}
    cells = crossing_cells(people, fps)
    if not cells:
        return seen
    gaps = traffic_gaps(vehicles, fps, cells, frames)
    return {**seen, "gaps_6s": sum(g >= GAP_ADULT_S for g in gaps), "gaps_12s": sum(g >= GAP_SLOW_S for g in gaps),
            "longest_gap_s": round(max(gaps, default=0.0), 1),
            "gap_6s_share_pct": round(100 * sum(g for g in gaps if g >= GAP_ADULT_S) * fps / frames, 1)}
