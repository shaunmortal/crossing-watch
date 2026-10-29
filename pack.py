"""Evidence pack: one page a school can send to the road authority. Muse Spark picks the fix and writes the
letter from the measured events only; Muse Image draws that fix onto the real street.

Run after analyze.py: python3 pack.py OUT_DIR SITE.json
Writes OUT_DIR/index.html next to the clips (open it in a browser).
"""
import argparse
import base64
import html
import http.client
import json
import os
import re
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

import crowd
import render
import review
import roadmap
import road
import sam

IMAGE_EDIT_URL = "https://api.meta.ai/v1/images/edits"
IMAGE_MODEL = "muse-image-1.0"
TIMEOUT_S = 300
SHOWN_EVENTS = 5
MIN_RATE_MINUTES = 15  # shortest video scaled to hourly rates (MUTCD Warrant 4 counts 15-minute periods)
LETTER_URL = os.environ.get("LETTER_MODEL_URL", "")  # an OpenAI-compatible server, e.g. llama-server with Muse
LETTER_MODEL = os.environ.get("LETTER_MODEL", "Muse Glimmer 30B")  # Glimmer; empty: Muse Spark writes the letter
WRITER = f"{LETTER_MODEL} (open weights, self-hosted)" if LETTER_URL else "Muse Spark"
OPEN_MODEL_TIMEOUT_S = 900  # a 30B model on two T4s writes a letter in minutes, not seconds
JUDGE = "Muse Spark (a separate reviewer)"
JUDGE_PROMPT = """You review a letter before a school sends it to its road authority. MEASUREMENTS are the only facts.
List every problem: a claim or number the measurements do not support; saying a standard or warrant is met; a death
risk stated for a child; blaming a named person. Tone, wording and the choice of fix are not problems.
Reply JSON only: {{"problems": ["<one short sentence each>"]}}, with [] if there are none.

MEASUREMENTS:
{facts}

LETTER:
{letter}"""
LETTER_TRIES = 3     # Spark gets this many tries at a letter whose every number was measured
NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")  # 1,200 is one number
LETTER_PROMPT = """You help a school ask its road authority to make the crossing outside it safer.
Below are measurements from a video of the crossing, made by Crossing Watch (SAM 3.1 tracking, road-plane geometry,
post-encroachment time). Use ONLY these facts; never invent numbers, names, places or dates.
Death-risk figures are for adults hit by a car front: never state a death risk for a child.
From the engineering lines, mention at most PV² and the share of time in gaps, briefly, with their main caveat;
never say a standard is met.

{facts}

Reply with JSON only:
{{"fix": "<one specific physical fix, e.g. raised zebra crossing, speed table, 20 km/h zone with signs>",
  "why": "<one sentence linking the fix to the measurements>",
  "image_prompt": "<an instruction to edit a photo of this street so it shows the fix; keep people and buildings unchanged>",
  "letter": "<a short formal letter in {language} from the head of the school to the road authority: what was measured,
             the worst near-misses, the requested fix, and an offer to share the video. Use [School name] and [Date]
             as placeholders.>"}}"""


def confirmed(events):
    """Events whose track Spark did not reject as 'not a person' in any reviewed event (unreviewed ones stay,
    marked as such): one rejected pole must not come back through its unreviewed pairings with other vehicles."""
    rejected = {e["person"] for e in events if (e.get("review") or {}).get("is_person") is False}
    return [e for e in events if e["person"] not in rejected]


def serious(events):
    return [e for e in events if e.get("tier", "serious") == "serious"]


def facts(site, events, seen):
    worst = events[:SHOWN_EVENTS]
    return json.dumps({
        "site": site.get("name", ""), "observed": seen,
        "serious_near_misses": len(serious(events)), "close_passes": len(events) - len(serious(events)),
        "definition": f"serious: pedestrian and moving vehicle on the same spot less than {road.PET_MAX_S} s apart; "
                      f"close pass: {road.PET_MAX_S}-{road.CLOSE_PASS_S} s",
        "worst": [{"tier": e.get("tier", "serious"), "pet_s": e["pet_s"], "vehicle": e["vehicle"].split("#")[0], "vehicle_kmh": e["vehicle_kmh"],
                   "adult_death_risk_if_hit_pct": e["death_risk_pct"], "at_20_kmh_limit": e["with_limit"]["20"],
                   "road_user": (e.get("review") or {}).get("road_user", "not reviewed")} for e in worst],
        "risk_source": "Rosén & Sander 2009, adults 15+, car fronts",
        "engineering": engineering_lines(seen, None),
    }, indent=1, ensure_ascii=False)  # \u escapes would add digits the number check counts as measured



def engineering_lines(seen, cost):
    """The numbers road engineers already use, from the same tracks: PV^2 (IRC:103-2012) and gaps in traffic
    (UK Traffic Signs Manual ch. 6), plus what the tracking cost. Rates from a short video are scaled, and say so."""
    minutes = seen["duration_s"] / 60 if seen.get("duration_s") else seen.get("minutes") or 0
    if not minutes:
        return []
    lines = []
    if "crossings" in seen and "vehicles" in seen and minutes < MIN_RATE_MINUTES:
        lines.append(f"PV² and hourly rates need at least {MIN_RATE_MINUTES} minutes of video; this one is "
                     f"{minutes:.1f}. Counted: {seen['crossings']} pedestrian crossings, {seen['vehicles']} moving vehicles.")
    elif "crossings" in seen and "vehicles" in seen:
        shown = round(minutes, 1)
        source = (f"scaled from {shown:g} minutes of video; a formal check counts the full peak hour" if minutes < 60
                  else f"from {shown:g} minutes of video")
        lines.append(f"PV² = {road.pv2(seen['crossings'], seen['vehicles'], minutes) / 1e8:.1f} x 10^8: "
                     f"{round(seen['crossings'] * 60 / minutes)} pedestrians and {round(seen['vehicles'] * 60 / minutes)} "
                     f"moving vehicles an hour ({source}; pedestrians are people who walked 2 m or more on the marked carriageway, or "
                     f"anywhere in view if none is marked, and broken tracks can count one twice: 1.3x the true count "
                     f"in our drone test). IRC:103-2012 (6.7.4.1.2): a controlled crossing may be "
                     f"warranted above {road.PV2_UNDIVIDED / 1e8:g} x 10^8 on an undivided road, "
                     f"{road.PV2_DIVIDED / 1e8:g} x 10^8 on a divided road.")
    if "gaps_6s" in seen:
        lines.append(f"{seen.get('gap_6s_share_pct', '?')}% of the time was inside gaps of {road.GAP_ADULT_S:g} s or "
                     f"more with no moving vehicle where people crossed: {seen['gaps_6s']} "
                     f"gap{'' if seen['gaps_6s'] == 1 else 's'}, {seen['gaps_12s']} of them {road.GAP_SLOW_S:g} s or "
                     f"more, longest {seen['longest_gap_s']} s (the first and last are cut short by the video). "
                     f"UK Traffic Signs Manual ch. 6 (13.5.2): 4-6 s is an "
                     f"acceptable gap at urban speeds; other groups, such as children, may need 10-12 s or longer.")
    if cost and cost.get("sam_usd") is not None:
        basis = (f"about ${cost['image_usd']:.2f} of it is image detection at a guessed $0.002 an image, as Meta's "
                 "image price was not found" if cost.get("image_usd") else "at Meta's list price for SAM video")
        lines.append(f"SAM tracking cost for this video: about ${cost['sam_usd']:.2f}, so about "
                     f"${cost['sam_usd'] * 60 / minutes:.2f} per hour of footage ({basis}).")
    return lines


def engineering(seen, cost):
    lines = engineering_lines(seen, cost)
    if not lines:
        return ""
    items = "".join(f"<li>{html.escape(line)}</li>" for line in lines)
    return f"<section><h2>Numbers road engineers use</h2><ul>{items}</ul></section>"


def limit_note(full):
    """Say so when SAM's per-request object limit was reached: then the counts are a minimum."""
    if not full or not full[0]:
        return ""
    return (f'<p class="note">In {full[0]} of {full[1]} tracking requests SAM reached its {sam.MAX_OBJECTS}-object '
            "limit, so some people or vehicles were not tracked: counts and near-misses here are a minimum.</p>")

def unmeasured(text, facts_text):
    """Numbers in `text` that appear nowhere in the measured facts: a letter to an authority must not invent any."""
    value = lambda n: float(n.replace(",", ""))
    known = {value(n) for n in NUMBER.findall(facts_text)}
    return sorted({n for n in NUMBER.findall(text) if value(n) not in known}, key=value)


def ask_plan(prompt, measured, api_key, photo=None, tries=LETTER_TRIES):
    """The model's fix and letter, verified before use in two layers (Meta's verifiable-agents workshop): code
    checks that every number was measured, then Muse Spark as a separate reviewer (LLM as judge) lists claims the
    measurements do not support. An invalid reply or either objection goes back with the reason; after the last try
    the letter is kept with what remains listed for a person to check before sending."""
    note, plan, bad, problems = "", None, [], []
    for attempt in range(tries):
        try:
            plan = model_plan(prompt + note, api_key, photo)
        except ValueError as err:  # JSONDecodeError included
            if attempt == tries - 1 and plan is None:
                raise
            note = f"\n\nYour previous output was invalid: {str(err)[:200]}. Reply with the JSON object only."
            continue
        bad = unmeasured(plan["letter"] + " " + plan["why"], prompt + "\n" + measured)
        problems = [] if bad or not api_key else judge_problems(plan["letter"], measured, api_key)
        if not bad and not problems:
            return {**plan, "writer": WRITER, **({"judged_by": JUDGE} if api_key else {})}
        note = (f"\n\nYour previous letter used numbers that are not in the measurements: {', '.join(bad)}. "
                "Use only numbers given above." if bad else
                "\n\nA reviewer found claims in your previous letter that the measurements do not support: "
                + " ".join(problems) + " Fix them.")
    return {**plan, "writer": WRITER, "unmeasured": bad, "unsupported": problems}


def judge_problems(letter, measured, api_key):
    """Muse Spark, as a reviewer separate from the writer, lists the letter's unsupported claims ([] if none). A
    reply it cannot read counts as one problem, so a broken judge never passes a letter silently."""
    problems = read_problems(spark_reply(JUDGE_PROMPT.format(facts=measured, letter=letter), None, api_key))
    return ["The reviewer's reply could not be read."] if problems is None else problems


def read_problems(text):
    match = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(match[0]) if match else None
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("problems"), list):
        return None
    return [str(p)[:300] for p in data["problems"] if isinstance(p, str) and p.strip()]


def model_plan(prompt, api_key, photo=None):
    """One reply from the letter model, Muse Spark or (with LETTER_MODEL_URL) an open-weights model, parsed into
    the plan. The blurred street photo, when there is one, lets the model see the street it is fixing."""
    image = "data:image/jpeg;base64," + base64.b64encode(photo.read_bytes()).decode() if photo else None
    text = open_model_reply(prompt, image) if LETTER_URL else spark_reply(prompt, image, api_key)
    match = re.search(r"\{.*\}", text, re.S)
    plan = json.loads(match[0], strict=False) if match else {}  # a letter may hold raw newlines
    if not isinstance(plan, dict) or not all(isinstance(plan.get(k), str) and plan[k].strip() for k in ("fix", "why", "image_prompt", "letter")):
        raise ValueError(f"the plan is incomplete: {text[:200]!r}")
    return plan


def spark_reply(prompt, image, api_key):
    if not api_key:
        raise ValueError("no MODEL_API_KEY for Muse Spark (or set LETTER_MODEL_URL for an open-weights model)")
    content = [{"type": "input_text", "text": prompt}] + ([{"type": "input_image", "image_url": image}] if image else [])
    body = json.dumps({"model": review.MODEL, "reasoning": {"effort": "low"}, "text": {"format": {"type": "json_object"}},
                       "input": [{"role": "user", "content": content}]}).encode()
    req = urllib.request.Request(sam.API_URL, data=body, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
        reply = json.load(response)
    return "".join(c.get("text", "") for o in reply.get("output", []) if o.get("type") == "message"
                   for c in o.get("content", []))


def open_model_reply(prompt, image):
    """Chat completion from an OpenAI-compatible server, e.g. llama-server running Muse Glimmer 30B on a GPU."""
    content = [{"type": "text", "text": prompt}] + ([{"type": "image_url", "image_url": {"url": image}}] if image else [])
    body = json.dumps({"model": LETTER_MODEL, "messages": [{"role": "user", "content": content}],
                       "response_format": {"type": "json_object"}}).encode()
    req = urllib.request.Request(LETTER_URL.rstrip("/") + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=OPEN_MODEL_TIMEOUT_S) as response:
        reply = json.load(response)
    return reply["choices"][0]["message"]["content"]


def draw_fix(photo, instruction, api_key, out_path):
    """Muse Image edit of the real street photo; returns out_path."""
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in (("model", IMAGE_MODEL), ("prompt", instruction))]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="street.jpg"\r\n'
                 f"Content-Type: image/jpeg\r\n\r\n".encode() + photo.read_bytes() + b"\r\n")
    req = urllib.request.Request(IMAGE_EDIT_URL, data=b"".join(parts) + f"--{boundary}--\r\n".encode(), headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
        reply = json.load(response)
    data = reply.get("data") if isinstance(reply, dict) else None
    if not (isinstance(data, list) and data and isinstance(data[0], dict) and data[0].get("b64_json")):
        raise ValueError(f"Muse Image returned no image: {str(reply)[:200]}")
    image = base64.b64decode(data[0]["b64_json"])
    raw = out_path.with_suffix(".webp")
    raw.write_bytes(image)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), str(out_path)], check=True)
    return out_path


def street_photo(clip, out_path, person_concept="person", crowd_mode=False):
    """First frame of the clip with every head blurred (it is shown on the page and sent to Muse Image). Uses the
    same SAM cache analyze wrote (crowd mode's first image, or part0/ for long videos); without it there is no
    photo rather than unblurred faces."""
    folder = clip.parent / "part0" if (clip.parent / "part0").is_dir() else clip.parent
    people_file = (crowd.cache_dir(clip.parent, person_concept) / f"{0:06d}.sam.txt" if crowd_mode
                   else sam.cache_path(folder, person_concept))
    if not people_file.exists():
        raise ValueError(f"no person tracks at {people_file}; not showing an unblurred street photo")
    people = sam.parse(people_file.read_text()).values()
    size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", str(clip)], check=True, capture_output=True, text=True).stdout.strip()
    filters = ",".join(render.blur_filters(people, 0, 0, tuple(int(v) for v in size.split(",")))) or "null"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf", filters, "-frames:v", "1", str(out_path)],
                   check=True)
    return out_path


def event_card(i, e, fps):
    """Card #i, linkable as #event-i; data-t is the second of its clip when the first of the two reached the spot."""
    verdict, at30, at20 = e.get("review") or {}, e["with_limit"]["30"], e["with_limit"]["20"]
    road_user = verdict.get("road_user", "pedestrian (not reviewed by Spark)")
    road_user = "pedestrian" if road_user == "unclear" else road_user
    who = html.escape(("an " if road_user[0] in "aeiou" else "a ") + road_user)
    video = f'<video src="{html.escape(e["clip"])}" controls muted loop playsinline></video>' if e.get("clip") else ""
    moment_s = min(e["t_person_s"], e["t_vehicle_s"]) - render.window(e, fps)[0] / fps
    return f"""<article class="card" id="event-{i}" data-t="{moment_s:.2f}">{video}
<h3>#{i} &middot; {html.escape(e.get("tier", "serious"))} &middot; {html.escape(e["vehicle"].split("#")[0])} at {e["vehicle_kmh"]} km/h, {e["pet_s"]:.1f} s from {who}</h3>
<table><tr><th></th><th>Impact speed if hit</th><th>Adult death risk</th></tr>
<tr><td>As driven</td><td>{e.get("impact_kmh", e["vehicle_kmh"])} km/h</td><td>{e["death_risk_pct"]}%</td></tr>
<tr><td>30 km/h limit</td><td>{at30["impact_kmh"]} km/h</td><td>{at30["death_risk_pct"]}%</td></tr>
<tr><td>20 km/h limit</td><td>{at20["impact_kmh"]} km/h</td><td>{at20["death_risk_pct"]}%</td></tr></table>
<p class="note">At {e["t_person_s"]:.1f} s in the video. Gap {e["gap_m"]} m. {html.escape(verdict.get("reason", ""))}
{html.escape(risk_caveat(road_user, e["vehicle"].split("#")[0]))}</p>
{heard_line(e.get("heard"))}</article>"""


def risk_caveat(road_user, vehicle):
    """The death-risk curve is for adults hit by a car front; say so where this event is neither."""
    notes = ["The curve is for adults, so this is not a child's risk."] if road_user == "child" else []
    if vehicle != "car":
        notes.append(f"It was measured for car fronts; for a {vehicle} it is only a rough guide.")
    return " ".join(notes)


def heard_line(heard):
    """What Muse Wonder heard around the moment, e.g. 'brakes 0.4 s before, horn 0.2 s after'."""
    if not heard:
        return ""
    parts = [f'{html.escape(s["sound"])} {abs(s["t_s"]):.1f} s {"before" if s["t_s"] < 0 else "after"}' for s in heard]
    return f'<p class="note">Heard (Muse Wonder): {", ".join(parts)}.</p>'



def map_section(events, site):
    drawn = roadmap.svg(events, site["world_points"], SHOWN_EVENTS)
    if not drawn:
        return ""
    return (f"<section><h2>Where it happened</h2>{drawn}<p class=\"note\">Seen from above, in metres on the road "
            "(grid every 5 m; dashed: the measured area). Blue: the pedestrian, red: the vehicle, 2 s either side. "
            "Filled dots: serious near-misses; rings: close passes.</p></section>")


def fix_section(plan, images):
    if not plan:
        return ""
    head = f"""<section><h2>Proposed fix: {html.escape(plan["fix"])}</h2><p>{html.escape(plan["why"])}</p>"""
    if not images:
        return head + "</section>"
    return head + f"""
<div class="pair"><figure><img src="{images[0]}" alt="The street today"><figcaption>Today</figcaption></figure>
<figure><img src="{images[1]}" alt="The street with the fix, drawn by Muse Image"><figcaption>With the fix
(drawn by Muse Image)</figcaption></figure></div></section>"""


def letter_section(plan):
    if not plan:
        return ""
    paragraphs = "".join(f"<p>{html.escape(p)}</p>" for p in plan["letter"].split("\n") if p.strip())
    check = "".join(f'<p class="note">Check before sending: {html.escape(text)}</p>' for text in (
        [f'these numbers are not in the measurements: {", ".join(plan["unmeasured"])}.'] if plan.get("unmeasured") else [])
        + [f"the reviewer says: {p}" for p in plan.get("unsupported", [])])
    checked = (f"Every number was checked against the measurements by code, and the claims by {plan['judged_by']}."
               if plan.get("judged_by") else "Every number was checked against the measurements by code.")
    check += f'<p class="note">{html.escape(checked)}</p>' if not plan.get("unmeasured") and not plan.get("unsupported") else ""
    writer = f'<p class="note">Fix and letter written by {html.escape(plan["writer"])}.</p>' if plan.get("writer") else ""
    return (f'<section><h2>Letter to the road authority</h2>{writer}<div class="letter">{paragraphs}</div>{check}'
            '</section>')


STYLE = """
:root { --bg: #fafaf7; --ink: #1d1d1b; --muted: #66665f; --line: #deded6; --accent: #c0392b; }
@media (prefers-color-scheme: dark) { :root { --bg: #161614; --ink: #ececE6; --muted: #a3a39a; --line: #34342f; --accent: #ff6b5b; } }
body { margin: 0 auto; max-width: 880px; padding: 24px 16px 64px; background: var(--bg); color: var(--ink);
       font: 16px/1.5 system-ui, sans-serif; }
h1 { font-size: 1.8rem; margin: 0 0 4px; } h2 { margin-top: 40px; } .muted, .note { color: var(--muted); }
.stats { display: flex; gap: 24px; flex-wrap: wrap; margin: 20px 0; } .stats b { display: block; font-size: 2rem; color: var(--accent); }
.card { border-top: 1px solid var(--line); padding: 16px 0; } video, img { width: 100%; border-radius: 6px; }
table { border-collapse: collapse; width: 100%; } td, th { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--line); }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; } @media (max-width: 600px) { .pair { grid-template-columns: 1fr; } }
figure { margin: 0; } .letter { border-left: 3px solid var(--line); padding-left: 16px; }
"""


def stats(events, seen):
    """Headline numbers. They always say how much was watched, so a quiet video never reads as "safe"."""
    n_serious, crossings = len(serious(events)), seen.get("crossings") or 0
    tiles = [(n_serious, f"serious near-misses (under {road.PET_MAX_S} s)"),
             (len(events) - n_serious, f"close passes ({road.PET_MAX_S}-{road.CLOSE_PASS_S} s)"),
             (crossings, "pedestrian crossings watched"), (seen.get("vehicles", "?"), "moving vehicles"),
             (seen.get("minutes", "?"), "minutes of video")]
    if seen.get("speed_85th_kmh"):
        tiles.append((seen["speed_85th_kmh"], "km/h, 85% of vehicles at or below"))
    if crossings:
        tiles.append((round(100 * len(events) / crossings, 1), "conflicts per 100 crossings"))
    return "".join(f"<div><b>{html.escape(str(v))}</b>{html.escape(label)}</div>" for v, label in tiles)


def page(site, events, seen, plan, images, fps, cost=None, full=None):
    cards = "\n".join(event_card(i + 1, e, fps) for i, e in enumerate(events[:SHOWN_EVENTS])) or (
        f"<p>No conflicts under {road.CLOSE_PASS_S} s in these {html.escape(str(seen.get('minutes', '?')))} minutes. "
        "A short recording can miss rare events: record more school-run periods before drawing any conclusion.</p>")
    method = (f"SAM 3.1 tracked every pedestrian and vehicle. Four points on the road turned pixels into metres. "
              f"A near-miss is a pedestrian and a moving vehicle on the same spot (within {road.CONFLICT_RADIUS_M} m) "
              f"less than {road.PET_MAX_S} s apart (post-encroachment time); {road.PET_MAX_S}-{road.CLOSE_PASS_S} s is "
              f"reported as a close pass. Muse Spark checked each clip and removed "
              f"tracks that were not people. Death risk: Rosén & Sander (2009), Accident Analysis & Prevention "
              f"41(3):536-542, for adults hit by a car front; children are not covered by that study. Speed-limit rows "
              f"replay the same moment with the vehicle no faster than the limit, a {road.REACTION_S} s reaction and "
              f"{road.BRAKING_MPS2} m/s² braking. {site.get('calibration_note', '')}")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Crossing Watch evidence</title>
<style>{STYLE}{roadmap.STYLE}</style></head><body>
<h1>Crossing Watch: near-miss evidence</h1>
<p class="muted">{html.escape(site.get("name", ""))}</p>
<div class="stats">{stats(events, seen)}</div>{limit_note(full)}
{engineering(seen, cost)}
{map_section(events, site)}<section><h2>Worst moments</h2>{cards}</section>{fix_section(plan, images)}{letter_section(plan)}
<section><h2>How this was measured</h2><p class="note">{html.escape(method)}</p></section></body></html>"""


def clip_minutes(clip, fps):
    frames = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries",
                             "stream=nb_read_packets", "-of", "csv=p=0", str(clip)],
                            check=True, capture_output=True, text=True).stdout
    return int(frames) / fps / 60



def optional_key():
    """The Meta API key, or None: an open-weights letter model can run without one."""
    try:
        return sam.load_api_key()
    except SystemExit:
        return None

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir")
    parser.add_argument("site")
    args = parser.parse_args()
    out_dir, site = Path(args.out_dir), json.loads(Path(args.site).read_text())
    data = json.loads((out_dir / "events.json").read_text())
    events = confirmed(data["events"])
    seen = data.get("exposure") or {"minutes": round(clip_minutes(out_dir / "clip.mp4", data["fps"]), 1)}
    plan, images = None, None
    if events:
        try:
            photo = street_photo(out_dir / "clip.mp4", out_dir / "street.jpg", site.get("person", "person"),
                                 site.get("person_mode") == "crowd")
        except (ValueError, OSError, subprocess.CalledProcessError) as err:
            print(f"no street photo: {err}", file=sys.stderr)
            photo = None
        try:
            key = optional_key()
            measured = facts(site, events, seen)
            prompt = LETTER_PROMPT.format(facts=measured, language=site.get("letter_language", "English"))
            plan = ask_plan(prompt, measured, key, photo)
            if photo and key:  # Muse Image draws the fix; without a key there is no street image on the page
                images = (photo.name, draw_fix(photo, plan["image_prompt"], key, out_dir / "street-fixed.jpg").name)
        except (SystemExit, OSError, ValueError, KeyError, IndexError, TypeError, AttributeError,
                http.client.HTTPException, subprocess.CalledProcessError) as err:
            print(f"letter or fix image failed, page will show the measurements only: {err}", file=sys.stderr)
    (out_dir / "index.html").write_text(page(site, events, seen, plan, images, data["fps"], data.get("cost"),
                                             data.get("sam_full_requests")))
    print(f"wrote {out_dir / 'index.html'}: {len(serious(events))} serious, {len(events) - len(serious(events))} close "
          f"passes, fix: {plan['fix'] if plan else 'none'}")


if __name__ == "__main__":
    main()
