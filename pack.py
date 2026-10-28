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
import re
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

import render
import review
import road
import sam

IMAGE_EDIT_URL = "https://api.meta.ai/v1/images/edits"
IMAGE_MODEL = "muse-image-1.0"
TIMEOUT_S = 300
SHOWN_EVENTS = 5
LETTER_PROMPT = """You help a school ask its road authority to make the crossing outside it safer.
Below are measurements from a video of the crossing, made by Crossing Watch (SAM 3.1 tracking, road-plane geometry,
post-encroachment time). Use ONLY these facts; never invent numbers, names, places or dates.

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
    }, indent=1)


def ask_spark(prompt, api_key):
    body = json.dumps({"model": review.MODEL, "reasoning": {"effort": "low"}, "input": prompt}).encode()
    req = urllib.request.Request(sam.API_URL, data=body, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
        reply = json.load(response)
    text = "".join(c.get("text", "") for o in reply.get("output", []) if o.get("type") == "message"
                   for c in o.get("content", []))
    match = re.search(r"\{.*\}", text, re.S)
    plan = json.loads(match[0], strict=False) if match else {}  # Spark's letter may hold raw newlines
    if not isinstance(plan, dict) or not all(isinstance(plan.get(k), str) and plan[k].strip() for k in ("fix", "why", "image_prompt", "letter")):
        raise ValueError(f"Spark's plan is incomplete: {text[:200]!r}")
    return plan


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


def street_photo(clip, out_path, person_concept="person"):
    """First frame of the clip with every head blurred (it is shown on the page and sent to Muse Image). Uses the
    same SAM cache analyze wrote (part0/ for long videos); without it there is no photo rather than unblurred faces."""
    folder = clip.parent / "part0" if (clip.parent / "part0").is_dir() else clip.parent
    people_file = sam.cache_path(folder, person_concept)
    if not people_file.exists():
        raise ValueError(f"no person tracks at {people_file}; not showing an unblurred street photo")
    people = sam.parse(people_file.read_text()).values()
    size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", str(clip)], check=True, capture_output=True, text=True).stdout.strip()
    filters = ",".join(render.blur_filters(people, 0, 0, tuple(int(v) for v in size.split(",")))) or "null"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf", filters, "-frames:v", "1", str(out_path)],
                   check=True)
    return out_path


def event_card(i, e):
    verdict, at30, at20 = e.get("review") or {}, e["with_limit"]["30"], e["with_limit"]["20"]
    road_user = verdict.get("road_user", "pedestrian (not reviewed by Spark)")
    road_user = "pedestrian" if road_user == "unclear" else road_user
    who = html.escape(("an " if road_user[0] in "aeiou" else "a ") + road_user)
    video = f'<video src="{html.escape(e["clip"])}" controls muted loop playsinline></video>' if e.get("clip") else ""
    return f"""<article class="card">{video}
<h3>#{i} &middot; {html.escape(e.get("tier", "serious"))} &middot; {html.escape(e["vehicle"].split("#")[0])} at {e["vehicle_kmh"]} km/h, {e["pet_s"]:.1f} s from {who}</h3>
<table><tr><th></th><th>Impact speed if hit</th><th>Adult death risk</th></tr>
<tr><td>As driven</td><td>{e.get("impact_kmh", e["vehicle_kmh"])} km/h</td><td>{e["death_risk_pct"]}%</td></tr>
<tr><td>30 km/h limit</td><td>{at30["impact_kmh"]} km/h</td><td>{at30["death_risk_pct"]}%</td></tr>
<tr><td>20 km/h limit</td><td>{at20["impact_kmh"]} km/h</td><td>{at20["death_risk_pct"]}%</td></tr></table>
<p class="note">At {e["t_person_s"]:.1f} s in the video. Gap {e["gap_m"]} m. {html.escape(verdict.get("reason", ""))}</p>
{heard_line(e.get("heard"))}</article>"""


def heard_line(heard):
    """What Muse Wonder heard around the moment, e.g. 'brakes 0.4 s before, horn 0.2 s after'."""
    if not heard:
        return ""
    parts = [f'{html.escape(s["sound"])} {abs(s["t_s"]):.1f} s {"before" if s["t_s"] < 0 else "after"}' for s in heard]
    return f'<p class="note">Heard (Muse Wonder): {", ".join(parts)}.</p>'


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
    return f'<section><h2>Letter to the road authority</h2><div class="letter">{paragraphs}</div></section>'


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


def page(site, events, seen, plan, images):
    cards = "\n".join(event_card(i + 1, e) for i, e in enumerate(events[:SHOWN_EVENTS])) or (
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
<style>{STYLE}</style></head><body>
<h1>Crossing Watch: near-miss evidence</h1>
<p class="muted">{html.escape(site.get("name", ""))}</p>
<div class="stats">{stats(events, seen)}</div>
<section><h2>Worst moments</h2>{cards}</section>{fix_section(plan, images)}{letter_section(plan)}
<section><h2>How this was measured</h2><p class="note">{html.escape(method)}</p></section></body></html>"""


def clip_minutes(clip, fps):
    frames = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries",
                             "stream=nb_read_packets", "-of", "csv=p=0", str(clip)],
                            check=True, capture_output=True, text=True).stdout
    return int(frames) / fps / 60


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
            key = sam.load_api_key()
            plan = ask_spark(LETTER_PROMPT.format(facts=facts(site, events, seen),
                                                  language=site.get("letter_language", "English")), key)
            photo = street_photo(out_dir / "clip.mp4", out_dir / "street.jpg", site.get("person", "person"))
            images = (photo.name, draw_fix(photo, plan["image_prompt"], key, out_dir / "street-fixed.jpg").name)
        except (SystemExit, OSError, ValueError, KeyError, IndexError, TypeError, AttributeError,
                http.client.HTTPException, subprocess.CalledProcessError) as err:
            print(f"letter or fix image failed, page will show the measurements only: {err}", file=sys.stderr)
    (out_dir / "index.html").write_text(page(site, events, seen, plan, images))
    print(f"wrote {out_dir / 'index.html'}: {len(serious(events))} serious, {len(events) - len(serious(events))} close "
          f"passes, fix: {plan['fix'] if plan else 'none'}")


if __name__ == "__main__":
    main()
