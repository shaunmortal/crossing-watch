"""Blind check (G5 in GATES.md): the pipeline's near-misses shuffled among decoys, for a rater who is not told which is
which. Run after analyze.py on the same folder, before anyone labels:

  python3 blind_set.py OUT_DIR SITE.json [--to DIR] [--review-decoys]

Writes DIR/blind/ (clip01.mp4 ... and index.html, the rater's page: give the rater this folder only) and
DIR/blind-key.json, kept apart, for score_humans.py (DIR is OUT_DIR unless --to). Tracks are rebuilt from the SAM
replies analyze.py cached: one that is not cached stops the run, so it never pays for SAM. A decoy whose pedestrian
Spark has not looked at is left out, unless --review-decoys lets Spark look (one paid call each).
"""
import argparse
import html
import json
import random
import shutil
import subprocess
from pathlib import Path

import analyze
import crowd
import pack
import render
import review
import road
import sam

MAX_NEAR_MISSES = 12   # the most dangerous near-misses Spark kept, at most this many, and as many decoys
DECOY_MIN_PET_S = 5.0  # a decoy: a pedestrian and a moving vehicle on the same spot at least this far apart...
DECOY_MAX_PET_S = 8.0  # ...and at most this, so the vehicle still reaches the spot inside the clip
LEAD_S = 2.0           # every clip starts this long before the first of the two reached the spot (earlier to fit)...
CLIP_S = 12.0          # ...and lasts this long, near-miss or decoy alike, so its length gives nothing away
SEED = 20261102        # the fixed shuffle
CHOICES = (("serious", f"Serious: the vehicle went through the spot the person was on, or was about to step onto, "
                       f"less than about {road.PET_MAX_S:g} s apart"),
           ("close", f"Close: about {road.PET_MAX_S:g} to {road.CLOSE_PASS_S:g} s apart"),
           ("none", "None: no real danger between these two"),
           ("cant_tell", "Can't tell"))


def refuse(*args):
    raise SystemExit("a SAM reply is not cached in this folder: run analyze.py on it first (blind_set.py never pays)")


def load_tracks(site, out_dir):
    """(person boxes, vehicle boxes, pedestrian pieces, vehicle shapes, frame size, frame count) as analyze.py built
    them, from its cached SAM replies only. Refuses when a SAM video request for people was full: people who came
    later have no track, so their faces would go to the rater unblurred."""
    sam.request = crowd.request = refuse
    clip = out_dir / "clip.mp4"
    frame_size = tuple(int(v) for v in analyze.probe(clip, "stream=width,height").split(","))
    total = analyze.frame_count(clip)
    pieces = analyze.parts(clip, out_dir, total)
    switched = analyze.auto_switch(site, pieces, analyze.video_plan(site), None, frame_size)  # as analyze.py did
    person, grid = site.get("person", "person"), site.get("person_grid", 1)
    if person not in analyze.crowd_concepts(site) + list(switched) and \
            analyze.full_requests(pieces, [(person, grid)], frame_size)[0]:
        raise SystemExit(f"a SAM video request for {person} hit the {sam.MAX_OBJECTS}-object limit, so some faces have "
                         'no track to blur: analyze this video with "person_mode": "crowd" first')
    tracks_of = lambda concept, grid=1: analyze.concept_tracks(site, concept, clip, total, pieces, out_dir, None,
                                                               frame_size, grid, switched)[0]
    person_boxes = tracks_of(person, grid)
    vehicle_boxes = {f"{c}#{vid}": t for c in site["vehicles"] for vid, t in tracks_of(c).items()}
    H = road.homography(site["image_points"], site["world_points"])
    return (person_boxes, vehicle_boxes, *analyze.road_tracks(site, H, person_boxes, vehicle_boxes, frame_size),
            frame_size, total)


def decoys(candidates, verdict_of, n, total):
    """Up to n pairs whose closest pass was DECOY_MIN_PET_S to DECOY_MAX_PET_S apart, closest first, each pedestrian
    one Spark says is a person, not one it was unsure of (so a pole is never a decoy), and in no near-miss or close
    pass inside its clip."""
    out = []
    for e in sorted((e for e in candidates if e["pet_s"] >= DECOY_MIN_PET_S), key=lambda e: e["pet_s"]):
        if len(out) == n:
            break
        verdict = verdict_of(e["person"]) or {}
        if (not endangered(e, candidates, total) and verdict.get("is_person") and not verdict.get("review_unclear")
                and not verdict.get("review_disputed")):
            out.append(e)
    return out


def endangered(e, candidates, total):
    """Whether e's pedestrian passes another vehicle under road.CLOSE_PASS_S apart inside e's clip: the rater would
    see real danger where the key says none."""
    start, person = clip_start(e, total), e["person"].split("/")[0]
    return any(c["person"].split("/")[0] == person and c["vehicle"] != e["vehicle"] and c["pet_s"] < road.CLOSE_PASS_S
               and min(c["t_person_s"], c["t_vehicle_s"]) <= start + CLIP_S
               and max(c["t_person_s"], c["t_vehicle_s"]) >= start for c in candidates)


def clip_start(e, total):
    """When e's clip starts: LEAD_S before the first of the two reached the spot, earlier when CLIP_S from there
    would run past the last of the video's `total` frames, so every clip is CLIP_S long."""
    latest = (total - 1) / analyze.FPS - CLIP_S
    if latest < 0:
        raise SystemExit(f"the video is {total} frames, shorter than a {CLIP_S:g} s blind clip")
    return min(max(0.0, min(e["t_person_s"], e["t_vehicle_s"]) - LEAD_S), latest)


def blind_window(e, total):
    """The event with its two times moved so render.window cuts CLIP_S from clip_start."""
    start = clip_start(e, total) + render.PAD_S
    return {**e, "t_person_s": start, "t_vehicle_s": start + CLIP_S - 2 * render.PAD_S}


def shuffled(near_misses, fakes):
    """[(clip name, truth, event)] in a fixed random order: truth is the near-miss's tier, or "decoy"."""
    entries = [(e["tier"], e) for e in near_misses] + [("decoy", e) for e in fakes]
    random.Random(SEED).shuffle(entries)
    return [(f"clip{k:02d}.mp4", truth, e) for k, (truth, e) in enumerate(entries, 1)]


def key_record(clips):
    """blind-key.json: the truth behind each clip, for score_humans.py. Never in the rater's folder."""
    return {"seed": SEED, "clips": [{"clip": name, "truth": truth, "person": e["person"], "vehicle": e["vehicle"],
                                     "pet_s": e["pet_s"], "t_s": min(e["t_person_s"], e["t_vehicle_s"])}
                                    for name, truth, e in clips]}


def page(names):
    """The rater's page: each clip with the four choices, kept in the browser as they go, and a button that downloads
    the answers as JSON for score_humans.py."""
    cards = "".join(
        f'<article><h2>{html.escape(name[:-4])}</h2><video src="{html.escape(name)}" controls muted loop playsinline '
        f'preload="metadata"></video><fieldset>' + "".join(
            f'<label><input type="radio" name="{html.escape(name)}" value="{value}"> {html.escape(label)}</label>'
            for value, label in CHOICES) + "</fieldset></article>" for name in names)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Blind check</title><style>
:root {{ color-scheme: light dark; }} body {{ margin: 0 auto; max-width: 760px; padding: 24px 16px 64px;
font: 16px/1.5 system-ui, sans-serif; }} video {{ width: 100%; border-radius: 6px; }} label {{ display: block; }}
fieldset {{ border: 0; padding: 8px 0; }} article {{ border-top: 1px solid #8886; padding: 16px 0; }}
input[type=text] {{ width: 100%; font: inherit; padding: 6px; box-sizing: border-box; }}
button {{ font: inherit; padding: 8px 16px; }}</style></head><body><form>
<h1>Blind check: {len(names)} clips</h1>
<p>Each clip shows one person in a <b>cyan</b> box and one vehicle in a <b>red</b> box; the faces SAM found are
blurred. Judge only those two. Some clips were flagged by software as near-misses and some were not; you are not told
which, and the order is random. Watch each clip as often as you like.</p>
<label>Your name and role (for example: A. Rao, transport lecturer)<input type="text" name="rater"></label>
{cards}<p id="status"></p><button type="button" id="save">Download answers</button></form>
<script>{{
const KEY = "blind-check-answers", form = document.querySelector("form"), status = document.getElementById("status");
const answers = () => ({{rater: form.rater.value.trim(), answers: Object.fromEntries(
  [...form.querySelectorAll("input[type=radio]:checked")].map(box => [box.name, box.value]))}});
const show = () => status.textContent = Object.keys(answers().answers).length + " of {len(names)} answered.";
try {{
  const saved = JSON.parse(localStorage.getItem(KEY) || "{{}}");
  form.rater.value = saved.rater || "";
  for (const box of form.querySelectorAll("input[type=radio]"))
    box.checked = (saved.answers || {{}})[box.name] === box.value;
}} catch (err) {{}}  // no storage (a private window): the page still works, answers just are not kept
show();
form.addEventListener("change", () => {{
  show();
  try {{ localStorage.setItem(KEY, JSON.stringify(answers())); }} catch (err) {{}}
}});
document.getElementById("save").addEventListener("click", () => {{
  const data = answers();
  if (!data.rater) {{ alert("Please write your name and role first."); return; }}
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], {{type: "application/json"}}));
  link.download = "answers-" + data.rater.replace(/[^A-Za-z0-9]+/g, "-") + ".json";
  link.click();
}});
}}</script></body></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", help="an analyze.py output folder")
    parser.add_argument("site")
    parser.add_argument("--to", help="where blind/ and blind-key.json go (default: out_dir)")
    parser.add_argument("--review-decoys", action="store_true",
                        help="let Muse Spark look at decoy pedestrians it has not seen (one paid call each)")
    args = parser.parse_args()
    out_dir, site = Path(args.out_dir), analyze.load_site(args.site)
    to = Path(args.to or out_dir)
    if (to / "blind-key.json").exists():  # the set a rater may already hold must not change under them
        raise SystemExit(f"{to / 'blind-key.json'} exists: a blind set is made once. Delete it and {to / 'blind'} "
                         "only if no one has labelled yet")
    events = json.loads((out_dir / "events.json").read_text())["events"]
    person_boxes, vehicle_boxes, people, vehicles, frame_size, total = load_tracks(site, out_dir)
    near = pack.confirmed(events)[:MAX_NEAR_MISSES]
    if any(e["person"] not in people or e["vehicle"] not in vehicle_boxes for e in near):
        raise SystemExit("events.json does not match the tracks rebuilt from cache: re-run analyze.py on this folder")
    key = sam.load_api_key() if args.review_decoys else None
    verdicts = {e["person"]: e["review"] for e in events if e.get("review")}

    def verdict_of(pid):
        if pid not in verdicts and key:  # paid: Spark looks once at a decoy pedestrian it has not seen
            try:
                verdicts[pid] = review.review(out_dir / "clip.mp4", analyze.piece_boxes(person_boxes, people, pid),
                                              frame_size, out_dir / f"person-{pid.replace('/', '-')}.jpg", key,
                                              site.get("view") == "top-down")
            except (subprocess.CalledProcessError, OSError) as err:  # no crop: no verdict, so not a decoy
                print(f"review of {pid} failed: {err}", flush=True)
                verdicts[pid] = None
        return verdicts.get(pid)

    fakes = decoys(road.conflicts(people, vehicles, analyze.FPS, pet_max=DECOY_MAX_PET_S), verdict_of, len(near),
                   total)
    clips = shuffled(near, fakes)
    shutil.rmtree(to / "blind", ignore_errors=True)  # no clip left from an earlier set
    (to / "blind").mkdir(parents=True)
    for name, _, e in clips:
        render.render(out_dir / "clip.mp4", blind_window(e, total),
                      analyze.piece_boxes(person_boxes, people, e["person"]), vehicle_boxes[e["vehicle"]], analyze.FPS,
                      to / "blind" / name, everyone=list(person_boxes.values()), frame_size=frame_size,
                      vehicles=list(vehicle_boxes.values()))
        if analyze.frame_count(to / "blind" / name) != round(CLIP_S * analyze.FPS) + 1:  # a shorter clip gives it away
            raise SystemExit(f"{to / 'blind' / name} is not {CLIP_S:g} s long: no key written, do not hand it out")
    (to / "blind" / "index.html").write_text(page([name for name, _, _ in clips]))
    (to / "blind-key.json").write_text(json.dumps(key_record(clips), indent=1))
    print(f"wrote {to / 'blind'}: {len(near)} near-misses and {len(fakes)} decoys, shuffled; the key is "
          f"{to / 'blind-key.json'}: keep it away from the rater. Blurred are the faces SAM found: watch every "
          "clip before handing it out")


if __name__ == "__main__":
    main()
