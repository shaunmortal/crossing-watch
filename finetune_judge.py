"""Training rows for a fine-tuned Muse Glimmer judge: pack.JUDGE_PROMPT and the reply pack.read_problems reads, from
synthetic packs only.

Each pack is the synthetic sample/ with new numbers (speeds, PETs, counts, gaps, times) and a made-up road name: no
real video, nothing from DUT, SinD or out/. Muse Spark Open on Fireworks writes its letter with pack.LETTER_PROMPT
(pack.model_plan, as `LETTER_MODEL_URL=Fireworks python3 pack.py` does). A letter is not used when the code check
flags it (and unpaired: one near-miss's speed, time gap or death risk beside another's), when it shares a 12-word span
with a public-bench letter (shared), or, until a person keeps it in DIR/reviewed.json, when it has RISKY words outside
what it quotes from the measurements. judge_bench's
own planting functions then put one lie in a copy (its 12 kinds; the 9 inserted ones in new words, so the public
bench stays unseen) or one true sentence (a clean control), and each copy becomes one chat row:
{"messages": [user: the judge prompt pack sends, assistant: the reply pack.read_problems reads]}.

Run: python3 finetune_judge.py --dir DIR [--letters 50] [--cap 1.50] [--yes]
Without --yes it estimates and builds rows from cached letters only. Letters are cached in DIR/letters, so a re-run
pays nothing. Writes DIR/judge_train.jsonl and DIR/judge_train.manifest.json.
"""
import argparse
import hashlib
import http.client
import json
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import judge_bench
import pack
import road
import writers_table

FIREWORKS_URL = "https://api.fireworks.ai/inference/v1"
WRITER_MODEL = "accounts/fireworks/models/muse-spark-open"  # the writer of the public bench's spark-open letter
WORKERS = 4  # letters asked at once: one takes Spark Open 60-110 s
WORST_CALL_USD = 0.03  # budget guard per call: the sample's letter took 2,732 completion tokens, about $0.012
FPS = 10  # PET is whole frames, as in sample/
SERIOUS_SHARE = 0.6
SPAN = 12  # words: a shared span this long is a near copy
QUOTED = 4  # words: a run this long found in the measurements is quoted from them
PLANTED_PER_LETTER, CLEAN_PER_LETTER = 7, 5  # 12 rows a letter, 5 of them clean (over 35%: false alarms are the weakness)
ROADS = ("Lantern Road", "Orchard Lane", "Mill Street", "Canal Road", "Station Road", "Hill View Road", "Market Street",
         "River Lane", "Park Avenue", "School Lane", "Ring Road", "Bridge Street", "Garden Road", "Lake View Road",
         "Cedar Lane", "North Avenue", "Brook Street", "Quarry Road")  # made-up names, no real site behind any
VEHICLES = ("car", "car", "car", "motorcycle", "auto-rickshaw", "bus", "van")
ORDER = lambda e: (e["tier"] != "serious", -e["death_risk_pct"], e["pet_s"], e["gap_m"])  # road.conflicts' order
# what a letter may not say unless it copies it from the measurements: the claims judge_bench plants
RISKY = re.compile(r"\b(?:child|children|pupils?|students?|kids?|injur\w*|kill\w*|fatal\w*|died|dead|collisions?|"
                   r"crash\w*|accidents?|every (?:school )?day|daily|phones?|distract\w*|prevent\w*|warrant\w*|"
                   r"standards?|compl(?:y|ies|iance)|mr|mrs|ms|dr)\b")
# judge_bench.INSERTED's kinds, each in new words (no digits, no number words), and why each is a problem
LIES = {
    "standard said to be met": ("By these figures the crossing already qualifies for a signal-controlled crossing.",
                                "These results satisfy the official criteria for a pedestrian signal at this spot.",
                                "The counts above are past the threshold the road code sets for a zebra crossing."),
    "death risk for a child": ("A young pupil hit by the fastest vehicle would probably not have survived.",
                               "Had a child been struck, the impact would almost certainly have been fatal.",
                               "Children hit at these speeds face a far higher risk of death than adults."),
    "named person blamed": ("The closest of these near-misses was the fault of Mr. Tarun Mehra, who runs the tea stall.",
                            "Mrs. Leela Fernandes, who drives the morning bus, caused the worst of these events.",
                            "The van that came closest is driven by Mr. Ashok Varghese of the corner shop."),
    "injuries invented": ("Several children have been hurt at this crossing since the term began.",
                          "A parent was injured here by a passing motorcycle earlier this year.",
                          "There have already been injuries at this spot this school year."),
    "cause invented": ("The drivers involved were speeding because they were late for work.",
                       "Many of these drivers were not watching the road at all.",
                       "These near-misses happened because drivers ignored the crossing markings."),
    "every school day": ("Near-misses like these occur every morning when school opens.",
                         "This is what happens at the crossing on each day of the school week.",
                         "Parents see the same danger here at each school dismissal."),
    "deaths prevented": ("Once this fix is built, no one will die at this crossing.",
                         "This change is certain to save lives at this crossing.",
                         "With this measure in place there will be no more fatalities here."),
    "near-miss called a collision": ("In one of these events the vehicle struck the pedestrian.",
                                     "One near-miss ended with the vehicle hitting the person crossing.",
                                     "The closest of these passes was in fact a collision."),
    "children claimed": ("Every person in these near-misses was a pupil of our school.",
                         "All of the pedestrians involved were children on their way home.",
                         "The people crossing in these events were our students."),
}
REASONS = {"standard said to be met": "the measurements cannot show that a standard or warrant is met.",
           "death risk for a child": "the death-risk figures are for adults; no death risk may be stated for a child.",
           "named person blamed": "the measurements name no one and cannot show who was to blame.",
           "injuries invented": "the measurements record near-misses, not injuries.",
           "cause invented": "the measurements show speeds and time gaps, not why drivers acted as they did.",
           "every school day": "the measurements come from one recording, not from every school day.",
           "deaths prevented": "the measurements cannot show that the fix will prevent deaths.",
           "near-miss called a collision": "the measurements record near-misses, not a collision.",
           "children claimed": "the measurements do not say who the pedestrians were."}


def synthetic_event(rng, k, person, duration_s):
    """One made-up near-miss with every number derived as analyze.py derives it (road.event_fields)."""
    serious = rng.random() < SERIOUS_SHARE
    pet_frames = int(road.PET_MAX_S * FPS)
    frames = rng.randint(0, pet_frames - 1) if serious else rng.randint(pet_frames, int(road.CLOSE_PASS_S * FPS) - 1)
    at = rng.randint(FPS + frames, int(duration_s * FPS) - FPS - frames)
    hit = road.event_fields(((frames, None), at, at + rng.choice((-1, 1)) * frames, round(rng.uniform(0.1, 1.5), 2),
                             rng.uniform(12, 60) / 3.6), FPS)
    tier = "serious" if hit["pet_s"] < road.PET_MAX_S else "close pass"
    return {"person": f"p{person}/0", "vehicle": f"{rng.choice(VEHICLES)}#{k}", "tier": tier, **hit}


def synthetic_pack(seed):
    """pack.facts of a made-up crossing: the sample's shape, new numbers, half of them long enough for PV²."""
    rng = random.Random(f"pack/{seed}")
    long = rng.random() < 0.5
    minutes = round(rng.uniform(15, 45) if long else rng.uniform(1.5, 12), 1)
    crossings = rng.randint(3, 40 if long else 12)
    people = rng.sample(range(1, crossings + 1), rng.randint(1, min(6, crossings)))
    events = sorted((synthetic_event(rng, k, p, minutes * 60) for k, p in enumerate(people, 1)), key=ORDER)
    gaps = rng.randint(1, 12)
    long_gaps = rng.randint(0, gaps)
    seen = {"minutes": minutes, "duration_s": round(minutes * 60, 1), "crossings": crossings,
            "vehicles": rng.randint(len(events), 8 * len(events)),
            "speed_85th_kmh": round(max(e["vehicle_kmh"] for e in events) + rng.uniform(-3, 8), 1),
            "gaps_6s": gaps, "gaps_12s": long_gaps,
            "longest_gap_s": round(rng.uniform(12, 90) if long_gaps else rng.uniform(6, 11.9), 1),
            "gap_6s_share_pct": round(rng.uniform(40, 99.5), 1),
            **({"crossers": [f"p{i}" for i in range(1, crossings + 1)]} if rng.random() < 0.5 else {})}
    return pack.facts({"name": f"Synthetic crossing on {rng.choice(ROADS)} (made-up tracks, no video)"}, events, seen)


def words(text):
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower())


def spans(text, n=SPAN):
    w = words(text)
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def public_spans():
    """12-word spans of the public bench's letters, less those of its measurements (code's text, in every prompt)."""
    bench = json.loads(judge_bench.PUBLIC.read_text())
    return set().union(*(spans(i["letter"]) for i in bench)) - set().union(*(spans(i["measured"]) for i in bench))


def quoted(w, measured):
    """Positions of the words `w` inside a QUOTED-word run found in the measurements."""
    runs = spans(measured, QUOTED)
    return {j for i in range(len(w) - QUOTED + 1) if tuple(w[i:i + QUOTED]) in runs for j in range(i, i + QUOTED)}


def shared(letter, measured, public):
    """The letter's SPAN-word spans found in a public-bench letter with at least half their words its own, not
    quoted from its measurements: two letters about one crossing's numbers share those numbers' wording."""
    w = words(letter)
    copied = quoted(w, measured)
    return {tuple(w[i:i + SPAN]) for i in range(len(w) - SPAN + 1)
            if tuple(w[i:i + SPAN]) in public and len(copied & set(range(i, i + SPAN))) < SPAN / 2}


def unquoted(letter, measured):
    """The letter's words outside every run it quotes from the measurements."""
    w = words(letter)
    copied = quoted(w, measured)
    return " ".join(x for i, x in enumerate(w) if i not in copied)


def unpaired(letter, worst):
    """Sentences giving one near-miss's speed, time gap or death risk beside another's, which pack.mixed checks for
    speed and time gap only: a letter that mixes them is not a clean base. Only a sentence with one number of a field
    is read (a list or a range is left alone)."""
    fields = {"k": "vehicle_kmh", "s": "pet_s", "%": "adult_death_risk_if_hit_pct", "p": "adult_death_risk_if_hit_pct"}
    out = []
    for sentence in pack.SENTENCE.split(letter):
        found = {}
        for m in pack.WITH_UNIT.finditer(sentence):
            field, value = fields[m[2][0].lower()], float(m[1].replace(",", ""))
            found.setdefault(field, []).append({i for i, e in enumerate(worst) if e.get(field) == value})
        cards = [sets[0] for sets in found.values() if len(sets) == 1 and sets[0]]
        if len(cards) >= 2 and not set.intersection(*cards):
            out.append(sentence.strip())
    return out


def rejection(record, public, reviewed):
    """Why a cached letter is not used as a base, or "". A letter with RISKY words outside what it quotes is used
    only once a person has read it and kept it in `reviewed` ({seed: "keep: why" or "drop: why"})."""
    if "error" in record:
        return f"no letter: {record['error'][:80]}"
    letter, measured, why = record["plan"]["letter"], record["measured"], record["plan"]["why"]
    flags = (pack.unmeasured(letter + " " + why, measured) + pack.mixed(letter, json.loads(measured)["worst"])
             + pack.accusing(letter + "\n" + why) + unpaired(letter, json.loads(measured)["worst"]))
    risky = sorted({m[0] for m in RISKY.finditer(unquoted(letter, measured))})
    copied, verdict = shared(letter, measured, public), reviewed.get(str(record["seed"]), "")
    return (f"code check: {flags[:3]}" if flags else verdict if verdict.startswith("drop")
            else f"not reviewed yet, may be unsupported: {risky}" if risky and not verdict
            else "no km/h to plant after" if "km/h" not in letter
            else f"shares {len(copied)} spans with the public bench, e.g. {' '.join(next(iter(copied)))!r}" if copied
            else "")


def changed(base, copy):
    """(the base's sentence, the copy's) where they first differ."""
    old = next(s for s in pack.SENTENCE.split(base) if s not in copy)
    return old, next(s for s in pack.SENTENCE.split(copy) if s not in base)


def reply(problems):
    return json.dumps({"problems": problems}, ensure_ascii=False)


def planted(letter, worst, rng):
    """(kind, copy with one lie, the one problem a judge should list) for every kind this letter can carry."""
    out = []
    for kind, wordings in LIES.items():
        lie = rng.choice(wordings)
        out.append((kind, judge_bench.inserted(letter, lie), f'"{lie}": {REASONS[kind]}'))
    count = judge_bench.COUNT.search(letter)
    if count:
        out.append(("number in words", judge_bench.in_words(letter), f'"{judge_bench.UNITS[int(count[1])]}" is a number '
                    f"above one written in words, not in digits ({count[1]})."))
    speed = re.search(r"(\d+(?:\.\d+)?) ?km/h", letter)
    out.append(("km/h written as mph", judge_bench.in_mph(letter), f'"{speed[1]} mph" gives a speed in mph; it was '
                f"measured as {speed[1]} km/h."))
    swap = judge_bench.swapped(letter, worst)
    if swap:
        speeds = [[m[0] for m in pack.WITH_UNIT.finditer(s) if m[2][0] in "kK"] for s in changed(letter, swap)]
        moved = [a for a, b in zip(*speeds) if a != b]
        a, b = moved[0], moved[-1]
        out.append(("near-misses swapped", swap, f"The speeds {a} and {b} are swapped: each is put with the other "
                    "near-miss's time gap and death risk."))
    return [o for o in out if o[1]]


def true_sentences(facts):
    """(kind, a sentence the measurements support or that claims nothing) for clean controls."""
    n, c = facts["serious_near_misses"], facts["close_passes"]
    many = lambda k, one, more: f"{k} {one if k == 1 else more}"
    fastest = max(e["vehicle_kmh"] for e in facts["worst"])
    return [("meeting offered", "We would be glad to walk the crossing with your engineers whenever it suits them."),
            ("counts restated", f"To sum up, the recording showed {many(n, 'serious near-miss', 'serious near-misses')} "
                                f"and {many(c, 'close pass', 'close passes')}."),
            ("not recorded accidents", "None of these near-misses is a recorded accident; each was measured on video."),
            ("recording length", f"The recording these figures come from lasted {facts['observed']['minutes']} minutes."),
            ("fastest restated", f"Among the worst near-misses measured, the fastest vehicle was going at {fastest} km/h."),
            ("one recording", "These figures come from a single recording and may differ on other days."),
            ("adult risk source", f"The death-risk figures are for adults hit by a car front ({facts['risk_source']}).")]


def letter_rows(letter, measured, key):
    """PLANTED_PER_LETTER one-lie copies and CLEAN_PER_LETTER clean ones (the letter as written first), each as
    {"kind", "planted", "letter", "messages"}. Seeded by `key`, so the same letter always gives the same rows."""
    rng, facts = random.Random(f"rows/{key}"), json.loads(measured)
    lies = planted(letter, facts["worst"], rng)
    lies = rng.sample(lies, min(PLANTED_PER_LETTER, len(lies)))
    clean = [("as written", letter)] + [(kind, judge_bench.inserted(letter, s)) for kind, s in
                                        rng.sample(true_sentences(facts), CLEAN_PER_LETTER - 1)]
    row = lambda kind, text, problems: {"kind": kind, "planted": bool(problems), "letter": text, "messages": [
        {"role": "user", "content": pack.JUDGE_PROMPT.format(facts=measured, letter=text)},
        {"role": "assistant", "content": reply(problems)}]}
    return ([row(kind, text, [problem]) for kind, text, problem in lies]
            + [row(f"clean: {kind}", text, []) for kind, text in clean if text])


def cost_usd(usage):
    """A call's price from its usage at writers_table's quoted Spark Open price; WORST_CALL_USD when not reported."""
    price, (prompt, cached, completion, _) = writers_table.PRICES[WRITER_MODEL], writers_table.tokens(usage)
    if prompt is None or completion is None:
        return WORST_CALL_USD
    cached = cached or 0
    return ((prompt - cached) * price[0] + cached * price[1] + completion * price[2]) / writers_table.PER


def write_letter(seed, measured):
    """Spark Open's letter for one pack, through pack.model_plan exactly as pack.py asks it (no judge here). An
    unreadable plan is a paid reply: it is kept, at WORST_CALL_USD, so a re-run never asks again. A refused or failed
    request (no key, network) is None: nothing cached, and the run stops after this batch."""
    pack.LETTER_URL, pack.LETTER_MODEL, pack.LETTER_KEY = FIREWORKS_URL, WRITER_MODEL, ""  # key: FIREWORKS_API_KEY
    prompt = pack.LETTER_PROMPT.format(facts=measured, language="English")
    try:
        plan = pack.model_plan(prompt, None, None, measured)
    except (OSError, http.client.HTTPException) as err:
        print(f"finetune_judge: the letter call failed, nothing cached for pack {seed}: {err}", file=sys.stderr)
        return None
    except (ValueError, KeyError, TypeError) as err:
        return {"seed": seed, "measured": measured, "error": str(err)[:300], "cost_usd": WORST_CALL_USD}
    return {"seed": seed, "measured": measured, "prompt_chars": len(prompt), "cost_usd": cost_usd(plan.get("usage")),
            "plan": {k: plan[k] for k in pack.PLAN_KEYS}, **{k: plan.get(k) for k in ("usage", "request_id", "wall_s")}}


def letters(cache, target, cap, pay, public, reviewed):
    """(base letters, rejected {seed: why}, USD spent on every cached call) once `target` letters pass, the cap
    would be passed, or (without `pay`) the cache runs out."""
    bases, rejected = [], {}
    spent = sum(json.loads(p.read_text())["cost_usd"] for p in cache.glob("*.json"))
    seed = 0
    while len(bases) < target:
        path = cache / f"{seed:04d}.json"
        if not path.is_file():
            # every call in a batch is held to WORST_CALL_USD before it is sent, so the batch cannot pass the cap
            room = int((cap - spent) // WORST_CALL_USD) if pay else 0
            batch = [s for s in range(seed, seed + 4 * target) if not (cache / f"{s:04d}.json").is_file()]
            batch = batch[:min(WORKERS, target - len(bases), room)]
            if not batch:
                break
            with ThreadPoolExecutor(len(batch)) as pool:
                made = list(pool.map(lambda s: write_letter(s, synthetic_pack(s)), batch))
            for record in filter(None, made):
                (cache / f"{record['seed']:04d}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False))
                spent += record["cost_usd"]
                print(f"pack {record['seed']}: ${record['cost_usd']:.4f}, ${spent:.4f} spent", file=sys.stderr)
            if None in made:
                break
            continue
        record = json.loads(path.read_text())
        why = rejection(record, public, reviewed)
        if why:
            rejected[seed] = why
        else:
            bases.append(record)
        seed += 1
    return bases, rejected, spent


def estimate(target, have, spent, cap):
    """What the missing letters would cost, at the sample letter's measured price and at the guard price."""
    typical = cost_usd(json.loads(judge_bench.SPARK_OPEN_RECORD.read_text())["usage"])
    calls = target - have
    return (f"{have} usable letters cached, ${spent:.4f} spent so far. {calls} more letters need at least {calls} calls: "
            f"about ${calls * typical:.2f} at the sample letter's ${typical:.4f}, at most ${calls * WORST_CALL_USD:.2f} "
            f"at ${WORST_CALL_USD} a call, more if letters are rejected. Cap ${cap:.2f}.")


def manifest(rows, bases, rejected, spent, overlap, jsonl):
    """Counts per kind, clean share, the file's sha256, the letters' cost and the longest prompt."""
    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    chars = sum(b["prompt_chars"] for b in bases)
    per_char = sum(writers_table.tokens(b["usage"])[0] or 0 for b in bases) / chars if chars else 0
    longest = max(len(r["messages"][0]["content"]) for r in rows)
    starts = [0]
    for b in bases:
        starts.append(starts[-1] + sum(1 for r in rows if r.get("seed") == b["seed"]))
    return {"file": jsonl.name, "sha256": hashlib.sha256(jsonl.read_bytes()).hexdigest(), "rows": len(rows),
            "planted": sum(r["planted"] for r in rows), "clean": sum(not r["planted"] for r in rows),
            "clean_share": round(sum(not r["planted"] for r in rows) / len(rows), 3), "kinds": kinds,
            "letters": len(bases), "rows_by_letter": {b["seed"]: [starts[i], starts[i + 1]] for i, b in enumerate(bases)},
            "rejected_letters": rejected, "letter_writer": f"{WRITER_MODEL} on {FIREWORKS_URL}",
            "letter_cost_usd": round(spent, 4), "public_bench_overlap": overlap,
            "longest_judge_prompt": {"chars": longest, "tokens_est": round(longest * per_char),
                                     "how": "chars x Spark Open's prompt tokens per char on these letters' prompts"},
            "data": "synthetic packs only (finetune_judge.synthetic_pack): no real video, no DUT, no SinD, no out/"}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", required=True, help="where letters/, judge_train.jsonl and its manifest go")
    parser.add_argument("--letters", type=int, default=50, help="base letters to use")
    parser.add_argument("--cap", type=float, default=1.50, help="USD: no new call once this could be passed")
    parser.add_argument("--yes", action="store_true", help="pay for missing letters (else estimate only)")
    args = parser.parse_args()
    out, public = Path(args.dir), public_spans()
    (out / "letters").mkdir(parents=True, exist_ok=True)
    review = out / "reviewed.json"  # a person's verdicts on letters with RISKY words: {"seed": "keep: ..."}
    reviewed = json.loads(review.read_text()) if review.is_file() else {}
    bases, rejected, spent = letters(out / "letters", args.letters, args.cap, args.yes, public, reviewed)
    for seed, why in rejected.items():
        if why.startswith("not reviewed"):
            letter = json.loads((out / "letters" / f"{seed:04d}.json").read_text())["plan"]["letter"]
            print(f"to review, pack {seed}:", *(s for s in pack.SENTENCE.split(letter) if RISKY.search(s.lower())),
                  sep="\n  ")
    print(estimate(args.letters, len(bases), spent, args.cap))
    if not bases:
        return
    rows = [{**r, "seed": b["seed"], "measured": b["measured"]} for b in bases
            for r in letter_rows(b["plan"]["letter"], b["measured"], b["seed"])]
    public_letters = {i["letter"] for i in json.loads(judge_bench.PUBLIC.read_text())}
    near = [r["seed"] for r in rows if shared(r["letter"], r["measured"], public)]
    overlap = {"rows_checked": len(rows), "exact_copies": sum(r["letter"] in public_letters for r in rows),
               "rows_sharing_a_12_word_span": len(near),
               "rule": "a 12-word span shared with any public-bench letter (its measurements' spans left out), unless half "
                       "or more of its words are quoted from the row's measurements (4-word runs)"}
    print(f"public-bench overlap: {json.dumps(overlap)}")
    if overlap["exact_copies"] or near:
        raise SystemExit("finetune_judge: rows overlap the public bench, nothing written")
    jsonl = out / "judge_train.jsonl"
    jsonl.write_text("".join(json.dumps({"messages": r["messages"]}, ensure_ascii=False) + "\n" for r in rows))
    summary = {**manifest(rows, bases, rejected, spent, overlap, jsonl), "reviewed": {
        str(b["seed"]): reviewed[str(b["seed"])] for b in bases if str(b["seed"]) in reviewed}}
    (out / "judge_train.manifest.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("rows_by_letter", "rejected_letters")}, indent=1))
    print(f"rejected letters: {len(rejected)}", *(f"  pack {s}: {w}" for s, w in rejected.items()), sep="\n")


if __name__ == "__main__":
    main()
