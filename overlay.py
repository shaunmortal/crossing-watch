"""What the evidence page lays over each clip: a gap clock that counts from when the first of the pedestrian and the
vehicle reached the spot and freezes in red, with the tier, when the second gets there; and the same gap as a
sentence for anyone who cannot watch the video."""
import html

import road


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


def clip(video, e):
    """The card's clip with its clock on top (none without a clip), then the gap sentence. Without the page script
    the clock just shows the final gap."""
    sentence = f'<p class="gap">{html.escape(clock_text(e))}</p>'
    if not video:
        return sentence
    frozen = f'{e["pet_s"]:.1f} s, {tier_word(e)}'
    return (f'<div class="clip">{video}<span class="clock frozen" aria-hidden="true" data-pet="{e["pet_s"]:.1f}" '
            f'data-word="{html.escape(tier_word(e))}">{html.escape(frozen)}</span></div>{sentence}')


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
"""
