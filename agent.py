"""Case agent: Muse Spark works one video's case through tools, stops to ask a person for a tape measure, and files
the letter only when the video's metres agree with the tape (GATES.md G2).

Run: python3 agent.py VIDEO SITE.json [--out DIR]               start, or continue a paused case
     python3 agent.py VIDEO SITE.json --answer R1 "7.2 m"       a person answers request R1
     python3 agent.py VIDEO SITE.json --approve                 the head of the school signs the letter off
     python3 agent.py VIDEO SITE.json --reject --notes "..."    ...or sends it back with notes
The case lives in DIR/case/: progress.json (the whole conversation, so a stopped case resumes) and agent_log.jsonl (one
line per step). analyze.py and pack.py never call the agent: without this script nothing changes.
The site file marks the distance to tape, in clip pixels, apart from the calibration points:
"check": {"what": "kerb to kerb along the zebra", "points": [[x, y], [x, y]]}.
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
import urllib.request
from pathlib import Path

import analyze
import pack
import review
import road
import sam

MAX_TURNS = 25           # model turns per start or resume (the workshop's turn limit); then the case pauses
MAX_USD = 1.00           # Muse Spark spend on agent turns per case; the letter's own calls in pack.ask_plan are apart
USD_PER_M_IN, USD_PER_M_OUT = 1.25, 4.25  # Spark's rate per 1M input / output tokens: Muse Spark Open's list price
MAX_REFUSALS = 3         # submit_letter refused this often in a row: a person is asked (the workshop's memo_refused)
CHECK_TOLERANCE = 0.15   # GATES.md G2: a distance not used for calibration agrees with the tape within 15%
TAPE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(cm)?", re.I)  # "7.2 m", "7.2" or "720 cm"
LOG = "agent_log.jsonl"
NUDGE = "Plain text is not accepted. Call exactly one tool."
INSTRUCTIONS = """You work one near-miss case for a school. A phone filmed the crossing outside it; the head of the
school will send the road authority a letter built only from what the video measured. Your tools:
- track: run the tracker. Start with people and vehicles in "video" mode. SAM video tracks at most 16 objects per
  request, so a concept whose requests hit that limit missed later arrivals: track again with it in "crowd" mode.
- review: what Muse Spark said about each tracked pedestrian (is it a person, a child, a rider).
- measure: the measurements a letter may use, and the video's reading of the site's check distance.
- request_measurement: ask a person to tape-measure the check distance. The case pauses until they answer.
- submit_letter: write the letter. It is refused until a taped check distance agrees with the video.
Call exactly one tool per turn. Never answer in plain text. If a step is refused, do what the refusal says."""


def function(name, description, **properties):
    """A Responses API function tool whose arguments are all required."""
    return {"type": "function", "name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}}


MODE = {"type": "string", "enum": ["video", "crowd"]}
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
    seen = data.get("exposure") or {"minutes": round(pack.clip_minutes(out_dir / "clip.mp4", data["fps"]), 1)}
    return data, pack.confirmed(data["events"]), seen


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
    return math.dist(road.to_ground(H, *points[0]), road.to_ground(H, *points[1]))


def run_tracker(p, site):
    """analyze.py on the case's video with `site` (SAM replies are cached, so a re-run pays only for what is new);
    per concept SAM video tracked, [requests that hit its object limit, requests]."""
    out_dir = Path(p["out"])
    copy = out_dir / "case" / f"site-{site['person_mode']}-{site['vehicle_mode']}.json"
    copy.write_text(json.dumps(site, indent=1, ensure_ascii=False))
    run = subprocess.run([sys.executable, str(Path(__file__).with_name("analyze.py")), p["video"], str(copy),
                          "--out", str(out_dir)], stderr=subprocess.PIPE, text=True)
    if run.returncode:
        raise ValueError(run.stderr.strip()[-500:] or f"analyze.py exited with {run.returncode}")
    clip = out_dir / "clip.mp4"
    frame_size = tuple(int(v) for v in analyze.probe(clip, "stream=width,height").split(","))
    pieces = analyze.parts(clip, out_dir, analyze.frame_count(clip))
    plan = [(site.get("person", "person"), site.get("person_grid", 1))] + [(c, 1) for c in site["vehicles"]]
    return {c: list(analyze.full_requests(pieces, [(c, g)], frame_size)) for c, g in plan
            if c not in analyze.crowd_concepts(site)}


def track(p, args, key):
    modes = {"person_mode": args.get("people"), "vehicle_mode": args.get("vehicles")}
    if not set(modes.values()) <= {"video", "crowd"}:
        return {"summary": "Refused: people and vehicles must each be \"video\" or \"crowd\"."}
    full = run_tracker(p, {**case_site(p), **modes})
    p["modes"] = modes
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


def letter_blocker(p, site, events, notes):
    """Why the letter may not be written yet, or "": it needs near-misses and a taped check distance that agrees
    with the video."""
    video_m, tape = check_distance(site), p.get("tape_m")
    if not events:
        return "no near-misses were measured, so there is nothing to report"
    if video_m is None:
        return 'the site marks no check distance ("check" in the site file), so the metres are unproven'
    if not tape:
        return "no tape-measured check distance yet: call request_measurement"
    if off_share(video_m, tape) > CHECK_TOLERANCE:
        return (f"video {video_m:.1f} m, tape {tape:g} m: {off_share(video_m, tape):.0%} off, more than "
                f"{CHECK_TOLERANCE:.0%}, so the calibration points must be marked again")
    if re.search(r"\d", notes):
        return "notes may not hold numbers: a letter's numbers come only from the measurements"
    return ""


def submit_letter(p, args, key):
    site, notes = case_site(p), str(args.get("notes") or "")
    _, events, seen = case_data(p)
    reason = letter_blocker(p, site, events, notes)
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
    measured = json.dumps(measured, indent=1, ensure_ascii=False)
    prompt = pack.LETTER_PROMPT.format(facts=measured, language=site.get("letter_language", "English"))
    prompt += f"\n\nThe head of the school asks for these changes: {notes}" if notes else ""
    out_dir = Path(p["out"])
    try:
        photo = pack.street_photo(out_dir / "clip.mp4", out_dir / "street.jpg", site.get("person", "person"),
                                  site.get("person_mode") == "crowd")
    except (ValueError, OSError, subprocess.CalledProcessError):
        photo = None
    p["letter"] = pack.ask_plan(prompt, measured, key, photo)
    (out_dir / "plan.json").write_text(json.dumps(p["letter"], indent=1, ensure_ascii=False))
    left = len(p["letter"].get("unmeasured", [])) + len(p["letter"].get("unsupported", []))
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
        return runner(p, args, key)
    except (SystemExit, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError,
            http.client.HTTPException) as err:
        return {"summary": f"{call.get('name')} failed: {str(err)[:300]}"}


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
            save(p, {"summary": f"Stopped: agent turns cost ${p['usd']:.2f}, the cap is ${MAX_USD:.2f}."})
            return p["status"]
        body = {"model": review.MODEL, "instructions": INSTRUCTIONS, "input": p["messages"], "tools": TOOLS,
                "parallel_tool_calls": False, "store": False, "reasoning": {"effort": "low"}}
        try:
            reply = spark_turn(body, key)
        except (OSError, ValueError, http.client.HTTPException) as err:  # URLError and JSONDecodeError included
            p["status"] = "paused"
            save(p, {"summary": f"Paused: the model call failed ({str(err)[:200]})."})
            return p["status"]
        usage = reply.get("usage") or {}
        used_in, used_out = usage.get("input_tokens") or 0, usage.get("output_tokens") or 0
        p["usd"] += (used_in * USD_PER_M_IN + used_out * USD_PER_M_OUT) / 1e6
        p["turn"] += 1
        call = next((o for o in reply.get("output") or [] if o.get("type") == "function_call"), None)
        if call:  # only the call and its output are replayed: reasoning items are not kept with store=False
            result = run_tool(p, call, key)
            arguments = call.get("arguments") if isinstance(call.get("arguments"), str) else json.dumps(call.get("arguments"))
            p["messages"] += [{"type": "function_call", "call_id": call.get("call_id"), "name": call.get("name"),
                               "arguments": arguments},
                              {"type": "function_call_output", "call_id": call.get("call_id"), "output": json.dumps(result)}]
        else:
            result = {"summary": "Answered in plain text; told to call exactly one tool."}
            p["messages"].append({"role": "user", "content": NUDGE})
        p["status"] = result.get("status", "running")
        save(p, {"turn": p["turn"], "tool": call and call.get("name"), "summary": result["summary"],
                 "status": p["status"], "input_tokens": used_in, "output_tokens": used_out, "usd": round(p["usd"], 4)})
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
    items = "".join(f"<li>{'Person: ' if s.get('person') else ''}{html.escape(s['summary'])}</li>" for s in steps)
    turns, usd = sum("turn" in s for s in steps), max([s.get("usd", 0) for s in steps] or [0])
    return (f'<section><h2>How the agent worked this case</h2><ol>{items}</ol><p class="note">Muse Spark chose one '
            f"tool per turn: {turns} turns, about ${usd:.2f} at ${USD_PER_M_IN:g} / ${USD_PER_M_OUT:g} per million "
            "input / output tokens. Steps marked Person were a person's answers.</p></section>")


def write_page(p, images=None):
    site, (data, events, seen) = case_site(p), case_data(p)
    page = pack.page(site, events, seen, p["letter"], images, data["fps"], data.get("cost"),
                     data.get("sam_full_requests"), case=case_section(p["out"]))
    (Path(p["out"]) / "index.html").write_text(page)


def sign_off(p, key):
    """The head of the school approved the letter: Muse Image draws the fix and the page is written. No agent turn."""
    photo, images = Path(p["out"]) / "street.jpg", None
    if photo.exists() and key:
        try:
            images = (photo.name, pack.draw_fix(photo, p["letter"]["image_prompt"], key,
                                                Path(p["out"]) / "street-fixed.jpg").name)
        except (OSError, ValueError, http.client.HTTPException, subprocess.CalledProcessError) as err:
            print(f"fix image failed, the page has the letter only: {err}", file=sys.stderr)
    p["status"] = "done"
    save(p, {"person": "approve", "summary": "The head of the school approved the letter."})
    write_page(p, images)


def tape_metres(text):
    match = TAPE.search(text)
    metres = float(match[1]) / (100 if match and match[2] else 1) if match else 0
    if metres <= 0:
        raise SystemExit(f"answer with the taped length, e.g. \"7.2 m\", not {text!r}")
    return metres


def person_step(p, key, answer=None, approve=False, notes=None):
    """Apply what a person did since the case stopped: the message for the model, or None when no turn follows."""
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
            return sign_off(p, key)
        save(p, {"person": "reject", "summary": f"The head of the school sent the letter back: {notes}"})
        return f"The head of the school sent the letter back with these notes: {notes}. Revise it with submit_letter."
    if status == "needs_input":
        raise SystemExit(f"waiting for a person: {open_requests[-1]['question']} "
                         f"Reply with --answer {open_requests[-1]['id']} \"...\"")
    if status in ("needs_review", "done", "over_budget"):
        raise SystemExit({"needs_review": "the letter waits for --approve or --reject --notes \"...\"",
                          "done": "this case is done; the page is index.html",
                          "over_budget": f"this case reached the ${MAX_USD:.2f} cap"}[status])
    return ("You have more turns. Continue." if p["turn"] else
            f"Work the case for the crossing \"{case_site(p).get('name', '')}\" and file the letter.")


def work(video, site, out_dir, key, answer=None, approve=False, notes=None):
    """Start or resume the case in out_dir/case; returns its status."""
    case_dir = Path(out_dir) / "case"
    case_dir.mkdir(parents=True, exist_ok=True)
    saved = case_dir / "progress.json"
    p = json.loads(saved.read_text()) if saved.exists() else {
        "video": str(Path(video).resolve()), "site": str(Path(site).resolve()), "out": str(out_dir), "status": "new",
        "turn": 0, "usd": 0.0, "messages": [], "requests": [], "tape_m": None, "refusals": 0, "letter": None}
    if p["video"] != str(Path(video).resolve()):
        raise SystemExit(f"{case_dir} is the case of {p['video']}; pass a new --out folder")
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
    parser.add_argument("--approve", action="store_true", help="sign the letter off")
    parser.add_argument("--reject", action="store_true", help="send the letter back; needs --notes")
    parser.add_argument("--notes", help="what to change, with --reject")
    args = parser.parse_args()
    if args.reject != (args.notes is not None):
        parser.error("--reject and --notes go together")
    out_dir = Path(args.out or Path("out") / Path(args.video).stem)
    status = work(args.video, args.site, out_dir, sam.load_api_key(), args.answer, args.approve, args.notes)
    print(f"case {status}: {out_dir / 'case' / 'progress.json'}")


if __name__ == "__main__":
    main()
