"""Evidence pack: one page a school can send to the road authority. Muse Spark picks the fix and writes the
letter from the measured events only; Muse Image draws that fix onto the real street.

Run after analyze.py: python3 pack.py OUT_DIR SITE.json
Writes OUT_DIR/index.html next to the clips (open it in a browser), and OUT_DIR/share/: the page and only the files it
shows, the one folder to publish, with their SHA256SUMS. The letter is kept in OUT_DIR/plan.json, so a re-run pays
nothing; --notes FILE revises it, and --approved-by NAME --school SCHOOL signs it (OUT_DIR/signoff.json).
python3 pack.py --verify FOLDER checks a shared folder: MATCH, CHANGED or MISSING per file.
"""
import argparse
import base64
import datetime
import difflib
import hashlib
import html
import http.client
import json
import math
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.request
import uuid
from pathlib import Path

import ailabel
import crowd
import fixband
import openweights
import overlay
import pace
import render
import review
import roadmap
import road
import sam
import seal

IMAGE_EDIT_URL = "https://api.meta.ai/v1/images/edits"
IMAGE_MODEL = "muse-image-1.0"
TIMEOUT_S = 300
SHOWN_EVENTS = 5
MIN_RATE_MINUTES = 15  # shortest video scaled to hourly rates (MUTCD Warrant 4 counts 15-minute periods)
ALPHA = 0.05      # exact two-sided 95% ranges
BISECTIONS = 50   # halvings to find a range's end: 1e-15 of the span, and a share never rounds up to exactly 1
SCHOOL_YEAR = ("school_days", "dismissal_minutes")  # optional site keys: the "if every dismissal" line needs both
LETTER_URL = os.environ.get("LETTER_MODEL_URL", "")  # an OpenAI-compatible server, e.g. llama-server with Muse
LETTER_MODEL = os.environ.get("LETTER_MODEL", "Muse Glimmer 30B")  # its API model id, shown as openweights.name()
LETTER_KEY = os.environ.get("LETTER_MODEL_KEY", "")  # Bearer token for the letter server (Fireworks: FIREWORKS_API_KEY)
JUDGE_URL = os.environ.get("JUDGE_MODEL_URL", "")  # an OpenAI-compatible server whose model also judges the letter
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", LETTER_MODEL)  # the judge server's API model id
JUDGE_KEY = os.environ.get("JUDGE_MODEL_KEY", "")  # Bearer token for the judge server only (Fireworks: as above)


def writer_label(url, model=LETTER_MODEL):
    """Who runs at `url`, the letter's writer or its open-weights judge (openweights.label), or Muse Spark."""
    return openweights.label(url, model) if url else "Muse Spark"


WRITER = writer_label(LETTER_URL)
LETTER_HOST = os.environ.get("LETTER_MODEL_HOST", "")  # where it ran, e.g. "Kaggle 2 x T4" (the notebook reads nvidia-smi)
PROVENANCE = "letter-provenance.json"  # beside plan.json: what an open-weights server ran, measured; never a key
RUN_KEYS = ("request_id", "usage", "wall_s", "timings", "response_format")  # openweights.reply's record
JUDGE = "Muse Spark (a separate reviewer)"
JUDGE_PROMPT = """You review a letter before a school sends it to its road authority. MEASUREMENTS are the only facts.
List every problem: a claim or number the measurements do not support; a number above one written in words, not in
digits; saying a standard or warrant is met; a death risk stated for a child; blaming a named person. Tone, wording
and the choice of fix are not problems.
Reply JSON only: {{"problems": ["<one short sentence each>"]}}, with [] if there are none.

MEASUREMENTS:
{facts}

LETTER:
{letter}"""
PROBLEMS_SCHEMA = {"type": "object", "properties": {"problems": {"type": "array", "items": {"type": "string"}}},
                   "required": ["problems"], "additionalProperties": False}  # the judge's reply, for a JUDGE_MODEL_URL server
LETTER_TRIES = 3     # Spark gets this many tries at a letter whose every number was measured
NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")  # 1,200 is one number
WORDS = ("two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
         "eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundreds?|thousands?|dozens?")
# a number in words, which code cannot check: "one" is too common to flag, and a two-wheeler is a vehicle
NUMBER_WORD = re.compile(rf"\b(?:{WORDS})(?:-(?:{WORDS}))?\b(?![- ]wheel)", re.I)
MPH = re.compile(rf"(?:(?:{NUMBER.pattern})\s?)?(?<![a-z])(?:mph|miles (?:per|an) hour)\b", re.I)  # measured in km/h
# a number with the unit of an event's speed, PET or death risk ("s" never matches "12 schools")
WITH_UNIT = re.compile(rf"({NUMBER.pattern})\s?(km/h|kmph|s(?:ec(?:ond)?s?)?|%|per ?cent)(?![\w/])", re.I)
UNIT_FIELD = {"k": "vehicle_kmh", "s": "pet_s", "%": "death_risk_pct", "p": "death_risk_pct"}  # unit's 1st letter
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")
SHOWN_FILE = re.compile(r'\bsrc="([^"#?]+)')  # a file the page shows (a clip or a picture), without #t=...
UNSHAREABLE = re.compile(r"clip\.mp4|person-.*\.jpg")  # the unblurred video and the unblurred crops Spark saw
PLAN_KEYS = ("fix", "why", "image_prompt", "letter")
JSON_ESCAPE = r'\\["\\/bfnrt]'  # an escape inside a JSON string, but never \u: "\u0032" is a hidden 2
LETTER_PROMPT = """You help a school ask its road authority to make the crossing outside it safer.
Below are measurements from a video of the crossing, made by Crossing Watch (SAM tracking, road-plane geometry,
post-encroachment time). Use ONLY these facts; never invent numbers, names, places or dates.
Write every number in digits, exactly as given (speeds in km/h), and never put one near-miss's speed in a sentence
with another near-miss's time gap.
Death-risk figures are for adults hit by a car front: never state a death risk for a child.
From the engineering lines, mention at most PV² and the share of time in gaps, briefly, with their main caveat;
never say a standard is met. If desire_lines is given, you may say where people crossed and quote its IRC:103-2012 words.

{facts}

Reply with JSON only:
{{"fix": "<one specific physical fix, e.g. raised zebra crossing, speed table, 20 km/h zone with signs>",
  "why": "<one sentence linking the fix to the measurements>",
  "image_prompt": "<an instruction to edit a photo of this street so it shows the fix; keep people and buildings unchanged>",
  "letter": "<a short formal letter in {language} from the head of the school to the road authority: what was measured,
             the worst near-misses, the requested fix, and an offer to share the video. Use [School name] and [Date]
             as placeholders.>"}}"""
# --notes: appended to LETTER_PROMPT with the letter being revised (Meta's legal-agent workshop: "Reject with notes")
REVISE = """

The head of the school read your letter below and wrote the notes under it. Reply with the same JSON, the letter
revised: change only the sentences the notes ask for and keep every other sentence word for word. The notes are stated
by the principal, not measured: anything taken from them is the school's own statement, never a measurement.

YOUR LETTER:
{letter}

NOTES:
{notes}"""
# the principal's notes as both letter checks read them, after the measurements: the judge must neither reject the
# school's own facts nor take them as measured
STATED = "\n\nSTATED BY THE PRINCIPAL, NOT MEASURED (a letter may give these as the school's own statements):\n"
SIGNOFF_KEYS = ("approved_by", "school", "date", "letter_sha256")  # signoff.json
FILED_KEYS = ("to", "channel", "date", "reference")  # the site's "submitted" record, once the pack is filed
TCT_TOOLKIT = "https://www.childhealthinitiative.org/media/v5bntgmp/tct-toolkit__one-pager_final_508_updated.pdf"
PRINTED_CARDS = 3  # on paper only the worst 3 near-misses, so the letter's own sheet comes soon
PYRAMID_WIDTHS = (20, 45, 70, 100)  # % of its column, tip to base: not to scale, the labels give the counts
# Muse Image only: IRC 103-2022 as the Supreme Court quotes it (order para 21 and its footnote 1). Never in
# LETTER_PROMPT, where 4, 10 and 20 would count as measured numbers.
RAISED_SPEC = ("Draw the crossing raised to the level of the footpath and 4 m wide, with a speed hump 10-20 m before it "
               "on each approach.")
RAISED = re.compile(r"raised|\btable", re.I)  # fixes RAISED_SPEC fits: raised zebra, tabletop crossing, speed table
ORDER_PDF = "https://www.livelaw.in/pdf_upload/2037620122025-10-07-624635.pdf"  # the signed order, 41 pages
ORDER = ("Supreme Court of India, S. Rajaseekaran v. Union of India, Writ Petition (Civil) No. 295 of 2012, "
         "reportable order of 7 October 2025, 2025 INSC 1189")
# (paragraph, PDF page, the Court's words verbatim): written by code, so no model ever writes a paragraph number
SCHOOL_ZONES = ("35.5", 33, "In school zones and other vulnerable corridors, authorities shall systematically identify "
                "high-risk stretches using accident data, and implement context-specific measures such as raised "
                "crossings, zebra markings, traffic calming features, and deployment of trained crossing guards.")
SURVEY = ("35.6", 34, "We, therefore, direct the road owning agencies in the 50 cities mentioned in Annexure 46 of the "
          "Report on Road Accidents, 2023 and the NHAI to draw up an action plan and start phase-wise survey to assess "
          "the requirement of additional pedestrian crossing facilities.")
GRIEVANCE = ("35.11", 37, "State Governments/Municipal Authorities/NHAI are directed to create an online grievance "
             "redressal mechanism regarding footpaths which would include complaints of encroachments on footpaths, "
             "maintenance of footpaths and also suggestions for pedestrian crossing.")
LEGAL_NOTE = ("Paragraph 35.5 asks authorities to identify high-risk stretches using accident data. The near-misses "
              "measured here are not accidents: they are offered as further evidence about this crossing, alongside "
              "that data. Where the road authority has set up the online mechanism of paragraph 35.11, this pack can "
              "be filed there as a suggestion for a pedestrian crossing.")
# the 50 million-plus cities of Annexure 46 in MoRTH's Road Accidents in India 2023 (paragraph 35.6 binds them), and
# common other names. Exact names only: a misspelt city loses paragraph 35.6, it never gains it
ANNEXURE_46 = {
    "agra", "ahmedabad", "allahabad", "prayagraj", "amritsar", "asansol durgapur", "asansol", "durgapur", "aurangabad",
    "bengaluru", "bhopal", "chandigarh", "coimbatore", "chennai", "delhi", "dhanbad", "faridabad", "ghaziabad",
    "gwalior", "hyderabad", "indore", "jabalpur", "jaipur", "jamshedpur", "jodhpur", "kannur", "kanpur", "kozhikode",
    "kochi", "kolkata", "kollam", "kota", "lucknow", "ludhiana", "madurai", "malappuram", "meerut", "mumbai", "nagpur",
    "nashik", "patna", "pune", "raipur", "rajkot", "srinagar", "surat", "thiruvananthapuram", "thrissur",
    "tiruchirappalli", "vadodara", "varanasi", "vijayawada", "visakhapatnam",
    "bangalore", "bombay", "calcutta", "madras", "cochin", "calicut", "trivandrum", "trichy", "baroda", "vizag",
    "new delhi"}


def confirmed(events):
    """Events whose track Spark did not reject as 'not a person' in any reviewed event (unreviewed ones stay,
    marked as such): one rejected pole must not come back through its unreviewed pairings with other vehicles."""
    rejected = {e["person"] for e in events if (e.get("review") or {}).get("is_person") is False}
    return [e for e in events if e["person"] not in rejected]


def real_crossers(events, seen):
    """exposure without the crossers Spark rejected as 'not a person', so the headline's n holds the same people as
    its k (a rider or a moved pole must not count as a crossing nobody was hit in). By person, not piece: one with
    any piece left in confirmed(events) stays."""
    if not seen.get("crossers"):
        return seen
    kept = {e["person"].split("/")[0] for e in confirmed(events)}
    rejected = {e["person"].split("/")[0] for e in events if (e.get("review") or {}).get("is_person") is False} - kept
    return {**seen, "crossers": [c for c in seen["crossers"] if c not in rejected]}


def serious(events):
    return [e for e in events if e.get("tier", "serious") == "serious"]


def facts(site, events, seen, paths=None):
    """The measurements a letter may quote, as JSON. Arrays (paths, spans, replays) never enter: they are not facts
    for a letter, and their many numbers would let almost any number in a letter pass the measured-number check.
    The desire lines (`paths`) enter only as roadmap.desire_lines()' counts."""
    worst, lines, desire = events[:SHOWN_EVENTS], headline(events, seen, site), roadmap.desire_lines(paths, site)
    return json.dumps({
        **({"headline": " ".join(lines)} if lines else {}),
        "site": site.get("name", ""), "observed": {k: v for k, v in seen.items() if not isinstance(v, (list, tuple, set))},
        "serious_near_misses": len(serious(events)), "close_passes": len(events) - len(serious(events)),
        **road.first_counts(events),
        "definition": f"serious: pedestrian and moving vehicle on the same spot less than {road.PET_MAX_S} s apart; "
                      f"close pass: {road.PET_MAX_S}-{road.CLOSE_PASS_S} s",
        "worst": [{"tier": e.get("tier", "serious"), "pet_s": e["pet_s"], "vehicle": e["vehicle"].split("#")[0], "vehicle_kmh": e["vehicle_kmh"],
                   "adult_death_risk_if_hit_pct": e["death_risk_pct"], "at_20_kmh_limit": e["with_limit"]["20"],
                   "road_user": review.unconfirmed_rider(e.get("review"))
                   or (e.get("review") or {}).get("road_user", "not reviewed")} for e in worst],
        "risk_source": "Rosén & Sander 2009, adults 15+, car fronts",
        "engineering": engineering_lines(seen, None),
        **({"desire_lines": " ".join(desire)} if desire else {}),
    }, indent=1, ensure_ascii=False)  # \u escapes would add digits the number check counts as measured


def watched_minutes(seen):
    """Minutes of video, exact from duration_s when there (minutes is rounded to 0.1)."""
    return seen["duration_s"] / 60 if seen.get("duration_s") else seen.get("minutes") or 0


def falling_root(f, hi):
    """Where f, positive near 0 and falling, crosses 0 in [0, hi] (hi when it never does)."""
    lo = 0.0
    for _ in range(BISECTIONS):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


def exact_range(cdf, k, hi):
    """Exact two-sided 95% range for a count seen k times; cdf(j, x) = P(count <= j), falling as x grows."""
    upper = falling_root(lambda x: cdf(k, x) - ALPHA / 2, hi)
    lower = falling_root(lambda x: cdf(k - 1, x) - (1 - ALPHA / 2), hi) if k else 0.0
    return lower, upper


def poisson_range(k):
    """Garwood's exact 95% range for the mean of a count seen k times: 0 gives 0 to 3.69, so 0 never reads as safe."""
    cdf = lambda j, mu: sum(math.exp(i * math.log(mu) - mu - math.lgamma(i + 1)) for i in range(j + 1))
    return exact_range(cdf, k, 10 * k + 10)


def share_range(k, n):
    """Clopper-Pearson's exact 95% range for a share seen k times in n."""
    cdf = lambda j, p: sum(math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p)
                                    + (n - i) * math.log1p(-p)) for i in range(j + 1))
    return exact_range(cdf, k, 1.0)


def people_hit(events, crossers):
    """Distinct people who crossed among these events' pedestrians: one split into pieces, or passed by several
    vehicles, counts once; one exposure never counted as crossing does not count."""
    return len({e["person"].split("/")[0] for e in events} & crossers)


def headline(events, seen, site):
    """The one number, as natural frequencies (Gigerenzer & Hoffrage 1995): k of the n people who crossed had a moving
    vehicle through their spot within CLOSE_PASS_S, and within PET_MAX_S, with exact 95% ranges. Lines; none without
    exposure's crosser list (an older events.json), the only way to keep k inside n."""
    if not seen.get("crossers"):
        return []
    crossers = set(seen["crossers"])
    n, tiers = len(crossers), [(people_hit(events, crossers), road.CLOSE_PASS_S),
                               (people_hit(serious(events), crossers), road.PET_MAX_S)]
    one_in = lambda k: f" (1 in {round(n / k, 0 if n >= 10 * k else 1):g})" if k else ""
    (k3, s3), (k15, s15) = tiers
    shares = " and ".join(f"{100 * lo:.1f}-{100 * hi:.1f}%" for lo, hi in (share_range(k, n) for k, _ in tiers))
    counts = " and ".join(f"{lo:.1f}-{hi:.1f}" for lo, hi in (poisson_range(k) for k, _ in tiers))
    lines = [f"{k3} of {n} crossings{one_in(k3)} had a moving vehicle through the same spot within {s3:g} s of the "
             f"person; {k15} of {n}{one_in(k15)} within {s15:g} s.",
             f"Exact 95% ranges, if this recording is typical: {shares} of crossings (Clopper-Pearson); {counts} people "
             f"in a recording this long (Poisson)."]
    days, length = (site.get(key) for key in SCHOOL_YEAR)
    minutes = watched_minutes(seen)
    if all(isinstance(v, (int, float)) and v > 0 for v in (days, length)) and minutes >= MIN_RATE_MINUTES:
        scaled = lambda count: f"{float(f'{count * length / minutes * days:.2g}'):,.0f}"  # 2 significant figures
        # 0 seen is never 0 a year: Poisson's upper bound, scaled the same way
        per_year = lambda k: f"about {scaled(k)}" if k else f"up to {scaled(poisson_range(0)[1])}"
        lines.append(f"If every dismissal is like this one: {per_year(k3)} crossings a school year with a moving "
                     f"vehicle through the same spot within {s3:g} s, {per_year(k15)} within {s15:g} s ({days:g} school "
                     f"days, {length:g}-minute dismissals).")
    return lines



def engineering_lines(seen, cost):
    """The numbers road engineers already use, from the same tracks: PV^2 (IRC:103-2012) and gaps in traffic
    (UK Traffic Signs Manual ch. 6), plus what the tracking cost. Rates from a short video are scaled, and say so."""
    minutes = watched_minutes(seen)
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
                     f"in our drone test). IRC:103-2012 cl. 6.7.4.1.2: a controlled crossing may be "
                     f"warranted above {road.PV2_UNDIVIDED / 1e8:g} x 10^8 on an undivided road, "
                     f"{road.PV2_DIVIDED / 1e8:g} x 10^8 on a divided road (the Union has told the Supreme Court "
                     f"that a Second Revision, IRC 103-2022, exists).")
    if "gaps_6s" in seen:
        lines.append(f"{seen.get('gap_6s_share_pct', '?')}% of the time was inside gaps of {road.GAP_ADULT_S:g} s or "
                     f"more with no moving vehicle where people crossed: {seen['gaps_6s']} "
                     f"gap{'' if seen['gaps_6s'] == 1 else 's'}, {seen['gaps_12s']} of them {road.GAP_SLOW_S:g} s or "
                     f"more, longest {seen['longest_gap_s']} s (the first and last are cut short by the video). "
                     f"UK Traffic Signs Manual ch. 6 (13.5.2): 4-6 s is an "
                     f"acceptable gap at urban speeds; other groups, such as children, may need 10-12 s or longer.")
    if cost and cost.get("sam_usd") is not None:
        images = f" (about ${cost['image_usd']:.2f} of it image detection)" if cost.get("image_usd") else ""
        lines.append(f"SAM cost for this pack: about ${cost['sam_usd']:.2f} at Meta's list prices{images}, so about "
                     f"${cost['sam_usd'] * 60 / minutes:.2f} per hour of footage.")
    return lines


def engineering(seen, cost):
    lines = engineering_lines(seen, cost)
    if not lines:
        return ""
    items = "".join(f"<li>{html.escape(line)}</li>" for line in lines)
    return f"<section><h2>Numbers road engineers use</h2><ul>{items}</ul></section>"


def limit_note(full):
    """Say so when SAM's per-request object limit was reached: then the counts are a minimum. A third item holds
    analyze's auto-mode notes, for concepts that filled it and were detected frame by frame instead."""
    notes = full[2] if full and len(full) > 2 and full[2] else []
    switched = (f'<p class="note">SAM video tracking keeps at most {sam.MAX_OBJECTS} objects per request. '
                f'{html.escape("; ".join(notes))}.</p>' if notes else "")
    if not full or not full[0]:
        return switched
    return switched + (f'<p class="note">In {full[0]} of {full[1]} tracking requests SAM reached its {sam.MAX_OBJECTS}-object '
                       "limit, so some people or vehicles were not tracked: counts and near-misses here are a minimum.</p>")


def privacy_note(privacy):
    """The page's count of blurred heads, when analyze had SAM image search find the people a full video request
    for people missed on the published frames."""
    if not privacy:
        return ""
    counts = html.escape(f"up to {privacy['heads_tracked']} heads a frame blurred from tracks + up to "
                         f"{privacy['heads_found']} found by SAM image search")
    return (f'<p class="note">Faces in the clips and the street photo: {counts} (a SAM video request for people was '
            "full, so the published clips were searched image by image every 0.2 s, with boxes filled in between).</p>")


def unmeasured(text, facts_text):
    """Numbers in `text` that appear nowhere in the measured facts, then numbers in words and speeds in mph, which
    code cannot check against them: a letter to an authority must not invent any."""
    value = lambda n: float(n.replace(",", ""))
    known = {value(n) for n in NUMBER.findall(facts_text)}
    unchecked = dict.fromkeys(m[0] for pattern in (NUMBER_WORD, MPH) for m in pattern.finditer(text))
    return sorted({n for n in NUMBER.findall(text) if value(n) not in known}, key=value) + list(unchecked)


def owners(match, events):
    """(field, card numbers) of a WITH_UNIT match: the shown events whose speed, PET or death risk it equals."""
    field = UNIT_FIELD[match[2][0].lower()]
    return field, [i for i, e in enumerate(events, 1) if e.get(field) == float(match[1].replace(",", ""))]


def mixed(letter, worst):
    """Sentences that put one near-miss's speed beside another's PET ("a car at 38 km/h passed 0.2 s from a child"
    with 38 from #1 and 0.2 from #3). Only numbers that are some shown event's speed or PET count."""
    out = []
    for sentence in SENTENCE.split(letter):
        found = {"vehicle_kmh": [], "pet_s": []}
        for match in WITH_UNIT.finditer(sentence):
            field, cards = owners(match, worst)
            if cards and field in found:
                found[field].append(set(cards))
        speeds, pets = found.values()
        # ponytail: only a sentence with one speed and one PET is paired; a list or a range ("0.0 s to 0.1 s at
        # 11.3 km/h to 12.8 km/h", whose ends are not one event) is left to the judge
        if len(speeds) == len(pets) == 1 and not speeds[0] & pets[0]:
            out.append(sentence.strip())
    return out


def retry_note(bad, crossed, problems):
    """Why the previous letter goes back, for the next try."""
    reasons = ([f"Your previous letter used numbers that are not in the measurements: {', '.join(bad)}. Use only "
                "numbers given above, written in digits, with speeds in km/h."] if bad else [])
    reasons += [f'Your previous letter put one near-miss\'s speed beside another near-miss\'s time gap: "{s}". Keep '
                "each near-miss's numbers together." for s in crossed]
    reasons += ([f"A reviewer found claims in your previous letter that the measurements do not support: "
                 f"{' '.join(problems)} Fix them."] if problems else [])
    return "\n\n" + " ".join(reasons)


def number_pattern(known):
    """A JSON-schema "pattern" for a string as written between its quotes: digits only as the numbers NUMBER finds in
    `known`, each followed by a non-digit (so "2" then "0.6" never reads "20.6"), and no \\u escapes. Digits of every
    script count, as in Python's \\d, so "۳0" (30) or ०-९ in a Hindi letter cannot slip through either."""
    zeros = [c for c in range(0x80, sys.maxunicode + 1) if unicodedata.decimal(chr(c), -1) == 0]  # each 0 starts 0-9
    non_ascii = "".join(f"\\U{a:08x}-\\U{b:08x}" for a, b in zip([0x80] + [z + 10 for z in zeros],
                                                                   [z - 1 for z in zeros] + [sys.maxunicode]) if a <= b)

    def char(banned=""):
        """One character of a JSON string that is no digit and not in `banned`. Positive classes only: llama.cpp's
        grammar rejects half a character whose range touches a negated class, so [^०-९] would also ban ि ी ु े ्."""
        ascii_ok = "".join(f"\\x{c:02x}" for c in range(0x20, 0x7f) if chr(c) not in f'0123456789"\\{banned}')
        return f"[{ascii_ok}]|[{non_ascii}]|{JSON_ESCAPE}"

    numbers = "|".join(re.escape(n) for n in sorted(set(NUMBER.findall(known))))
    if not numbers:
        return f"^({char()})*$"
    # No "<" straight after a number either: llama.cpp's grammar reads a special token such as "<s>" as its text, but
    # the reply leaves it out, so "2<s>0.6" would arrive as "20.6" (seen on a local llama-server)
    after = f"{char('.,<')}|[.,]({char('<')})"  # "27.3." ends a sentence; "27.3.5" is not 27.3
    return f"^({char()}|({numbers})({after}))*(({numbers})[.,]?)?$"


def plan_schema(known):
    """The plan as a JSON schema whose strings follow number_pattern(known). llama-server turns it into a grammar that
    still lets Glimmer think first; a bare GBNF "grammar" would bind from the first token and block its thinking."""
    text = {"type": "string", "pattern": number_pattern(known)}
    return {"type": "object", "properties": {k: text for k in PLAN_KEYS}, "required": list(PLAN_KEYS),
            "additionalProperties": False}


def ask_plan(prompt, measured, api_key, photo=None, tries=LETTER_TRIES, stated=()):
    """The model's fix and letter, verified before use in two layers (Meta's verifiable-agents workshop): code
    checks that every number was measured, then Muse Spark as a separate reviewer (LLM as judge) lists claims the
    measurements do not support. An invalid reply or either objection goes back with the reason; after the last try
    the letter is kept with what remains listed for a person to check before sending. Numbers are checked against
    `measured` only, never the prompt (its wording would let "3.1" from "SAM 3.1" pass), plus `stated`, the
    principal's notes, which both checks read labelled as stated by the principal, not measured. "tries" counts the
    model's replies, for the pack's receipt."""
    note, plan, bad, crossed, problems = "", None, [], [], []
    worst, measured = json.loads(measured).get("worst", []), measured + stated_text(stated)
    for attempt in range(tries):
        try:
            plan = model_plan(prompt + note, api_key, photo, measured)  # not the note: it quotes the bad numbers
        except ValueError as err:  # JSONDecodeError included
            if attempt == tries - 1 and plan is None:
                raise
            note = f"\n\nYour previous output was invalid: {str(err)[:200]}. Reply with the JSON object only."
            continue
        bad = unmeasured(plan["letter"] + " " + plan["why"], measured)
        crossed = mixed(plan["letter"], worst)
        judged = api_key or JUDGE_URL
        problems = [] if bad or crossed or not judged else judge_problems(plan["letter"], measured, api_key)
        if not bad and not crossed and not problems:
            return {**plan, "writer": WRITER, "tries": attempt + 1, **({"judged_by": judges(api_key)} if judged else {})}
        note = retry_note(bad, crossed, problems)
    return {**plan, "writer": WRITER, "tries": tries, "unmeasured": bad, "mixed": crossed, "unsupported": problems}


def stated_text(notes):
    """The principal's notes as the letter checks read them, after the measurements: labelled, never as measured."""
    return STATED + "\n\n".join(notes) if notes else ""


def judges(api_key):
    """The judges that run, by name: Muse Spark with a key, the JUDGE_MODEL_URL model with that URL."""
    return " and ".join(([JUDGE] if api_key else []) + ([writer_label(JUDGE_URL, JUDGE_MODEL)] if JUDGE_URL else []))


def judge_problems(letter, measured, api_key):
    """Each judge, Muse Spark with a key and the JUDGE_MODEL_URL model with that URL, separate from the writer's call,
    lists the letter's unsupported claims ([] if none). A reply it cannot read counts as one problem, so a broken judge
    never passes a letter silently."""
    prompt = JUDGE_PROMPT.format(facts=measured, letter=letter)
    replies = (([spark_reply(prompt, None, api_key)] if api_key else [])
               + ([open_model_reply(prompt, None, PROBLEMS_SCHEMA, judge=True)[0]] if JUDGE_URL else []))
    found = [read_problems(text) for text in replies]
    return [p for problems in found for p in (["The reviewer's reply could not be read."] if problems is None else problems)]


def read_problems(text):
    match = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(match[0]) if match else None
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("problems"), list):
        return None
    return [str(p)[:300] for p in data["problems"] if isinstance(p, str) and p.strip()]


def model_plan(prompt, api_key, photo=None, known=None):
    """One reply from the letter model, Muse Spark or (with LETTER_MODEL_URL) an open-weights model, parsed into
    the plan. The blurred street photo, when there is one, lets the model see the street it is fixing. An
    open-weights server can write digits only as numbers in `known` (default: the prompt)."""
    image = "data:image/jpeg;base64," + base64.b64encode(photo.read_bytes()).decode() if photo else None
    text, server = (open_model_reply(prompt, image, plan_schema(known or prompt)) if LETTER_URL
                    else (spark_reply(prompt, image, api_key), {}))
    match = re.search(r"\{.*\}", text, re.S)
    plan = json.loads(match[0], strict=False) if match else {}  # a letter may hold raw newlines
    if not isinstance(plan, dict) or not all(isinstance(plan.get(k), str) and plan[k].strip() for k in PLAN_KEYS):
        raise ValueError(f"the plan is incomplete: {text[:200]!r}")
    return {**plan, **server}


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


def open_model_reply(prompt, image, schema, judge=False):
    """Chat completion from the letter's OpenAI-compatible server or, with `judge`, the JUDGE_MODEL_URL one, each read
    at call time with its own model id and key (a key never crosses servers), through openweights.reply: the text and
    its run record, kept in plan.json."""
    url, model, key = (JUDGE_URL, JUDGE_MODEL, JUDGE_KEY) if judge else (LETTER_URL, LETTER_MODEL, LETTER_KEY)
    content = [{"type": "text", "text": prompt}] + ([{"type": "image_url", "image_url": {"url": image}}] if image else [])
    return openweights.reply(url, model, openweights.server_key(url, key), content, schema)


def writer_note(plan):
    """Who wrote the fix and letter. An open-weights model's time is measured, never a guess: llama-server's own
    timings, else the wall time around the reply (Fireworks sends no timings)."""
    seconds = run_seconds(plan) if LETTER_URL else None
    if seconds is not None:
        host = LETTER_HOST or openweights.provider(LETTER_URL)
        return (f"{openweights.name(LETTER_MODEL)} wrote this in {seconds:.0f} s{f' on {host}' if host else ''} "
                "(open weights).")
    return f"Fix and letter written by {plan['writer']}." if plan.get("writer") else ""


def run_seconds(plan):
    timings, wall = plan.get("timings"), plan.get("wall_s")
    if isinstance(timings, dict) and all(isinstance(timings.get(k), (int, float)) for k in ("prompt_ms", "predicted_ms")):
        return (timings["prompt_ms"] + timings["predicted_ms"]) / 1000
    return wall if isinstance(wall, (int, float)) else None


def draw_fix(photo, instruction, api_key, out_path):
    """Muse Image edit of the real street photo, saved untouched as out_path (.webp): converting it would drop Meta's
    AI tag (IPTC trainedAlgorithmicMedia). Returns out_path."""
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
    out_path.write_bytes(base64.b64decode(data[0]["b64_json"]))
    return out_path


def frame0_replies(clip, concept):
    """The SAM replies analyze cached for the clip's first frame: the frame-by-frame one (crowd mode, auto mode after
    it switched, or analyze's search for the people a full video reply missed), then the video one (part0/ for long
    videos)."""
    folder = clip.parent / "part0" if (clip.parent / "part0").is_dir() else clip.parent
    return [f for f in (crowd.cache_dir(clip.parent, concept) / f"{0:06d}.sam.txt", sam.cache_path(folder, concept))
            if f.exists()]


def frame0_tracks(clip, concepts):
    """Every track in the first-frame replies of `concepts`."""
    return [t for c in concepts for f in frame0_replies(clip, c) for t in sam.parse(f.read_text()).values()]


def photo_people(clip, person_concept="person"):
    """Person tracks of the clip's first frame from every reply (frame0_replies): the heads the street photo blurs
    and the people the fix picture keeps real. Without a person reply, or with only a full video one, it raises
    rather than leave faces unblurred."""
    replies, people = frame0_replies(clip, person_concept), frame0_tracks(clip, [person_concept])
    if not replies:
        raise ValueError(f"no person tracks for {clip}; not showing an unblurred street photo")
    if replies[0].parent != crowd.cache_dir(clip.parent, person_concept) and len(people) >= sam.MAX_OBJECTS:
        raise ValueError(f"SAM's video reply for people in {clip} is full and frame 0 was not searched image by image "
                         "(run analyze.py on this folder again: it now searches frame 0 even with no near-misses); "
                         "not showing a street photo with unblurred faces")
    return people


def street_photo(clip, out_path, person_concept="person", vehicles=()):
    """First frame of the clip with every head (photo_people) and number plate blurred (it is shown on the page and
    sent to Muse Image); no photo rather than unblurred faces."""
    people = photo_people(clip, person_concept)
    size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", str(clip)], check=True, capture_output=True, text=True).stdout.strip()
    frame_size = tuple(int(v) for v in size.split(","))
    filters = ",".join(render.blur_filters(people, 0, 0, frame_size)
                       + render.plate_filters(frame0_tracks(clip, vehicles), 0, 0, frame_size)) or "null"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf", filters, "-frames:v", "1", str(out_path)],
                   check=True)
    return out_path


def event_card(i, e, fps, strip=""):
    """Card #i, linkable as #event-i; data-t is the second of its clip when the first of the two reached the spot.
    `strip` is overlay.strip()'s stopping strip for this card, if any."""
    verdict, at30, at20 = e.get("review") or {}, e["with_limit"]["30"], e["with_limit"]["20"]
    road_user = verdict.get("road_user", "pedestrian (not reviewed by Spark)")
    road_user = review.unconfirmed_rider(verdict) or ("pedestrian" if road_user == "unclear" else road_user)
    who = html.escape(("an " if road_user[0] in "aeiou" else "a ") + road_user)
    video = f'<video src="{html.escape(e["clip"])}" controls muted loop playsinline></video>' if e.get("clip") else ""
    moment_s = min(e["t_person_s"], e["t_vehicle_s"]) - render.window(e, fps)[0] / fps
    return f"""<article class="card" id="event-{i}" data-t="{moment_s:.2f}">{overlay.strobe(e)}{overlay.clip(video, e, strip)}
<h3>#{i} &middot; {html.escape(e.get("tier", "serious"))} &middot; {html.escape(e["vehicle"].split("#")[0])} at {e["vehicle_kmh"]} km/h, {e["pet_s"]:.1f} s from {who}</h3>
<table><tr><th></th><th>Impact speed if hit</th><th>Adult death risk</th></tr>
<tr><td>As driven</td><td>{e.get("impact_kmh", e["vehicle_kmh"])} km/h</td><td>{e["death_risk_pct"]}%</td></tr>
<tr><td>30 km/h limit</td><td>{at30["impact_kmh"]} km/h</td><td>{at30["death_risk_pct"]}%</td></tr>
<tr><td>20 km/h limit</td><td>{at20["impact_kmh"]} km/h</td><td>{at20["death_risk_pct"]}%</td></tr></table>
<p class="note">At {e["t_person_s"]:.1f} s in the video. Gap {e["gap_m"]} m. {html.escape(road.moment_note(e))} {html.escape(verdict.get("reason", ""))}
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



def map_section(events, site, ground=None, paths=None):
    """The map, drawn even with no near-miss: then it shows where people crossed (the desire lines)."""
    placed = any(e.get("where") for e in events)
    trails = (f" Faint blue: where each person crossed, a point every {road.DESIRE_STEP_S:g} s." if paths else "")
    near = (" Blue: the pedestrian, red: the vehicle, 2 s either side. Filled dots: serious near-misses; rings: close "
            "passes." if placed else "")
    under = (" Under it, the street photo seen from above: the road surface is to scale, standing objects lean, and "
             f"the {'dots' if placed else 'lines'} are measured positions." if ground else "")
    lines = roadmap.desire_lines(paths, site)  # the counts, then IRC:103-2012's words, shown as a note
    desire = "".join(f"<p>{html.escape(line)}</p>" for line in lines[:-1]) + "".join(
        f'<p class="note">{html.escape(line)}</p>' for line in lines[-1:])
    return (f"<section><h2>{'Where it happened' if placed else 'Where people crossed'}</h2>"
            f"{roadmap.svg(events, site['world_points'], SHOWN_EVENTS, ground, paths)}<p class=\"note\">Seen from "
            f"above, in metres on the road (grid every 5 m; dashed: the measured area).{trails}{near}{under}</p>"
            f"{desire}</section>")


def fix_section(plan, images):
    if not plan:
        return ""
    head = f"""<section><h2>Proposed fix: {html.escape(plan["fix"])}</h2><p>{html.escape(plan["why"])}</p>"""
    if not images:
        return head + "</section>"
    return head + f"""
<div class="pair"><figure><img src="{html.escape(images[0])}" alt="The street today"><figcaption>Today</figcaption></figure>
<figure><img src="{html.escape(images[1])}" alt="The street with the fix, drawn by Muse Image"><span class="ai-label">{ailabel.LABEL}</span>
<figcaption>AI-drawn proposal by Muse Image, not a photo</figcaption></figure></div></section>"""


def fix_instruction(plan):
    """Muse Image's instruction: the model's, plus the IRC size when the fix is a raised crossing."""
    return plan["image_prompt"] + (" " + RAISED_SPEC if RAISED.search(plan["fix"]) else "")


def in_india(site):
    return str(site.get("country", "")).upper() == "IN"


def legal_section(site):
    """For a site in India ("country": "IN"), why the authority can act: the Supreme Court's own sentences, each
    linked to its page of the order. Paragraph 35.6 only when the site's "city" is in Annexure 46."""
    if not in_india(site):
        return ""
    city = str(site.get("city", "")).strip()
    listed = city.casefold() in ANNEXURE_46
    quotes = "".join(f'<blockquote>“{html.escape(text)}”<cite><a href="{ORDER_PDF}#page={page}">Paragraph {para}, '
                     f"page {page}</a></cite></blockquote>"
                     for para, page, text in [SCHOOL_ZONES] + ([SURVEY] if listed else []) + [GRIEVANCE])
    annexure = (f'<p class="note">{html.escape(city)} is one of the 50 million-plus cities in Annexure 46 of MoRTH\'s '
                "Road Accidents in India 2023.</p>" if listed else "")
    return (f'<section><h2>Why the authority can act</h2>{quotes}{annexure}<p class="note">{html.escape(LEGAL_NOTE)}</p>'
            f'<p class="note">Source: {html.escape(ORDER)} (<a href="{ORDER_PDF}">PDF</a>).</p></section>')


def submitted(site):
    """The site's "submitted" record, {to, channel, date, reference} all filled in, or None until the pack is filed."""
    sent = site.get("submitted")
    if sent is None:
        return None
    if not (isinstance(sent, dict) and all(isinstance(sent.get(k), str) and sent[k].strip() for k in FILED_KEYS)):
        raise ValueError(f'the site\'s "submitted" needs {", ".join(FILED_KEYS)}, each filled in')
    return sent


def filed_line(site):
    """Under the title once the pack is filed. Only "filed, reference X": whether anything is approved or fixed is
    the authority's to say, and no resolution date is promised."""
    sent = submitted(site)
    if not sent:
        return ""
    to, channel, date, reference = (html.escape(sent[k].strip()) for k in FILED_KEYS)
    return f'<p class="filed">Filed with {to} on {channel}, {date}: reference {reference}.</p>'


def tct_section():
    """Where this pack sits in the school-zone Traffic Conflict Technique toolkit, and the step left after the fix."""
    return ('<section><h2>Where this fits in a conflict study</h2><p class="note">This pack covers steps 5-7 (baseline '
            f'counts, pre-intervention conflicts, analysis) of the CDC/FIA school-zone <a href="{TCT_TOOLKIT}">Traffic '
            "Conflict Technique toolkit</a>, without the trained observers step 3 normally needs. Severity here is "
            "post-encroachment time and the measured speed, not the toolkit's observer severity scales, so the two do "
            "not compare one to one. Step 9 comes after the fix is in place: film the same dismissal from the same spot "
            "for as long, run this pack again and compare.</p></section>")


def pyramid(events, seen):
    """This crossing's safety pyramid (Laureshyn, Svensson & Hydén 2010), not to scale: the people who crossed at the
    base, those with a moving vehicle through their spot within CLOSE_PASS_S and within PET_MAX_S above them, and
    collisions at the tip, which nothing here measures: the exact 95% bound says how many even 0 would leave possible.
    The headline's own k and n, so none without its crosser list."""
    if not seen.get("crossers"):
        return ""
    crossers = set(seen["crossers"])
    n = len(crossers)
    tiers = [("tip", f"Collisions: not measured. Even 0 in {n} crossings would still allow up to "
                     f"{100 * share_range(0, n)[1]:.1f}% of crossings to end in one (exact 95% bound), so no recording "
                     "can show a crossing is safe."),
             ("serious", f"{people_hit(serious(events), crossers)} of {n} had a moving vehicle through their spot "
                         f"within {road.PET_MAX_S:g} s"),
             ("close", f"{people_hit(events, crossers)} of {n} within {road.CLOSE_PASS_S:g} s"),
             ("base", f"{n} people crossed")]
    rows = "".join(f'<i class="{kind}" style="width: {width}%"></i><span>{html.escape(text)}</span>'
                   for (kind, text), width in zip(tiers, PYRAMID_WIDTHS))
    return (f'<section><h2>The safety pyramid at this crossing</h2><div class="pyramid">{rows}</div><p class="note">Not '
            "to scale. Near-misses happen far more often than collisions, so they can be counted now, before anyone is "
            "hurt (the traffic-safety pyramid: Laureshyn, Svensson & Hydén 2010).</p></section>")


def receipt_line(data, plan, images):
    """What made this pack, said by code: the analysis run's wall-clock minutes and the SAM requests it sent (none:
    every reply came from cache), the people Muse Spark looked at, the moments Muse Wonder listened to, the letter's
    tries and the Muse Image picture. Counts only: dollars are for SAM alone, in the cost line."""
    run, events = data.get("run") or {}, data.get("events", [])
    sent = run.get("sam_requests")
    parts = ([f"the analysis ran {run['minutes']:g} minutes and " + (
        f"sent {sent} new SAM request{'' if sent == 1 else 's'}" if sent else
        "took every SAM reply from cache, so it paid nothing new")] if run else [])
    looked, heard = len({e["person"] for e in events if e.get("review")}), sum(e.get("heard") is not None for e in events)
    parts += [f"Muse Spark looked at {looked} {'person' if looked == 1 else 'people'}"] if looked else []
    parts += [f"Muse Wonder listened around {heard} near-miss{'' if heard == 1 else 'es'}"] if heard else []
    if plan and plan.get("tries"):
        parts.append(f"{plan.get('writer') or 'the model'} wrote the letter in {plan['tries']} "
                     f"tr{'y' if plan['tries'] == 1 else 'ies'}")
    parts += ["Muse Image drew 1 picture"] if images else []
    return f"Receipt: {'; '.join(parts)}. Dollar costs on this page are for SAM only." if parts else ""


def hash_line(source_sha256, site):
    """Where the hashes are that show a changed file: the original video's (from analyze.py) and SHA256SUMS in the
    shared folder; for a site in India, the evidence-law form that asks for them, which the school fills and signs."""
    video = (f"The original video's SHA-256 is <code>{html.escape(source_sha256)}</code>. " if source_sha256 else "")
    law = (" In India, Part A of the certificate for electronic evidence in the Schedule to the Bharatiya Sakshya "
           "Adhiniyam, 2023 (section 63(4)) asks for these hash values: the school fills and signs it."
           if in_india(site) else "")
    return (f'<p class="note">{video}{seal.SUMS} in the shared folder lists every shared file\'s SHA-256: '
            f"<code>shasum -a 256 -c {seal.SUMS}</code> or <code>python3 pack.py --verify FOLDER</code> says if any "
            f"changed.{html.escape(law)}</p>")


def linked(text, events):
    """`text` as HTML, each number with a unit that equals exactly one shown event's speed, PET or death risk linked
    to that event's card. The raw text is split first and each piece escaped: escaping first would let the number
    pattern match the 27 inside &#x27;."""
    out, end = [], 0
    for match in WITH_UNIT.finditer(text):
        cards = owners(match, events)[1]
        if len(cards) == 1:
            out += [html.escape(text[end:match.start()]), f'<a class="clip" href="#event-{cards[0]}" data-clip="'
                    f'{cards[0]}" title="Play clip {cards[0]}">{html.escape(match[0])}</a>']
            end = match.end()
    return "".join(out) + html.escape(text[end:])


def letter_section(plan, events=(), measured="", signoff=None):
    """The letter, editable in the browser, on its own printed sheet. A number that is one shown event's own links to
    its clip ("see clip N" when printed); an edit re-checks every number against `measured` (and the principal's
    notes) as it is typed. `signoff` (signoff.json) names who approved it while its sha256 still matches."""
    if not plan:
        return ""
    paragraphs = "".join(f"<p>{linked(p, events)}</p>" for p in plan["letter"].split("\n") if p.strip())
    check = "".join(f'<p class="note">Check before sending: {html.escape(text)}</p>' for text in (
        [f'these numbers are not in the measurements: {", ".join(plan["unmeasured"])}.'] if plan.get("unmeasured") else [])
        + [f"this sentence mixes two near-misses: {s}" for s in plan.get("mixed", [])]
        + [f"the reviewer says: {p}" for p in plan.get("unsupported", [])])
    sources = "the measurements" + (" and the principal's notes" if plan.get("notes") else "")
    checked = (f"Every number was checked against {sources} by code, and the claims by {plan['judged_by']}."
               if plan.get("judged_by") else f"Every number was checked against {sources} by code.")
    clean = not (plan.get("unmeasured") or plan.get("mixed") or plan.get("unsupported"))
    known = " ".join(sorted({n.replace(",", "") for n in NUMBER.findall(measured + stated_text(plan.get("notes")))}))
    writer = f'<p class="note">{html.escape(note)}</p>' if (note := writer_note(plan)) else ""
    return (f'<section class="letter-sheet"><h2>Letter to the road authority</h2>{writer}<div class="letter" '
            f'contenteditable="plaintext-only" spellcheck="false" role="textbox" aria-multiline="true" '
            f'aria-label="Letter, editable" data-measured="{known}">{paragraphs}</div>{check}<p class="note ok" id="letter-check"'
            f'{"" if clean else " hidden"}>{html.escape(checked) if clean else ""}</p>{disclosure(plan, signoff)}'
            f"{LETTER_SCRIPT}</section>")


# the same three checks as unmeasured(), re-run in the browser on every edit, and a linked number's click
LETTER_SCRIPT = """<script>{  // a block, so its names never clash with another script on the page
const letter = document.querySelector(".letter"), verdict = document.getElementById("letter-check");
const known = new Set(letter.dataset.measured.split(" ").filter(Boolean).map(Number));
const checks = [[new RegExp(%s, "g"), n => !known.has(Number(n.replaceAll(",", "")))],
                [new RegExp(%s, "gi"), () => true], [new RegExp(%s, "gi"), () => true]];
letter.addEventListener("input", () => {
  const ranges = [], bad = [], walk = document.createTreeWalker(letter, NodeFilter.SHOW_TEXT);
  for (let node; (node = walk.nextNode());)
    for (const [pattern, flagged] of checks)
      for (const m of node.data.matchAll(pattern)) if (flagged(m[0])) {
        const range = new Range();
        range.setStart(node, m.index); range.setEnd(node, m.index + m[0].length);
        ranges.push(range); bad.push(m[0]);
      }
  if (window.Highlight) CSS.highlights.set("unmeasured", new Highlight(...ranges));
  verdict.hidden = false;
  verdict.className = bad.length ? "note bad" : "note ok";
  verdict.textContent = "Edited here: numbers re-checked in your browser." +
    (bad.length ? " Not in the measurements: " + [...new Set(bad)].join(", ") + "." : "");
});
document.addEventListener("click", event => {
  const link = event.target.closest("a.clip"), card = link && document.querySelector(link.getAttribute("href"));
  if (!card) return;
  event.preventDefault();
  card.scrollIntoView({behavior: "smooth", block: "center"});
  const video = card.querySelector("video");
  if (video) { video.currentTime = Number(card.dataset.t); video.play(); }
});
}</script>""" % (json.dumps(NUMBER.pattern), json.dumps(NUMBER_WORD.pattern), json.dumps(MPH.pattern))


def disclosure(plan, signoff=None):
    """Written by code after both checks, never inside plan["letter"] (the number check would read it): the letter
    is an AI draft until a named person approves it, and Meta's AUP forbids passing outputs off as human-written.
    signoff.json fills in the blank only while its sha256 is still the letter's."""
    source = "the measurements in this pack" + (" and the principal's notes" if plan.get("notes") else "")
    signed = bool(signoff) and signoff["letter_sha256"] == sha256(plan["letter"])
    by = (f"{signoff['approved_by']}, {signoff['school']}, {signoff['date']} ({edits(plan)})" if signed
          else "____ (name, role, date)")
    stale = (f'<p class="note bad">Changed after sign-off by {html.escape(signoff["approved_by"])} on '
             f'{html.escape(signoff["date"])}, not signed.</p>' if signoff and not signed else "")
    return (f'{stale}<p class="disclosure">Drafted by {html.escape(plan.get("writer") or "an AI model")} from {source}. '
            f"Read and approved by: {html.escape(by)}.</p>")


def edits(plan):
    """How much the principal's notes changed the AI draft, by sentence (difflib): "1 of 12 sentences changed after
    the principal's notes". A sentence cut or added counts, out of the longer of the two letters."""
    if "draft_letter" not in plan:
        return "as drafted, no notes"
    draft, final = sentences(plan["draft_letter"]), sentences(plan["letter"])
    kept = sum(b.size for b in difflib.SequenceMatcher(None, draft, final, autojunk=False).get_matching_blocks())
    longer = max(len(draft), len(final))
    return f"{longer - kept} of {longer} sentences changed after the principal's notes"


def sentences(text):
    return [s.strip() for s in SENTENCE.split(text) if s.strip()]


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


STYLE = """
:root { --bg: #fafaf7; --ink: #1d1d1b; --muted: #66665f; --line: #deded6; --accent: #c0392b; --ok: #2e7d32; }
@media screen and (prefers-color-scheme: dark) { :root { --bg: #161614; --ink: #ececE6; --muted: #a3a39a; --line: #34342f; --accent: #ff6b5b; --ok: #7bd88f; } }
body { margin: 0 auto; max-width: 880px; padding: 24px 16px 64px; background: var(--bg); color: var(--ink);
       font: 16px/1.5 system-ui, sans-serif; }
h1 { font-size: 1.8rem; margin: 0 0 4px; } h2 { margin-top: 40px; } .muted, .note { color: var(--muted); }
.lead { font-size: 1.25rem; margin-bottom: 0; }
.stats { display: flex; gap: 24px; flex-wrap: wrap; margin: 20px 0; } .stats b { display: block; font-size: 2rem; color: var(--accent); }
.card { border-top: 1px solid var(--line); padding: 16px 0; } video, img { width: 100%; border-radius: 6px; }
table { border-collapse: collapse; width: 100%; } td, th { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--line); }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; } @media (max-width: 600px) { .pair { grid-template-columns: 1fr; } }
figure { margin: 0; position: relative; } .letter { border-left: 3px solid var(--line); padding-left: 16px; }
.ai-label { position: absolute; left: 8px; top: 8px; padding: 2px 8px; border-radius: 4px; background: #000c; color: #fff;
            font-size: 0.8rem; } .disclosure { border: 1px dashed var(--muted); padding: 8px 12px; }
blockquote { margin: 16px 0; padding-left: 16px; border-left: 3px solid var(--accent); }
cite { display: block; margin-top: 4px; font-style: normal; color: var(--muted); } a { color: inherit; }
.letter:focus { outline: 2px solid var(--line); outline-offset: 6px; } .note.ok { color: var(--ok); }
.note.bad { color: var(--accent); } ::highlight(unmeasured) { text-decoration: underline wavy #e5372a 2px; }
.filed { font-weight: 600; } code { overflow-wrap: anywhere; }
.pyramid { display: grid; grid-template-columns: minmax(96px, 35%) 1fr; gap: 6px 12px; align-items: center; }
.pyramid i { display: block; height: 28px; margin: 0 auto; background: var(--muted); print-color-adjust: exact; }
.pyramid i.base { background: var(--line); } .pyramid i.serious { background: var(--accent); }
.pyramid i.tip { box-sizing: border-box; background: none; border: 2px dashed var(--accent); }
@media print { a.clip { text-decoration: none; } a.clip::after { content: " (see clip " attr(data-clip) ")"; }
               .letter-sheet { break-before: page; break-after: page; } }
""" + (  # dark colours are for screens only (dark ink on white paper); on paper only the worst cards, so say so
    f"@media print {{ article.card:nth-of-type(n+{PRINTED_CARDS + 1}) {{ display: none; }} "
    + ", ".join(f'a.clip[data-clip="{i}"]::after' for i in range(PRINTED_CARDS + 1, SHOWN_EVENTS + 1))
    + ' { content: " (clip " attr(data-clip) ", not printed)"; } }\n')


def stats(events, seen, measured=True):
    """The count tiles. They always say how much was watched, so a quiet video never reads as "safe". Not `measured`
    (pace.warning), only that: its near-miss counts and speeds are not measurements."""
    n_serious, crossings = len(serious(events)), seen.get("crossings") or 0
    watched = [(crossings, "pedestrian crossings watched"), (seen.get("vehicles", "?"), "moving vehicles"),
               (seen.get("minutes", "?"), "minutes of video")]
    near = [(n_serious, f"serious near-misses (under {road.PET_MAX_S} s)"),
            (len(events) - n_serious, f"close passes ({road.PET_MAX_S}-{road.CLOSE_PASS_S} s)")]
    speed = [(seen["speed_85th_kmh"], "km/h, 85% of vehicles at or below")] if seen.get("speed_85th_kmh") else []
    tiles = [*near, *watched, *speed] if measured else watched
    return "".join(f"<div><b>{html.escape(str(v))}</b>{html.escape(label)}</div>" for v, label in tiles)


def lead(lines):
    """The headline under the title, its ranges and school-year line as notes."""
    return "".join(f'<p class="{"note" if i else "lead"}">{html.escape(line)}</p>' for i, line in enumerate(lines))


def banner(walking):
    """The warning that replaces the headline when people walk too fast or too slow here (pace.warning), else ""."""
    warning = pace.warning(walking)
    return (f'<p class="lead note bad" role="alert"><b>Not measurements.</b> {html.escape(warning)} No letter was '
            "asked for.</p>" if warning else "")


def page(site, events, seen, plan, images, fps, cost=None, full=None, privacy=None, signoff=None, receipt="",
         source_sha256=None, timeline=None, ground=None, paths=None, case="", walking=None):
    warning = banner(walking)  # then the headline, pyramid, engineering numbers and gap barcode are left out
    measured = "" if warning else (f"{pyramid(events, seen)}\n{engineering(seen, cost)}"
                                   f"{roadmap.gap_strip(timeline, events, SHOWN_EVENTS, full)}")
    moments = "Tracked moments, not measurements (see the warning above)" if warning else "Worst moments"
    cards = "\n".join(event_card(i + 1, e, fps, overlay.strip(e, site, events[:SHOWN_EVENTS]))
                      for i, e in enumerate(events[:SHOWN_EVENTS])) or (
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
<style>{STYLE}{roadmap.STYLE}{overlay.STYLE}</style></head><body>
<h1>Crossing Watch: near-miss evidence</h1>
<p class="muted">{html.escape(site.get("name", ""))}</p>{filed_line(site)}{warning or lead(headline(events, seen, site))}
<div class="stats">{stats(events, seen, not warning)}</div>{limit_note(full)}{privacy_note(privacy)}{measured}
{map_section(events, site, ground, paths)}<section><h2>{moments}</h2>{cards}</section>{fix_section(plan, images)}{fixband.figure(images)}{legal_section(site)}
{letter_section(plan, events[:SHOWN_EVENTS], facts(site, events, seen, paths), signoff)}{case}
{tct_section()}<section><h2>How this was measured</h2><p class="note">{html.escape(method)}</p>
{f'<p class="note">{html.escape(receipt)}</p>' if receipt else ""}{hash_line(source_sha256, site)}</section>{overlay.SCRIPT}</body></html>"""


def share(out_dir, page_html):
    """out_dir/share/: the page and only the files it shows, for the GitHub release. Never the unblurred video or
    the person crops, even if a page names one; the Muse Image .webp goes in untouched, AI tag and all."""
    folder = out_dir / "share"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    for name in {html.unescape(n) for n in SHOWN_FILE.findall(page_html)}:
        if Path(name).name == name and (out_dir / name).is_file() and not UNSHAREABLE.fullmatch(name):
            shutil.copyfile(out_dir / name, folder / name)
    (folder / "index.html").write_text(page_html)
    return folder


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

def read_json(path):
    """A JSON file an earlier run wrote, or None when it is missing or unreadable (said on stderr)."""
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as err:
        print(f"{path} unreadable, ignored: {err}", file=sys.stderr)
        return None


def saved_plan(out_dir, prompt):
    """plan.json when this same writer wrote it from this same prompt (the same measurements), else None: a re-run
    reuses the paid-for letter, and never one written from other measurements."""
    plan = read_json(out_dir / "plan.json")
    if isinstance(plan, dict) and plan.get("prompt_sha256") == sha256(prompt) and plan.get("writer") == WRITER:
        return plan
    if plan is not None:
        print("plan.json was written from other measurements or by another model: not reused", file=sys.stderr)
    return None


def new_plan(out_dir, prompt, measured, key, photo, revise=None, notes=""):
    """A new fix and letter, or `revise`'s letter revised by the principal's notes, saved to plan.json with the sha256
    of the prompt it came from. A revision also keeps every note so far (later checks read them as stated by the
    principal) and the first AI draft, which the sign-off counts changed sentences against."""
    stated = revise.get("notes", []) + [notes] if revise else []
    ask = prompt + REVISE.format(letter=revise["letter"], notes=notes) if revise else prompt
    plan = {**ask_plan(ask, measured, key, photo, stated=stated), "prompt_sha256": sha256(prompt)}
    if revise:
        plan = {**plan, "notes": stated, "draft_letter": revise.get("draft_letter", revise["letter"])}
    write_plan(out_dir, plan)
    return plan


def write_plan(out_dir, plan):
    """plan.json, the paid-for letter, and beside it when an open-weights server wrote it, PROVENANCE: the model id,
    host, request id, usage, wall seconds and the letter's sha256 (never the key)."""
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False))
    if LETTER_URL and "wall_s" in plan:
        record = {"model": LETTER_MODEL, "host": openweights.host(LETTER_URL), **{k: plan.get(k) for k in RUN_KEYS},
                  "tries": plan.get("tries"), "letter_sha256": sha256(plan["letter"])}
        (out_dir / PROVENANCE).write_text(json.dumps(record, indent=1))


def sign(out_dir, plan, approved_by, school):
    """signoff.json: who read and approved plan.json's letter, the day, and the sha256 of its exact text."""
    record = {"approved_by": approved_by, "school": school, "date": datetime.date.today().isoformat(),
              "letter_sha256": sha256(plan["letter"])}
    (out_dir / "signoff.json").write_text(json.dumps(record, indent=1, ensure_ascii=False))
    return record


def read_signoff(out_dir):
    """signoff.json, or None (the letter then shows as unsigned) when there is none or it is not a sign-off."""
    record = read_json(out_dir / "signoff.json")
    if record is None or isinstance(record, dict) and all(isinstance(record.get(k), str) for k in SIGNOFF_KEYS):
        return record
    print(f"signoff.json lacks {', '.join(SIGNOFF_KEYS)}: the letter shows as unsigned", file=sys.stderr)
    return None


def parse_args():
    """The command line, the notes' text and (approved_by, school), refusing flags that cannot go together."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", nargs="?")
    parser.add_argument("site", nargs="?")
    parser.add_argument("--verify", metavar="FOLDER", help=f"check a shared folder against its {seal.SUMS}: MATCH, "
                        "CHANGED or MISSING per file (alone, without out_dir and site)")
    parser.add_argument("--notes", metavar="FILE", help="the principal's notes on plan.json's letter: only the "
                        "sentences they ask about change")
    parser.add_argument("--approved-by", default="", metavar="NAME",
                        help='who read and approved plan.json\'s letter, e.g. "A. Rao, Principal" (with --school)')
    parser.add_argument("--school", default="", help="the school that sends the letter")
    args = parser.parse_args()
    if args.verify and (args.out_dir or args.notes or args.approved_by or args.school):
        parser.error("--verify FOLDER goes alone")
    if not args.verify and not (args.out_dir and args.site):
        parser.error("give out_dir and site (or --verify FOLDER)")
    signer = (args.approved_by.strip(), args.school.strip())
    if any(signer) and not all(signer):
        parser.error("--approved-by and --school go together")
    if all(signer) and args.notes:
        parser.error("sign after reading the revised letter: run --notes first, then --approved-by")
    try:
        notes = Path(args.notes).read_text().strip() if args.notes else ""
    except OSError as err:
        parser.error(f"cannot read the notes: {err}")
    if args.notes and not notes:
        parser.error(f"{args.notes} is empty")
    return args, notes, signer


def verify_folder(folder):
    """--verify: each listed file's MATCH, CHANGED or MISSING; the exit status is 0 only when every one matches."""
    try:
        status = seal.verify(folder)
    except (OSError, ValueError) as err:
        sys.exit(f"pack.py --verify: {err}")
    if not status:
        sys.exit(f"pack.py --verify: {Path(folder) / seal.SUMS} lists no files")
    print("\n".join(f"{state:8}{name}" for name, state in status.items()))
    sys.exit(0 if set(status.values()) == {"MATCH"} else 1)


def main():
    args, notes, signer = parse_args()
    if args.verify:
        verify_folder(args.verify)
    out_dir, site = Path(args.out_dir), json.loads(Path(args.site).read_text())
    try:
        submitted(site)
    except ValueError as err:
        sys.exit(f"pack.py: {err}")
    data = json.loads((out_dir / "events.json").read_text())
    events = confirmed(data["events"])
    seen = real_crossers(data["events"],
                         data.get("exposure") or {"minutes": round(clip_minutes(out_dir / "clip.mp4", data["fps"]), 1)})
    paths = data.get("paths") or {}  # desire lines: with them a 0-event clip still gets its photo, fix and letter
    measured = facts(site, events, seen, paths)
    prompt = LETTER_PROMPT.format(facts=measured, language=site.get("letter_language", "English"))
    untrusted = pace.warning(data.get("walking"))  # no letter (no paid call) from speeds and gaps that are not measured
    saved = None if untrusted else saved_plan(out_dir, prompt)
    if untrusted:
        print(f"no letter or fix picture: {untrusted}", file=sys.stderr)
    if (notes or all(signer)) and not saved:
        sys.exit("pack.py: --notes and --approved-by work on plan.json's letter from these same measurements, and "
                 "there is none: run pack.py without them first, and have that letter read")
    plan, images, ground = saved, None, None  # saved stays if a revision fails
    if (events or paths) and not untrusted:
        try:
            photo = street_photo(out_dir / "clip.mp4", out_dir / "street.jpg", site.get("person", "person"),
                                 site.get("vehicles", []))
        except (ValueError, OSError, subprocess.CalledProcessError) as err:
            print(f"no street photo: {err}", file=sys.stderr)
            photo = None
        ground = roadmap.ground(photo, site, events, out_dir, paths) if photo else None  # the street seen from above
        try:
            key = optional_key()
            plan = (saved if saved and not notes else  # a re-run pays nothing
                    new_plan(out_dir, prompt, measured, key, photo, saved if notes else None, notes))
            drawn = out_dir / fixband.PICTURE
            if photo and saved and drawn.is_file() and fix_instruction(saved) == fix_instruction(plan):
                muse = lambda image, words, path: drawn  # drawn for this same fix by an earlier run: no new call
            else:  # Muse Image draws the fix in the measured band; without a key there is no street image
                muse = (lambda image, words, path: draw_fix(image, words, key, path)) if photo and key else None
            if muse:
                images = fixband.draw(photo, plan["fix"], fix_instruction(plan), events, site,
                                      photo_people(out_dir / "clip.mp4", site.get("person", "person")), muse, out_dir)
        except (SystemExit, OSError, ValueError, KeyError, IndexError, TypeError, AttributeError,
                http.client.HTTPException, subprocess.CalledProcessError) as err:
            print(f"letter or fix image failed, the page shows plan.json's letter if any, else the measurements only: "
                  f"{err}", file=sys.stderr)
    signoff = sign(out_dir, plan, *signer) if plan and all(signer) else read_signoff(out_dir)
    page_html = page(site, events, seen, plan, images, data["fps"], data.get("cost"), data.get("sam_full_requests"),
                     data.get("privacy"), signoff=signoff, receipt=receipt_line(data, plan, images),
                     source_sha256=data.get("source_sha256"), timeline=data.get("timeline"), ground=ground,
                     paths=paths, walking=data.get("walking"))
    (out_dir / "index.html").write_text(page_html)
    seal.write_sums(share(out_dir, page_html))  # the only folder to publish, and its hashes
    print(f"wrote {out_dir / 'index.html'}: {len(serious(events))} serious, {len(events) - len(serious(events))} close "
          f"passes, fix: {plan['fix'] if plan else 'none'}")


if __name__ == "__main__":
    main()
