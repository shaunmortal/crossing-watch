"""Case agent: Muse Spark works one video's case through tools, stops to ask a person for a tape measure, and files
the letter only when the video's metres agree with the tape (GATES.md G2).

Run: python3 agent.py VIDEO SITE.json [--out DIR]               start, or continue a paused case
     python3 agent.py VIDEO SITE.json --answer R1 "7.2 m"       a person answers request R1
     python3 agent.py VIDEO SITE.json --approve --approved-by "A. Rao, Principal" --school "..."
                                                                the head of the school signs the letter off
     python3 agent.py VIDEO SITE.json --reject --notes "..."    ...or sends it back with notes
The case lives in DIR/case/: progress.json (the whole conversation, so a stopped case resumes) and agent_log.jsonl (one
line per step). With AGENT_MODEL_URL set, an open-weights model takes the turns instead (openagent.py, e.g. Muse Spark
Open on Fireworks), and MODEL_API_KEY is needed only for what Muse Spark does in the tools. analyze.py and pack.py
never call the agent: without this script nothing changes. Its tracking
re-reads the SAM replies an earlier analyze.py run cached (--budget 0): new SAM requests that round to a cent or more
stop the run, and the tool fails instead of paying.
The site file marks the distance to tape, in clip pixels, along the road and apart from the calibration points (kerb
to kerb is a calibration input when the rectangle runs kerb to kerb, so that check could never fail):
"check": {"what": "line A to line B along the near kerb (the A near and B near speed-line tape marks)",
          "points": [[x, y], [x, y]]}.
"""
import argparse
import datetime
import html
import http.client
import json
import math
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import analyze
import fixband
import openagent
import pace
import pack
import review
import road
import roadmap
import sam
import seal
import writers_table

MAX_TURNS = 25           # model turns per start or resume (the workshop's turn limit); then the case pauses
MAX_USD = 1.00           # estimated Spark spend on agent turns per case; tracking and pack.ask_plan's calls are apart
USD_PER_M_IN, USD_PER_M_OUT = 1.25, 4.25  # per 1M input / output tokens, an estimate at PRICE (cached input in full)
PRICE = (f"Meta API Standard list price for muse-spark-1.3 (${USD_PER_M_IN:g} / ${USD_PER_M_OUT:g} per 1M tokens, "
         "$0.15 cached input; list price fetched 29 Oct 2026 from https://dev.meta.ai/docs/pricing-rate-limits.md)")
TRACK_BUDGET_USD = "0"   # analyze.py --budget for the agent's tracking: it re-reads the paid run's SAM cache
MAX_REFUSALS = 3         # submit_letter refused this often in a row: a person is asked (the workshop's memo_refused)
MAX_FAILURES = 2         # the same tool failed this often in a row: a person is asked (calling it again rarely helps)
CHECK_TOLERANCE = 0.15   # GATES.md G2: a distance not used for calibration agrees with the tape within 15%
TAPE = re.compile(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(m|cm)\s*", re.I)  # the whole answer: "7.2 m", "7.2m" or "720 cm"
LOG = "agent_log.jsonl"
SPARK = "Muse Spark"     # who takes the turns without AGENT_MODEL_URL
HEAD_NOTES = ("notes", "draft_letter")  # what a revised letter keeps of the one sent back, as pack.new_plan does
# a sent-back letter on the public page: the notes may name a pupil or a teacher, so only agent_log.jsonl keeps them
NOTES_HIDDEN = "The head of the school sent the letter back with notes (kept in the case log, not shown here)."
NUDGE = "Plain text is not accepted. Call exactly one tool."
INSTRUCTIONS = """You work one near-miss case for a school. A phone filmed the crossing outside it; the head of the
school will send the road authority a letter built only from what the video measured. Your tools:
- track: run the tracker on the SAM replies a paid run cached; it never pays. Start with the modes the case names:
  other modes are usually not cached, and track then fails with their cost. SAM video tracks at most 16 objects per
  request, so a concept whose requests hit that limit missed later arrivals: track again with it in "crowd" mode
  ("auto" mode does that switch itself).
- review: what Muse Spark said about each tracked pedestrian (is it a person, a child, a rider).
- measure: the measurements a letter may use, and the video's reading of the site's check distance.
- request_measurement: ask a person to tape-measure the check distance. The case pauses until they answer.
- submit_letter: write the letter. It is refused until a taped check distance agrees with the video.
Call exactly one tool per turn. Never answer in plain text. If a step is refused, do what the refusal says."""


def function(name, description, **properties):
    """A Responses API function tool whose arguments are all required."""
    return {"type": "function", "name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}}


MODE = {"type": "string", "enum": list(analyze.MODES)}
TOOLS = [function("track", "Track people and vehicles with SAM 3.1 and measure near-misses.", people=MODE, vehicles=MODE),
         function("review", "Muse Spark's verdict on each tracked pedestrian in a near-miss."),
         function("measure", "The measurements a letter may quote, and the video's reading of the check distance."),
         function("request_measurement", "Ask a person to tape-measure the site's check distance; the case pauses."),
         function("submit_letter", "Write the letter to the road authority for the head of the school to sign off.",
                  notes={"type": "string", "description": "changes the head of the school asked for, or empty"})]


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def case_site(p):
    """The site file, re-read every time (a person may add the check distance while the case waits), with the
    tracking modes the agent chose."""
    return {**analyze.load_site(p["site"]), **p.get("modes", {})}


def case_data(p):
    """events.json, the events Spark did not reject, and what was watched, as pack.main reads them."""
    out_dir = Path(p["out"])
    data = json.loads((out_dir / "events.json").read_text())
    seen = pack.real_crossers(data["events"], data.get("exposure")
                              or {"minutes": round(pack.clip_minutes(out_dir / "clip.mp4", data["fps"]), 1)})
    return data, pack.confirmed(data["events"]), seen


def calibration(site):
    """The site's calibration points as one string, to tell whether they were marked again since the last track."""
    return json.dumps([site["image_points"], site["world_points"]])


def check_distance(site):
    """The video's reading, in metres, of the site's check distance; None when the site marks none."""
    check = site.get("check")
    if check is None:
        return None
    points = check.get("points") if isinstance(check, dict) else None
    if not (isinstance(check.get("what"), str) and isinstance(points, list) and len(points) == 2 and all(
            isinstance(pt, list) and len(pt) == 2 and all(isinstance(v, (int, float)) for v in pt) for pt in points)):
        raise ValueError('site "check" must be {"what": "<the distance>", "points": [[x, y], [x, y]]} in clip pixels')
    H = road.homography(site["image_points"], site["world_points"])
    ends = [road.to_ground(H, *pt) for pt in points]
    if None in ends:
        raise ValueError('site "check" points must lie on the road, below the horizon')
    return math.dist(*ends)


def named_modes(p):
    """The tracking modes the site file names: analyze.py's paid run used them, so SAM's replies for them are cached."""
    site = analyze.load_site(p["site"])
    return f'people "{site.get("person_mode", "video")}" and vehicles "{site.get("vehicle_mode", "video")}"'


def run_tracker(p, site):
    """analyze.py on the case's video with `site`, from SAM's cache only (--budget 0: a reply not cached stops it
    with its cost, which goes back to the model); per concept SAM video tracked, [requests that hit its object
    limit, requests]."""
    out_dir = Path(p["out"])
    copy = out_dir / "case" / f"site-{site['person_mode']}-{site['vehicle_mode']}.json"
    copy.write_text(json.dumps(site, indent=1, ensure_ascii=False))
    run = subprocess.run([sys.executable, str(Path(__file__).with_name("analyze.py")), p["video"], str(copy),
                          "--out", str(out_dir), "--budget", TRACK_BUDGET_USD], stderr=subprocess.PIPE, text=True)
    if run.returncode:
        raise ValueError(run.stderr.strip()[-500:] or f"analyze.py exited with {run.returncode}")
    clip = out_dir / "clip.mp4"
    frame_size = tuple(int(v) for v in analyze.probe(clip, "stream=width,height").split(","))
    pieces = analyze.parts(clip, out_dir, analyze.frame_count(clip))
    plan = [(site.get("person", "person"), site.get("person_grid", 1))] + [(c, 1) for c in site["vehicles"]]
    switching = analyze.crowd_concepts(site) + analyze.crowd_concepts(site, "auto")  # auto switched the full ones
    return {c: list(analyze.full_requests(pieces, [(c, g)], frame_size)) for c, g in plan if c not in switching}


def track(p, args, key):
    modes = {"person_mode": args.get("people"), "vehicle_mode": args.get("vehicles")}
    if not set(modes.values()) <= set(analyze.MODES):
        return {"summary": "Refused: people and vehicles must each be \"video\", \"crowd\" or \"auto\"."}
    site = {**case_site(p), **modes}
    try:
        full = run_tracker(p, site)
    except ValueError as err:  # mostly a cost: --budget 0 met replies the paid run never asked for
        raise ValueError(f"the site file names {named_modes(p)}, the modes whose SAM replies are cached. {err}")
    p["modes"], p["tracked_with"] = modes, calibration(site)
    data, events, _ = case_data(p)
    hit = [f"{c} in {n} of {total}" for c, (n, total) in full.items() if n]
    summary = (f"Tracked people in {modes['person_mode']} mode and vehicles in {modes['vehicle_mode']} mode: "
               f"near-misses kept: {len(events)}. " + (f"SAM video hit its {sam.MAX_OBJECTS}-object limit for "
                                                      f"{', '.join(hit)} requests." if hit else "No request was full."))
    return {"summary": summary, "full_requests": full, "events": len(events), "cost": data.get("cost")}


def verdicts(p, args, key):
    data, events, _ = case_data(p)
    reviewed = {e["person"]: e["review"] for e in data["events"] if e.get("review")}
    rejected = sum(not v["is_person"] for v in reviewed.values())
    return {"summary": f"Muse Spark reviewed {len(reviewed)} pedestrians and rejected {rejected}; "
                       f"{len(events)} of {len(data['events'])} near-misses kept.", "verdicts": reviewed}


def measure(p, args, key):
    site = case_site(p)
    _, events, seen = case_data(p)
    video_m = check_distance(site)
    check = (f"Video reading of the check distance ({site['check']['what']}): {video_m:.1f} m." if video_m is not None
             else 'The site marks no check distance ("check" in the site file).')
    return {"summary": f"{check} Serious near-misses: {len(pack.serious(events))}, "
                       f"close passes: {len(events) - len(pack.serious(events))}.",
            "check_m": None if video_m is None else round(video_m, 1),
            "measurements": json.loads(pack.facts(site, events, seen))}


def ask_person(p, kind, question):
    rid = f"R{len(p['requests']) + 1}"
    p["requests"].append({"id": rid, "kind": kind, "question": question, "answer": None})
    return rid


def request_measurement(p, args, key):
    site = case_site(p)
    if check_distance(site) is None:
        return {"summary": "Refused: the site marks no check distance to tape."}
    if p.get("tape_m"):
        return {"summary": f"Refused: the tape already reads {p['tape_m']:g} m."}
    what = site["check"]["what"]
    rid = ask_person(p, "measurement", f"Please tape-measure {what} and reply with the length, e.g. \"7.2 m\".")
    return {"status": "needs_input", "request": rid, "summary": f"Asked a person ({rid}) to tape-measure {what}."}


def off_share(video_m, tape):
    return abs(video_m - tape) / tape


def letter_blocker(p, site, events, notes, walking=None):
    """Why the letter may not be written yet, or "": it needs near-misses tracked in this case with the site's
    current calibration points, a taped check distance that agrees with the video, and people walking at a walking
    pace (events.json's "walking") in a video the site file does not mark as no measurement (pace.warning)."""
    video_m, tape = check_distance(site), p.get("tape_m")
    if warning := pace.warning(walking, site):
        return warning.rstrip(".")
    if not events:
        return "no near-misses were measured, so there is nothing to report"
    if video_m is None:
        return 'the site marks no check distance ("check" in the site file), so the metres are unproven'
    if not tape:
        return "no tape-measured check distance yet: call request_measurement"
    if off_share(video_m, tape) > CHECK_TOLERANCE:
        return (f"video {video_m:.1f} m, tape {tape:g} m: {off_share(video_m, tape):.0%} off, more than "
                f"{CHECK_TOLERANCE:.0%}, so the calibration points must be marked again")
    if p.get("tracked_with") != calibration(site):
        return "the near-misses were not tracked with the site's current calibration points: call track again"
    if re.search(r"\d", notes):
        return "notes may not hold numbers: a letter's numbers come only from the measurements"
    return ""


def submit_letter(p, args, key):
    site, notes = case_site(p), str(args.get("notes") or "")
    data, events, seen = case_data(p)
    reason = letter_blocker(p, site, events, notes, data.get("walking"))
    if reason:
        p["refusals"] += 1
        if p["refusals"] < MAX_REFUSALS:
            return {"summary": f"Letter refused: {reason}."}
        p["refusals"] = 0
        rid = ask_person(p, "letter_refused", f"The letter was refused {MAX_REFUSALS} times in a row, last because "
                                              f"{reason}. What should the agent do?")
        return {"status": "needs_input", "request": rid, "summary": f"Letter refused {MAX_REFUSALS} times ({reason}); "
                                                                     f"asked a person ({rid})."}
    p["refusals"], video_m, tape = 0, check_distance(site), p["tape_m"]
    measured = {**json.loads(pack.facts(site, events, seen)), "calibration_check": {
        "what": site["check"]["what"], "video_m": round(video_m, 1), "tape_m": tape,
        "off_pct": round(100 * off_share(video_m, tape))}}  # measured, so the letter may quote it
    p["measured"] = measured = json.dumps(measured, indent=1, ensure_ascii=False)  # the page's number check too
    prompt = pack.LETTER_PROMPT.format(facts=measured, language=site.get("letter_language", "English"))
    prompt += f"\n\nThe head of the school asks for these changes: {notes}" if notes else ""
    out_dir = Path(p["out"])
    try:
        photo = pack.street_photo(out_dir / "clip.mp4", out_dir / "street.jpg", site.get("person", "person"),
                                  site.get("vehicles", []))
    except (ValueError, OSError, subprocess.CalledProcessError):
        photo = None
    kept = {k: v for k, v in (p.get("letter") or {}).items() if k in HEAD_NOTES}  # the sign-off counts edits after them
    p["letter"] = {**pack.ask_plan(prompt, measured, key, photo), **kept}
    pack.write_plan(out_dir, p["letter"])
    left = sum(len(p["letter"].get(k, [])) for k in ("unmeasured", "unsupported", "accuses"))
    return {"status": "needs_review", "fix": p["letter"]["fix"], "letter": p["letter"]["letter"],
            "summary": f"Video {video_m:.1f} m, tape {tape:g} m, {off_share(video_m, tape):.0%} off: proven. "
                       f"Letter written by {p['letter']['writer']}" + (f", with {left} points for a person to check" if left else "")
                       + "; waiting for the head of the school."}


RUNNERS = {"track": track, "review": verdicts, "measure": measure, "request_measurement": request_measurement,
           "submit_letter": submit_letter}


def run_tool(p, call, key):
    """The one tool the model called, run; a refusal or failure goes back to the model as the result."""
    runner, arguments = RUNNERS.get(call.get("name")), call.get("arguments") or "{}"
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
        if not runner or not isinstance(args, dict):
            raise ValueError(f"no tool {call.get('name')!r} with arguments {str(arguments)[:100]}")
        result = runner(p, args, key)
    except (SystemExit, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError,
            http.client.HTTPException) as err:
        return tool_failed(p, call.get("name"), f"{call.get('name')} failed: {str(err)[:300]}")
    p["failed_tool"], p["failures"] = None, 0
    return result


def tool_failed(p, name, failure):
    """A failed tool's result. The same tool failing MAX_FAILURES times in a row asks a person, as refused letters do:
    on a case with no video, track failed about 20 turns running before the refusals stopped the case."""
    failures = p.get("failures", 0) + 1 if p.get("failed_tool") == name else 1
    if failures < MAX_FAILURES:
        p["failed_tool"], p["failures"] = name, failures
        return {"summary": failure}
    p["failed_tool"], p["failures"] = None, 0
    rid = ask_person(p, "tool_failed", f"{name} failed {MAX_FAILURES} times in a row, last with: {failure}. "
                                       "What should the agent do?")
    return {"status": "needs_input", "request": rid,
            "summary": f"{failure} ({MAX_FAILURES} times in a row); asked a person ({rid})."}


def model_label():
    return openagent.label() if openagent.URL else SPARK


def rates():
    """USD per 1M input / output tokens for the turns (cached input counted in full, as for Spark)."""
    return (openagent.quote()[0], openagent.quote()[2]) if openagent.URL else (USD_PER_M_IN, USD_PER_M_OUT)


def model_turn(p, key):
    """One turn: (the tool call or None, the usage), from Muse Spark on the Meta API or, with AGENT_MODEL_URL, from
    openagent (Chat Completions; the Meta key never goes there)."""
    if openagent.URL:
        return openagent.step(INSTRUCTIONS, p["messages"], TOOLS)
    body = {"model": review.MODEL, "instructions": INSTRUCTIONS, "input": p["messages"], "tools": TOOLS,
            "parallel_tool_calls": False, "store": False, "reasoning": {"effort": "low"}}
    reply = spark_turn(body, key)
    call = next((o for o in reply.get("output") or [] if o.get("type") == "function_call"), None)
    return call, reply.get("usage") or {}


def replay(call, result):
    """The call and its output for the next turn: only these are replayed, reasoning is not kept with store=False."""
    if openagent.URL:
        return openagent.replay(call, result)
    arguments = call.get("arguments") if isinstance(call.get("arguments"), str) else json.dumps(call.get("arguments"))
    return [{"type": "function_call", "call_id": call.get("call_id"), "name": call.get("name"), "arguments": arguments},
            {"type": "function_call_output", "call_id": call.get("call_id"), "output": json.dumps(result)}]


def spark_turn(body, key):
    req = urllib.request.Request(sam.API_URL, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=pack.TIMEOUT_S) as response:
        reply = json.load(response)
    if not isinstance(reply, dict):
        raise ValueError(f"the model's reply is not a JSON object: {str(reply)[:200]}")
    return reply


def save(p, entry=None):
    """progress.json, plus one line in agent_log.jsonl (printed too) for what just happened."""
    case_dir = Path(p["out"]) / "case"
    (case_dir / "progress.json").write_text(json.dumps(p, indent=1, ensure_ascii=False))
    if entry:
        with open(case_dir / LOG, "a") as log:
            log.write(json.dumps({"time": now(), **entry}, ensure_ascii=False) + "\n")
        print(f"{entry.get('tool') or entry.get('person') or 'stop'}: {entry['summary']}", flush=True)


def drive(p, key):
    """Model turns, one tool each, until the case stops for a person or reaches the turn or dollar cap."""
    for _ in range(MAX_TURNS):
        if p["usd"] >= MAX_USD:
            p["status"] = "over_budget"
            save(p, {"summary": f"Stopped: agent turns cost about ${p['usd']:.2f}, the cap is ${MAX_USD:.2f}."})
            return p["status"]
        started = time.monotonic()
        try:
            call, usage = model_turn(p, key)
        except (OSError, ValueError, http.client.HTTPException) as err:  # URLError and JSONDecodeError included
            p["status"] = "paused"
            save(p, {"summary": f"Paused: the model call failed ({str(err)[:200]})."})
            return p["status"]
        wall_s = round(time.monotonic() - started, 1)
        used_in, _, used_out, _ = (n or 0 for n in writers_table.tokens(usage))
        usd_in, usd_out = rates()
        p["usd"] += (used_in * usd_in + used_out * usd_out) / 1e6
        p["turn"] += 1
        if call:
            result = run_tool(p, call, key)
            p["messages"] += replay(call, result)
        else:
            result = {"summary": "Answered in plain text; told to call exactly one tool."}
            p["messages"].append({"role": "user", "content": NUDGE})
        p["status"] = result.get("status", "running")
        save(p, {"turn": p["turn"], "tool": call and call.get("name"), "summary": result["summary"],
                 "status": p["status"], "model": model_label(), "input_tokens": used_in, "output_tokens": used_out,
                 "usage": usage, "wall_s": wall_s, "usd": round(p["usd"], 4)})
        if p["status"] == "needs_review":
            write_page(p)
        if p["status"] != "running":
            return p["status"]
    p["status"] = "paused"
    save(p, {"summary": f"Paused after {MAX_TURNS} turns; run again to continue."})
    return p["status"]


def case_section(out_dir):
    """"How the agent worked this case" for the evidence page, from agent_log.jsonl ("" without one)."""
    log = Path(out_dir) / "case" / LOG
    if not log.exists():
        return ""
    steps = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    items = "".join(f"<li>{step_time(s)}{'Person: ' if s.get('person') else ''}"
                    f"{html.escape(NOTES_HIDDEN if s.get('person') == 'reject' else s['summary'])}</li>" for s in steps)
    turns, usd = sum("turn" in s for s in steps), max([s.get("usd", 0) for s in steps] or [0])
    model = next((s["model"] for s in steps if s.get("model")), SPARK)  # work() keeps one model per case
    price = PRICE if model == SPARK else openagent.price_words()
    return (f'<section id="case"><h2>How the agent worked this case</h2><ol>{items}</ol><p class="note">'
            f"{html.escape(model)} chose one tool per turn: {turns} turns, about ${usd:.2f}, estimated at the "
            f"{html.escape(price)}, with cached input "
            "counted at the full input price. Tracking (SAM, Spark's pedestrian reviews, the sound check) is billed "
            "apart and is not in this figure. Steps marked Person were a person's answers.</p></section>")


def step_time(step):
    """When a step happened, in this computer's time zone ("Mon 21:05 IST "); "" for a step logged without one."""
    if not step.get("time"):
        return ""
    return datetime.datetime.fromisoformat(step["time"]).astimezone().strftime("%a %H:%M %Z ")


def with_measured(page_html, measured):
    """The page with every number of the agent's measurements, the tape check included (pack.page knows only the
    site's), added to the letter's in-browser number check, so an edit leaves a quoted "tape 7.2 m" unflagged."""
    numbers = " ".join(n.replace(",", "") for n in pack.NUMBER.findall(measured))
    return page_html.replace('data-measured="', f'data-measured="{numbers} ', 1) if numbers else page_html


def write_page(p, images=None):
    """pack.main's page for this case, with its sign-off, receipt and street seen from above, and the share/ folder
    with the SHA256SUMS the page says is there."""
    out, site, (data, events, seen) = Path(p["out"]), case_site(p), case_data(p)
    paths, photo = data.get("paths") or {}, out / "street.jpg"
    page = pack.page(site, events, seen, p["letter"], images, data["fps"], data.get("cost"),
                     data.get("sam_full_requests"), data.get("privacy"), signoff=pack.read_signoff(out),
                     receipt=pack.receipt_line(data, p["letter"], images), source_sha256=data.get("source_sha256"),
                     timeline=data.get("timeline"), paths=paths, case=case_section(out), walking=data.get("walking"),
                     ground=roadmap.ground(photo, site, events, out, paths) if photo.exists() else None,
                     recording_s=data.get("recording_s"), removed=pack.removed_note(data["events"]))
    page = with_measured(page, p.get("measured", ""))
    (out / "index.html").write_text(page)
    seal.write_sums(pack.share(out, page))


def sign_off(p, key, approved_by, school):
    """The head of the school approved the letter: signoff.json (pack.sign), Muse Image draws the fix inside the
    measured band as pack.main does (fixband.draw), and the page is written. No agent turn. The pictures are kept in
    progress.json, so writing the page again pays for none."""
    out, site, images = Path(p["out"]), case_site(p), None
    photo = out / "street.jpg"
    pack.sign(out, p["letter"], approved_by, school)
    if photo.exists() and key:
        try:
            images = fixband.draw(photo, p["letter"]["fix"], pack.fix_instruction(p["letter"]), case_data(p)[1], site,
                                  pack.photo_people(out / "clip.mp4", site.get("person", "person")),
                                  lambda image, words, path: pack.draw_fix(image, words, key, path), out)
        except (SystemExit, OSError, ValueError, KeyError, IndexError, TypeError, AttributeError,
                http.client.HTTPException, subprocess.CalledProcessError) as err:  # pack.main's: signed all the same
            print(f"fix image failed, the page has the letter only: {err}", file=sys.stderr)
    p["status"], p["images"] = "done", images
    save(p, {"person": "approve", "summary": f"{approved_by}, {school}, approved the letter."})
    write_page(p, images)


def tape_metres(text):
    """The taped length in metres. Only "N m" or "N cm" is read, so "7 ft", "7,2 m" or a bare "720" is refused."""
    match = TAPE.fullmatch(text)
    metres = float(match[1]) / (100 if match[2].lower() == "cm" else 1) if match else 0
    if metres <= 0:
        raise SystemExit(f"answer with the taped length in m or cm, e.g. \"7.2 m\", not {text!r}")
    return metres


def person_step(p, key, answer=None, approve=None, notes=None):
    """Apply what a person did since the case stopped: the message for the model, or None when no turn follows.
    `approve` is (approved_by, school). A done case gets its page written again (a page fix after sign-off)."""
    status, open_requests = p["status"], [r for r in p["requests"] if r["answer"] is None]
    if answer:
        request = next((r for r in open_requests if r["id"] == answer[0]), None)
        if status != "needs_input" or not request:
            raise SystemExit(f"no open request {answer[0]}")
        if request["kind"] == "measurement":
            p["tape_m"] = tape_metres(answer[1])
        request["answer"] = answer[1]
        save(p, {"person": "answer", "summary": f"{request['id']} answered: {answer[1]}"})
        return f"A person answered {request['id']} ({request['question']}): {answer[1]}"
    if approve or notes is not None:
        if status != "needs_review":
            raise SystemExit("no letter is waiting for sign-off")
        if approve:
            return sign_off(p, key, *approve)
        first = p["letter"]  # as pack.new_plan keeps them: every note so far and the first AI draft
        p["letter"] = {**first, "notes": first.get("notes", []) + [notes],
                       "draft_letter": first.get("draft_letter", first["letter"])}
        save(p, {"person": "reject", "summary": f"The head of the school sent the letter back: {notes}"})
        return f"The head of the school sent the letter back with these notes: {notes}. Revise it with submit_letter."
    if status == "needs_input":
        raise SystemExit(f"waiting for a person: {open_requests[-1]['question']} "
                         f"Reply with --answer {open_requests[-1]['id']} \"...\"")
    if status == "done":
        write_page(p, p.get("images"))
        print(f"this case is done: {Path(p['out']) / 'index.html'} and share/ written again", flush=True)
        return None
    if status in ("needs_review", "over_budget"):
        raise SystemExit({"needs_review": "the letter waits for --approve or --reject --notes \"...\"",
                          "over_budget": f"this case reached the ${MAX_USD:.2f} cap"}[status])
    return ("You have more turns. Continue." if p["turn"] else
            f"Work the case for the crossing \"{case_site(p).get('name', '')}\" and file the letter. The case names "
            f"{named_modes(p)} for tracking.")


def work(video, site, out_dir, key, answer=None, approve=None, notes=None):
    """Start or resume the case in out_dir/case; returns its status. A new case never starts where pack.py signed a
    letter: its tracking rewrites events.json and its letter plan.json, and the signed letter may already be filed."""
    case_dir = Path(out_dir) / "case"
    saved = case_dir / "progress.json"
    signed = None if saved.exists() else pack.read_signoff(Path(out_dir))
    if signed:
        raise SystemExit(f"{out_dir} holds the letter {signed['approved_by']} signed on {signed['date']} with pack.py; "
                         "pass a new --out folder")
    case_dir.mkdir(parents=True, exist_ok=True)
    p = json.loads(saved.read_text()) if saved.exists() else {
        "video": str(Path(video).resolve()), "site": str(Path(site).resolve()), "out": str(out_dir), "status": "new",
        "turn": 0, "usd": 0.0, "messages": [], "requests": [], "tape_m": None, "refusals": 0, "letter": None,
        "agent_model": model_label()}
    if p["video"] != str(Path(video).resolve()):
        raise SystemExit(f"{case_dir} is the case of {p['video']}; pass a new --out folder")
    if p.get("agent_model", SPARK) != model_label():  # its messages are in that model's API format
        raise SystemExit(f"{case_dir} is a case {p.get('agent_model', SPARK)} worked, not {model_label()}: set "
                         "AGENT_MODEL_URL and AGENT_MODEL as it ran, or pass a new --out folder")
    rates()  # an unpriced open model stops here, before any turn
    message = person_step(p, key, answer, approve, notes)
    if not message:
        return p["status"]
    p["messages"].append({"role": "user", "content": message})
    return drive(p, key)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video")
    parser.add_argument("site")
    parser.add_argument("--out", help="output folder (default out/<video name>)")
    parser.add_argument("--answer", nargs=2, metavar=("REQUEST", "TEXT"), help='e.g. --answer R1 "7.2 m"')
    parser.add_argument("--approve", action="store_true", help="sign the letter off; needs --approved-by and --school")
    parser.add_argument("--approved-by", default="", metavar="NAME", help='who read and approved the letter, e.g. '
                        '"A. Rao, Principal"')
    parser.add_argument("--school", default="", help="the school that sends the letter")
    parser.add_argument("--reject", action="store_true", help="send the letter back; needs --notes")
    parser.add_argument("--notes", help="what to change, with --reject")
    args = parser.parse_args()
    if args.reject != (args.notes is not None):
        parser.error("--reject and --notes go together")
    signer = (args.approved_by.strip(), args.school.strip())
    if not args.approve == all(signer) == any(signer):
        parser.error("--approve, --approved-by and --school go together")
    if args.approve and args.reject:
        parser.error("--approve or --reject, not both")
    out_dir = Path(args.out or Path("out") / Path(args.video).stem)
    key = sam.env_value("MODEL_API_KEY") if openagent.URL else sam.load_api_key()  # Spark's tools still use it
    status = work(args.video, args.site, out_dir, key, args.answer, signer if args.approve else None,
                  args.notes)
    print(f"case {status}: {out_dir / 'case' / 'progress.json'}")


if __name__ == "__main__":
    main()
