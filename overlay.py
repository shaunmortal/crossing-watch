"""What the evidence page lays over each clip: a gap clock that counts from when the first of the pedestrian and the
vehicle reached the spot and freezes in red, with the tier, when the second gets there; and the same gap as a
sentence for anyone who cannot watch the video. On the worst fast person-first card, a stopping strip on the road:
red, the metres the vehicle needed to stop; green, the same from the lower speed limit."""
import html
import math

import road

STRIP_MIN_KMH = 25    # slower than this, the red and green strips are short and look alike
MAX_BEND_DEG = 30     # a vehicle path that turns more than this has no one line to brake along
STRIP_WIDTH_M = 1.8   # about a car's width; the green strip is half as wide, so the red shows along its whole length
RING_M = 0.6          # radius of the ring round the pedestrian's spot
RING_SIDES = 16
STEP_M = 0.1          # the strips are cut to the analysis zone to this precision
GREEN_KMH = min(road.SPEED_LIMITS_KMH)  # the lower replayed limit, 20 km/h


def clock_text(e):
    """The gap as a sentence, in the order it happened."""
    vehicle, gap = e["vehicle"].split("#")[0], f'{e["pet_s"]:.1f} s'
    if round(e["pet_s"], 1) == 0:
        return f"The pedestrian and the {vehicle} were on the same spot at once."
    if e["t_vehicle_s"] > e["t_person_s"]:
        return f"The {vehicle} reached the pedestrian's spot {gap} after they left it."
    return f"The pedestrian stepped where the {vehicle} was {gap} earlier."


def tier_word(e):
    tier = e.get("tier", "serious")
    return (f"serious near-miss, under {road.PET_MAX_S} s" if tier == "serious"
            else f"{tier}, {road.PET_MAX_S}-{road.CLOSE_PASS_S} s")


def stopping_m(kmh):
    """Metres to stop from `kmh` with the speed-limit replay's model: road.REACTION_S to react, then braking at
    road.BRAKING_MPS2."""
    v = kmh / 3.6
    return v * road.REACTION_S + v * v / (2 * road.BRAKING_MPS2)


def unit(dx, dy):
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length else None


def heading(path):
    """Unit vector the vehicle drove along (first point to last), or None when the path has under 3 points, stands
    still, or its second half turns more than MAX_BEND_DEG from its first."""
    if len(path) < 3:
        return None
    mid = len(path) // 2
    a = unit(path[mid][0] - path[0][0], path[mid][1] - path[0][1])
    b = unit(path[-1][0] - path[mid][0], path[-1][1] - path[mid][1])
    if not a or not b or abs(math.degrees(math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1]))) > MAX_BEND_DEG:
        return None
    return unit(path[-1][0] - path[0][0], path[-1][1] - path[0][1])


def stopping(e):
    """The strip's road geometry, or None. Only for a person-first event at STRIP_MIN_KMH or more on a path that does
    not bend, and only when the go/no-go holds: the vehicle was farther from the spot than the green strip, so from
    GREEN_KMH it would have stopped short. The anchor is where the vehicle was while the pedestrian stood on the spot,
    speed times PET back along its path, the same model as road.with_limits."""
    if not (e.get("where") and e["t_person_s"] < e["t_vehicle_s"] and e["vehicle_kmh"] >= STRIP_MIN_KMH):
        return None
    way = heading(e.get("path_vehicle") or [])
    had_m, green_m = e["vehicle_kmh"] / 3.6 * e["pet_s"], stopping_m(GREEN_KMH)
    if not way or had_m <= green_m:
        return None
    anchor = (e["where"][0] - way[0] * had_m, e["where"][1] - way[1] * had_m)
    return {"anchor": anchor, "heading": way, "needed_m": stopping_m(e["vehicle_kmh"]), "had_m": had_m,
            "green_m": green_m}


def strip_pixels(stop, length_m, width_m, zone, H):
    """Video-pixel corners of a strip `width_m` wide from the anchor `length_m` along the heading, cut to where its
    centre line is in the analysis zone and in front of the camera (far road blows up); None if no part is."""
    (x, y), (dx, dy) = stop["anchor"], stop["heading"]
    along = [min(k * STEP_M, length_m) for k in range(math.ceil(length_m / STEP_M) + 1)]
    kept = [t for t in along if road.in_zone((x + t * dx, y + t * dy), zone) and road.to_image(H, x + t * dx, y + t * dy)]
    if len(kept) < 2:
        return None
    side = (-dy * width_m / 2, dx * width_m / 2)
    corners = [road.to_image(H, x + t * dx + s * side[0], y + t * dy + s * side[1])
               for t, s in ((kept[0], -1), (kept[-1], -1), (kept[-1], 1), (kept[0], 1))]
    return None if None in corners else corners


def strip_note(e, stop):
    """The strip's caption: what it shows, and that it redraws the measured numbers, so it is not new evidence."""
    return (f"Red: the {e['vehicle'].split('#')[0]} needed {stop['needed_m']:.1f} m to stop, had {stop['had_m']:.1f} m "
            f"(from {e['vehicle_kmh']:g} km/h, starting where it was while the pedestrian stood on the ringed spot). "
            f"Green: from {GREEN_KMH} km/h it would have stopped in {stop['green_m']:.1f} m, short of the spot. Not new "
            f"evidence: this redraws the measured speed and gap with the speed-limit rows' model ({road.REACTION_S:g} s "
            f"to react, then {road.BRAKING_MPS2:g} m/s² braking), under which any gap below {road.REACTION_S:g} s "
            "always takes the red past the spot.")


def strip(e, site, shown):
    """The stopping strip over card `e`'s clip, then its caption; '' unless `e` is the first of `shown` (the page's
    cards, worst first) that stopping() accepts. The page script sizes it to the video and shows it from when the
    pedestrian is on the spot, so the vehicle is seen driving along the red strip."""
    stop = stopping(e)
    if not stop or next((s for s in shown if stopping(s)), None) is not e:
        return ""
    H = road.homography(site["image_points"], site["world_points"])
    zone = site.get("zone_m") or road.zone_around(site["world_points"])
    red = strip_pixels(stop, stop["needed_m"], STRIP_WIDTH_M, zone, H)
    green = strip_pixels(stop, stop["green_m"], STRIP_WIDTH_M / 2, zone, H)  # None when out of view: red alone
    turns = [2 * math.pi * k / RING_SIDES for k in range(RING_SIDES)]
    ring = [road.to_image(H, e["where"][0] + RING_M * math.cos(a), e["where"][1] + RING_M * math.sin(a)) for a in turns]
    if not red or None in ring:
        return ""
    points = lambda corners: " ".join(f"{x:.1f},{y:.1f}" for x, y in corners)
    shapes = [("red", red)] + ([("green", green)] if green else []) + [("ring", ring)]
    return (f'<svg class="strip" aria-hidden="true">'
            + "".join(f'<polygon class="{cls}" points="{points(c)}"/>' for cls, c in shapes)
            + f'</svg><p class="note">{html.escape(strip_note(e, stop))}</p>')


def clip(video, e, strip_html=""):
    """The card's clip with its clock on top (none without a clip), then the gap sentence and strip()'s markup, if
    any. Without the page script the clock just shows the final gap."""
    sentence = f'<p class="gap">{html.escape(clock_text(e))}</p>'
    if not video:
        return sentence
    frozen = f'{e["pet_s"]:.1f} s, {tier_word(e)}'
    return (f'<div class="clip">{video}<span class="clock frozen" aria-hidden="true" data-pet="{e["pet_s"]:.1f}" '
            f'data-word="{html.escape(tier_word(e))}">{html.escape(frozen)}</span>{sentence}{strip_html}</div>')


# requestAnimationFrame, since timeupdate can fire only 4 times a second. The clock is a function of the clip's
# currentTime alone, so it resets by itself when the clip loops. data-t (on the card) is the first arrival.
SCRIPT = """<script>
(function tick() {
  var SLACK = 0.01;  // seconds: float error in currentTime, well under one frame
  document.querySelectorAll(".card .clip").forEach(function (box) {
    var video = box.querySelector("video"), clock = box.querySelector(".clock");
    var since = video.currentTime - parseFloat(box.closest(".card").dataset.t), pet = parseFloat(clock.dataset.pet);
    var frozen = since >= pet - SLACK;
    clock.hidden = since < -SLACK;
    var strip = box.querySelector(".strip");  // its points are in the video's own pixels
    if (strip && video.videoWidth && !strip.getAttribute("viewBox")) {
      strip.setAttribute("viewBox", "0 0 " + video.videoWidth + " " + video.videoHeight);
    }
    if (strip) strip.classList.toggle("on", !clock.hidden && video.videoWidth > 0);
    clock.classList.toggle("frozen", frozen);
    clock.textContent = frozen ? pet.toFixed(1) + " s, " + clock.dataset.word
                               : (Math.floor(Math.max(0, since + SLACK) * 10) / 10).toFixed(1) + " s";
  });
  requestAnimationFrame(tick);
})();
</script>"""

STYLE = """
.clip { position: relative; } .clip video { display: block; }
.clock { position: absolute; top: 8px; left: 8px; padding: 2px 10px; border-radius: 4px; pointer-events: none;
         background: rgba(0, 0, 0, 0.65); color: #fff; font: 600 1.1rem/1.5 ui-monospace, monospace;
         font-variant-numeric: tabular-nums; }
.clock.frozen { background: #c0392b; } @media (max-width: 600px) { .clock { font-size: 0.8rem; } }
.strip { position: absolute; top: 0; left: 0; width: 100%; height: auto; pointer-events: none; visibility: hidden; }
.strip.on { visibility: visible; } .strip polygon { stroke-width: 2px; vector-effect: non-scaling-stroke; }
.strip .red { fill: rgba(192, 57, 43, 0.45); stroke: #c0392b; } .strip .green { fill: rgba(46, 158, 91, 0.8); stroke: #2e9e5b; }
.strip .ring { fill: none; stroke: #f1c40f; stroke-width: 3px; }
"""
