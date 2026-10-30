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

Run: python3 finetune_judge.py --dir DIR [--writers spark-open=50] [--cap 1.50] [--yes]
                                [--dev-letters N --out-dir OUT --name NAME]
--writers also takes spark=N: Muse Spark on the Meta API (MODEL_API_KEY), the writer pack.py uses by default, at
pack's reasoning effort "low", on packs from seed 10000 on (Spark Open's start at 0), so no pack has two letters.
Without --yes it estimates and builds rows from cached letters only. Letters are cached in DIR/letters (Spark Open)
and DIR/letters-spark, so a re-run pays nothing; DIR/reviewed.json holds the verdicts. Writes OUT/NAME.jsonl and
OUT/NAME.manifest.json (OUT is DIR unless given). With --dev-letters N, N whole letters (writers in turn) are dev and
the file is the starter's input (muse_glimmer_starter.py --file, seed 0, --n-eval from OUT/split.json): its shuffle
holds out every dev row and every public-bench prompt and trains on the rest; OUT/split.json labels the holdout.
v1 (commit 4b5f9fd, --writers spark-open=50 with no dev letters) had no "pairs restated" clean control and no inserted
"near-misses swapped" lie, so its rows come from that commit's finetune_judge.py; this one adds both.

v2: python3 finetune_judge.py --dir DIR --writers spark-open=100,spark=50 --dev-letters 15 --out-dir DIR/v2 \
        --name judge_v2 --cap 6.80 --yes
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
import review
import road
import sam
import writers_table

FIREWORKS_URL = "https://api.fireworks.ai/inference/v1"
WRITER_MODEL = "accounts/fireworks/models/muse-spark-open"  # the writer of the public bench's spark-open letter
# --writers name: (its letter cache under --dir, its first pack seed, its model, its server; "" = the Meta API as pack.py
# asks Muse Spark, spark_run). A record cached without "writer" is Spark Open's (v1).
WRITERS = {"spark-open": ("letters", 0, WRITER_MODEL, FIREWORKS_URL), "spark": ("letters-spark", 10_000, review.MODEL, "")}
STARTER_SEED = 0  # muse_glimmer_starter.py --seed: _prepare shuffles the file with random.Random(seed), holds out n_eval
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


def pair_sentence(worst, swap):
    """A sentence putting two near-misses' speeds with their time gaps, the speeds swapped when `swap`; None when no
    two near-misses differ in both. Every number is measured. v2: Spark Open rarely names two near-misses in one
    sentence, so judge_bench.swapped gave only 2 rows in v1."""
    pairs = [(a, b) for i, a in enumerate(worst) for b in worst[i + 1:]
             if a["pet_s"] != b["pet_s"] and a["vehicle_kmh"] != b["vehicle_kmh"]]
    if not pairs:
        return None
    a, b = pairs[0]
    first, second = (b, a) if swap else (a, b)
    return (f"In the near-miss with a time gap of {a['pet_s']} s the vehicle was going at {first['vehicle_kmh']} km/h, "
            f"and in the one with a time gap of {b['pet_s']} s it was going at {second['vehicle_kmh']} km/h.")


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
    elif lie := pair_sentence(worst, swap=True):
        out.append(("near-misses swapped", judge_bench.inserted(letter, lie), f'"{lie}": the two speeds are swapped; '
                    "each is put with the other near-miss's time gap."))
    return [o for o in out if o[1]]


def true_sentences(facts):
    """(kind, a sentence the measurements support or that claims nothing) for clean controls."""
    n, c = facts["serious_near_misses"], facts["close_passes"]
    many = lambda k, one, more: f"{k} {one if k == 1 else more}"
    fastest = max(e["vehicle_kmh"] for e in facts["worst"])
    pair = pair_sentence(facts["worst"], swap=False)
    return [("meeting offered", "We would be glad to walk the crossing with your engineers whenever it suits them."),
            ("counts restated", f"To sum up, the recording showed {many(n, 'serious near-miss', 'serious near-misses')} "
                                f"and {many(c, 'close pass', 'close passes')}."),
            ("not recorded accidents", "None of these near-misses is a recorded accident; each was measured on video."),
            ("recording length", f"The recording these figures come from lasted {facts['observed']['minutes']} minutes."),
            ("fastest restated", f"Among the worst near-misses measured, the fastest vehicle was going at {fastest} km/h."),
            ("one recording", "These figures come from a single recording and may differ on other days."),
            ("adult risk source", f"The death-risk figures are for adults hit by a car front ({facts['risk_source']}).")] + (
        [("pairs restated", pair)] if pair else [])


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


def cost_usd(usage, model=WRITER_MODEL):
    """A call's price from its usage at writers_table's quoted price; WORST_CALL_USD when not reported."""
    price, (prompt, cached, completion, _) = writers_table.PRICES[model], writers_table.tokens(usage)
    if prompt is None or completion is None:
        return WORST_CALL_USD
    cached = cached or 0
    return ((prompt - cached) * price[0] + cached * price[1] + completion * price[2]) / writers_table.PER


def write_letter(seed, measured, writer="spark-open", key=None):
    """`writer`'s letter for one pack, through pack.model_plan exactly as pack.py asks it (no judge here, no street
    photo: a synthetic pack has none). `key` is the Meta API key, for Muse Spark. An unreadable plan is a paid reply:
    it is kept, at WORST_CALL_USD, so a re-run never asks again. A refused or failed request (network, HTTP error) is
    None: nothing cached, and the run stops after this batch."""
    _, _, model, url = WRITERS[writer]
    pack.LETTER_URL, pack.LETTER_MODEL, pack.LETTER_KEY = url, model, ""  # Fireworks key: FIREWORKS_API_KEY
    prompt = pack.LETTER_PROMPT.format(facts=measured, language="English")
    try:
        plan = pack.model_plan(prompt, key, None, measured)
    except (OSError, http.client.HTTPException) as err:
        print(f"finetune_judge: the letter call failed, nothing cached for pack {seed}: {err}", file=sys.stderr)
        return None
    except (ValueError, KeyError, TypeError) as err:
        return {"seed": seed, "writer": writer, "measured": measured, "error": str(err)[:300], "cost_usd": WORST_CALL_USD}
    return {"seed": seed, "writer": writer, "model": model, "measured": measured, "prompt_chars": len(prompt),
            "cost_usd": cost_usd(plan.get("usage"), model),
            "plan": {k: plan[k] for k in pack.PLAN_KEYS}, **{k: plan.get(k) for k in ("usage", "request_id", "wall_s")}}


def cached_usd(cache):
    return sum(json.loads(p.read_text())["cost_usd"] for p in cache.glob("*.json"))


def letters(cache, target, cap, pay, public, reviewed, writer="spark-open", spent=None, key=None):
    """(base letters, rejected {seed: why}, USD spent) once `target` of `writer`'s letters pass, the cap would be
    passed, or (without `pay`) the cache runs out. `spent` is every writer's cached spend (default: this cache's)."""
    bases, rejected = [], {}
    spent = cached_usd(cache) if spent is None else spent
    seed = WRITERS[writer][1]
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
                made = list(pool.map(lambda s: write_letter(s, synthetic_pack(s), writer, key), batch))
            for record in filter(None, made):
                (cache / f"{record['seed']:04d}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False))
                spent += record["cost_usd"]
                print(f"pack {record['seed']}: ${record['cost_usd']:.4f}, ${spent:.4f} spent", file=sys.stderr)
            if None in made:
                break
            continue
        record = {"writer": "spark-open", **json.loads(path.read_text())}
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
    sparked = [b for b in bases if b["writer"] == "spark-open"]  # Glimmer's family: the closest tokenizer at hand
    chars = sum(b["prompt_chars"] for b in sparked)
    per_char = sum(writers_table.tokens(b["usage"])[0] or 0 for b in sparked) / chars if chars else 0
    longest = max(len(r["messages"][0]["content"]) for r in rows)
    starts = [0]
    for b in bases:
        starts.append(starts[-1] + sum(1 for r in rows if r.get("seed") == b["seed"]))
    return {"file": jsonl.name, "sha256": hashlib.sha256(jsonl.read_bytes()).hexdigest(), "rows": len(rows),
            "planted": sum(r["planted"] for r in rows), "clean": sum(not r["planted"] for r in rows),
            "clean_share": round(sum(not r["planted"] for r in rows) / len(rows), 3), "kinds": kinds,
            "letters": len(bases), "rows_by_letter": {b["seed"]: [starts[i], starts[i + 1]] for i, b in enumerate(bases)},
            "rejected_letters": rejected, "letters_by_writer": {w: sum(b["writer"] == w for b in bases) for w in WRITERS},
            "letter_writer": {w: f"{m} on {u or 'the Meta API (' + sam.API_URL + ')'}" for w, (_, _, m, u) in WRITERS.items()},
            "letter_cost_usd": round(spent, 4), "public_bench_overlap": overlap,
            "longest_judge_prompt": {"chars": longest, "tokens_est": round(longest * per_char),
                                     "how": "chars x Spark Open's prompt tokens per char on these letters' prompts"},
            "data": "synthetic packs only (finetune_judge.synthetic_pack): no real video, no DUT, no SinD, no out/"}


def dev_split(bases, n_dev):
    """(train, dev) whole letters: dev takes each writer's next letter in turn, each writer's letters in a seeded order,
    so it mixes writers and is the same on every run."""
    queues = [random.Random(f"dev/{w}").sample(own, len(own))
              for w in WRITERS if (own := [b for b in bases if b["writer"] == w])]
    turns = [q[i] for i in range(max(map(len, queues), default=0)) for q in queues if i < len(q)]
    dev = {b["seed"] for b in turns[:n_dev]}
    return [b for b in bases if b["seed"] not in dev], [b for b in bases if b["seed"] in dev]


def public_rows():
    """The 31 public-bench prompts as rows, each the judge prompt pack sends and its label's reply."""
    return [{"kind": i["kind"], "planted": i["planted"], "id": i["id"], "messages": [
        {"role": "user", "content": pack.JUDGE_PROMPT.format(facts=i["measured"], letter=i["letter"])},
        {"role": "assistant", "content": reply([i["kind"]] if i["planted"] else [])}]}
        for i in json.loads(judge_bench.PUBLIC.read_text())]


def starter_order(train, hold, seed=STARTER_SEED):
    """`train` and `hold` (JSONL lines) in one order whose random.Random(seed).shuffle, as the starter's _prepare does,
    puts `hold` first, in its own order, and every `train` line after: the starter's n_eval is len(hold). Checked by
    replaying that shuffle."""
    perm = list(range(len(train) + len(hold)))
    random.Random(seed).shuffle(perm)  # shuffle moves items by the list's length only: the file's moves are these
    at, rest = dict(zip(perm, hold)), iter(train)
    out = [at[i] if i in at else next(rest) for i in range(len(perm))]
    replay = list(out)
    random.Random(seed).shuffle(replay)
    if replay[:len(hold)] != hold or sorted(replay[len(hold):]) != sorted(train):
        raise AssertionError("the starter's shuffle would not hold out exactly the dev and public rows")
    return out


def line(row):
    return json.dumps({"messages": row["messages"]}, ensure_ascii=False)


def counts(rows):
    return {"rows": len(rows), "planted": sum(r["planted"] for r in rows), "clean": sum(not r["planted"] for r in rows),
            "swapped": sum(r["kind"] == "near-misses swapped" for r in rows)}


def write_starter(rows, bases, n_dev, out, name):
    """OUT/NAME.jsonl in starter order and OUT/split.json: n_eval and the holdout's labels in post-shuffle order."""
    train_letters, dev_letters = dev_split(bases, n_dev)
    dev_seeds = {b["seed"] for b in dev_letters}
    dev = [r for r in rows if r["seed"] in dev_seeds]
    train = [r for r in rows if r["seed"] not in dev_seeds]
    public = public_rows()
    if {line(r) for r in public} & {line(r) for r in rows}:
        raise SystemExit("finetune_judge: a public-bench prompt is among the synthetic rows, nothing written")
    hold = dev + public
    jsonl = out / f"{name}.jsonl"
    jsonl.write_text("".join(x + "\n" for x in starter_order([line(r) for r in train], [line(r) for r in hold])))
    labels = [{"set": "dev", "planted": r["planted"], "kind": r["kind"], "id": f"{r['writer']}/{r['seed']}/{r['k']}"}
              for r in dev] + [{"set": "public", "planted": r["planted"], "kind": r["kind"], "id": r["id"]} for r in public]
    split = {"file": jsonl.name, "sha256": hashlib.sha256(jsonl.read_bytes()).hexdigest(), "starter_seed": STARTER_SEED,
             "n_eval": len(hold), "train_rows": len(train),
             "dev_letters": [{"seed": b["seed"], "writer": b["writer"]} for b in dev_letters],
             "train_letters": len(train_letters), "sets": {"train": counts(train), "dev": counts(dev),
                                                           "public": counts(public)},
             "how": "the starter's _prepare shuffles the file with random.Random(seed) and holds out the first n_eval "
                    "rows: these, in this order (replayed when the file was written)", "holdout": labels}
    (out / "split.json").write_text(json.dumps(split, indent=1, ensure_ascii=False))
    return jsonl, split


def parse_writers(text):
    """"spark-open=100,spark=50" as {"spark-open": 100, "spark": 50}."""
    wanted = {}
    for part in text.split(","):
        name, _, n = part.partition("=")
        if name.strip() not in WRITERS or not n.strip().isdigit():
            raise argparse.ArgumentTypeError(f"{part!r}: give NAME=COUNT, NAME one of {', '.join(WRITERS)}")
        wanted[name.strip()] = int(n)
    return wanted


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", required=True, help="where the letter caches and reviewed.json are")
    parser.add_argument("--writers", type=parse_writers, default={"spark-open": 50},
                        help=f"usable letters per writer, e.g. spark-open=100,spark=50 ({', '.join(WRITERS)})")
    parser.add_argument("--cap", type=float, default=1.50,
                        help="USD, every cached call counted: no new call once this could be passed")
    parser.add_argument("--yes", action="store_true", help="pay for missing letters (else estimate only)")
    parser.add_argument("--dev-letters", type=int, default=0,
                        help="whole letters held out as dev; the file is then the starter's input with the public bench")
    parser.add_argument("--out-dir", help="where NAME.jsonl, its manifest and split.json go (default --dir)")
    parser.add_argument("--name", default="judge_train", help="the file's name, without .jsonl")
    args = parser.parse_args()
    cache, public = Path(args.dir), public_spans()
    out = Path(args.out_dir or args.dir)
    out.mkdir(parents=True, exist_ok=True)
    review_file = cache / "reviewed.json"  # a person's verdicts on letters with RISKY words: {"seed": "keep: ..."}
    reviewed = json.loads(review_file.read_text()) if review_file.is_file() else {}
    key = pack.optional_key() if "spark" in args.writers else None
    if args.yes and "spark" in args.writers and not key:
        raise SystemExit("finetune_judge: spark letters need MODEL_API_KEY (environment or .env)")
    for folder, *_ in WRITERS.values():
        (cache / folder).mkdir(parents=True, exist_ok=True)
    spent = sum(cached_usd(cache / folder) for folder, *_ in WRITERS.values())
    bases, rejected = [], {}
    for writer, target in args.writers.items():
        folder = cache / WRITERS[writer][0]
        got, why, spent = letters(folder, target, args.cap, args.yes, public, reviewed, writer, spent, key)
        bases, rejected = bases + got, {**rejected, **why}
        for seed, reason in why.items():
            if reason.startswith("not reviewed"):
                letter = json.loads((folder / f"{seed:04d}.json").read_text())["plan"]["letter"]
                print(f"to review, {writer} pack {seed}:",
                      *(s for s in pack.SENTENCE.split(letter) if RISKY.search(s.lower())), sep="\n  ")
        print(f"{writer}: {estimate(target, len(got), spent, args.cap)}")
    if not bases:
        return
    rows = [{**r, "seed": b["seed"], "writer": b["writer"], "measured": b["measured"], "k": k} for b in bases
            for k, r in enumerate(letter_rows(b["plan"]["letter"], b["measured"], b["seed"]))]
    public_letters = {i["letter"] for i in json.loads(judge_bench.PUBLIC.read_text())}
    near = [r["seed"] for r in rows if shared(r["letter"], r["measured"], public)]
    overlap = {"rows_checked": len(rows), "exact_copies": sum(r["letter"] in public_letters for r in rows),
               "rows_sharing_a_12_word_span": len(near),
               "rule": "a 12-word span shared with any public-bench letter (its measurements' spans left out), unless half "
                       "or more of its words are quoted from the row's measurements (4-word runs)"}
    print(f"public-bench overlap: {json.dumps(overlap)}")
    if overlap["exact_copies"] or near:
        raise SystemExit("finetune_judge: rows overlap the public bench, nothing written")
    if args.dev_letters:
        jsonl, split = write_starter(rows, bases, args.dev_letters, out, args.name)
    else:
        jsonl, split = out / f"{args.name}.jsonl", None
        jsonl.write_text("".join(line(r) + "\n" for r in rows))
    summary = {**manifest(rows, bases, rejected, spent, overlap, jsonl), "reviewed": {
        str(b["seed"]): reviewed[str(b["seed"])] for b in bases if str(b["seed"]) in reviewed}}
    if split:  # the file's rows are in the starter's order, not by letter: split.json says which row is which
        summary = {**{k: v for k, v in summary.items() if k != "rows_by_letter"},
                   **{k: split[k] for k in ("n_eval", "train_rows", "sets", "dev_letters")},
                   "file_rows": len(rows) + split["sets"]["public"]["rows"]}  # "rows", "kinds": the synthetic rows
    (out / f"{args.name}.manifest.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("rows_by_letter", "rejected_letters")}, indent=1))
    print(f"rejected letters: {len(rejected)}", *(f"  pack {s}: {w}" for s, w in rejected.items()), sep="\n")


if __name__ == "__main__":
    main()
