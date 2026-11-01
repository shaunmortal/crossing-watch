"""v6 judge file (GATES.md, "Fine-tuned Glimmer judge v6"): model-written slip edits, real slips, 260 new test letters.

Train: v5's training rows, read back from v5's file unchanged (its letters checked by their as-written rows); a
model-written slip edit and its clean paraphrase control for every train letter the cap allows; the 32 real writer
slips adjudication found in v4's and v5's test rows, rebuilt with today's pack.JUDGE_PROMPT and labelled with their
adjudication note.
Test: 130 new letters per writer (Spark Open from 100000, Spark from 110000) under v4's rules, every train letter's
spans counted. Per letter: as written, one template lie, natural_edits' lie and clean edit, one code-planted writer
slip where code can plant one (as v5), and the model-written slip edit; plus the 31 public prompts.

Slip edits: an editor (Spark and Spark Open alternating, as natural_edits) rewrites ONE sentence of the letter two
ways: with one subtle slip about a quantity in QUANTITIES, and as a true paraphrase. Code keeps a slip only when exactly
that sentence changed, the sentence states the named quantity's value (a number in it, a word for the quantity) and the
measurements give another value; the label is code's statement of that check. A control is kept only when exactly that
sentence changed, its numbers are the original sentence's, and natural_edits and pack.slips find nothing in it.
Every call is cached in DIR/slip/WRITER-SEED.json, so a re-run pays nothing.

Run: python3 judge_v6.py --dir DIR [--cap 12] [--yes] [--letters-only] [--tokenizer GLIMMER_DIR]
Writes DIR/v6/judge_v6.jsonl, DIR/v6/split.json, DIR/v6/judge_v6.manifest.json.
"""
import argparse
import json
import random
import re
import statistics
import sys
from pathlib import Path

import finetune_judge as fj
import judge_v4
import judge_v5
import natural_edits
import pack

FIRST = 100_000  # added to each writer's first seed: Spark Open 100000+, Spark 110000+, past every earlier seed
V5_TRAIN_ROWS = 3648
MAX_TOKENS = 3072  # the run's max_seq_len
SLIP_CALL_USD = 0.04  # budget guard per call, as natural_edits
REPO = Path(__file__).resolve().parent
REAL_SLIPS = {4: "judge_v4.jsonl", 5: "judge_v5.jsonl"}  # adjudicated in provenance/glimmer-judge-lora-vN
NOTE_NOISE = re.compile(r"^found by adjudication: |\s*\(as v\d row \d+\)|; unlike v\d row \d+.*$")
ORDINAL = ("st", "nd", "rd", "th")


def worst(key, pick):
    return lambda f: pick(e[key] for e in f["worst"]) if f["worst"] else None


QUANTITIES = {  # name: (its value from the measurements, a word a sentence stating it must have)
    "closest near-miss time gap (s)": (worst("pet_s", min), r"closest|tightest|smallest|shortest|narrowest|nearest|"
                                                             r"lowest|least|worst"),
    "widest near-miss time gap (s)": (worst("pet_s", max), r"widest|largest|longest|biggest|highest|most"),
    "fastest near-miss vehicle (km/h)": (worst("vehicle_kmh", max), r"fastest|highest|top|quickest|maximum"),
    "highest adult death risk (%)": (worst("adult_death_risk_if_hit_pct", max),
                                     r"highest|greatest|largest|most|top|maximum"),
    "serious near-misses": (lambda f: f["serious_near_misses"], r"serious"),
    "close passes": (lambda f: f["close_passes"], r"close pass"),
    "near-misses in all (serious and close passes)": (lambda f: f["serious_near_misses"] + f["close_passes"],
                                                      r"near.miss|event|in all|total|altogether|combined"),
    "near-misses with the person first": (lambda f: f["person_first"], r"person|pedestrian|people"),
    "near-misses with the vehicle first": (lambda f: f["vehicle_first"], r"vehicle|car|driver"),
    "near-misses with both at once": (lambda f: f["both_at_once"], r"both|same (?:time|moment)|at once|simultan"),
    "crossings": (lambda f: f["observed"]["crossings"], r"crossing|pedestrian|people"),
    "vehicles": (lambda f: f["observed"]["vehicles"], r"vehicle"),
    "85th percentile speed (km/h)": (lambda f: f["observed"]["speed_85th_kmh"], r"85th|percentile"),
    "gaps of 6 s or more": (lambda f: f["observed"]["gaps_6s"], r"gap"),
    "gaps of 12 s or more": (lambda f: f["observed"]["gaps_12s"], r"gap"),
    "longest gap with no moving vehicle (s)": (lambda f: f["observed"]["longest_gap_s"],
                                               r"longest|largest|biggest|widest"),
    "share of time inside gaps of 6 s or more (%)": (lambda f: f["observed"]["gap_6s_share_pct"], r"%|per ?cent"),
    "minutes recorded": (lambda f: f["observed"]["minutes"], r"minute"),
}
SLIP_PROMPT = """You help test a reviewer that checks letters a school sends to its road authority. MEASUREMENTS are
the only facts. Pick ONE sentence of the LETTER that states something measured and write it again two ways:

1. "slip": the same sentence carrying exactly one subtle factual slip about the MEASUREMENTS, of the kind careful
writers really make: calling a near-miss the closest (or the fastest, or the largest gap) when the measurements hold a
closer (faster, larger) one; giving one tier the counts the measurements give over all events; saying the vehicle came
first where the counts say the person did (or the reverse); a total that adds the wrong counts; a share or count of
gaps taken from the wrong row. Every number in it must appear in the MEASUREMENTS, so only the claim is wrong. Keep it
plausible and on the sentence's own topic; add no new topic. "quantity" is the measured quantity it gets wrong, copied
exactly from this list: QUANTITY_LIST. "stated" is the value the slip sentence gives for it, a number written in digits
in that sentence. "why" is one sentence saying why the measurements contradict it.
2. "control": the same sentence in new words, still true: every number kept exactly as it is, in digits, no new claim.

"original" is the sentence of the LETTER, copied exactly, that both replace.
Reply JSON only:
{{"original": "...", "slip": {{"sentence": "...", "quantity": "...", "stated": 0, "why": "..."}},
 "control": {{"sentence": "..."}}}}

MEASUREMENTS:
{facts}

LETTER:
{letter}""".replace("QUANTITY_LIST", "; ".join(QUANTITIES))
_TEXT = {"type": "string"}
SLIP_SCHEMA = {"type": "object", "required": ["original", "slip", "control"], "properties": {
    "original": _TEXT,
    "slip": {"type": "object", "required": ["sentence", "quantity", "stated", "why"],
             "properties": {"sentence": _TEXT, "quantity": _TEXT, "stated": {"type": "number"}, "why": _TEXT}},
    "control": {"type": "object", "required": ["sentence"], "properties": {"sentence": _TEXT}}}}


def numbers(text):
    """The numbers written in `text`, sorted, ordinals ("85th") left out."""
    return sorted(float(m[0].replace(",", "")) for m in pack.NUMBER.finditer(text)
                  if text[m.end():m.end() + 2].lower() not in ORDINAL)


def replaced(letter, original, sentence):
    """(letter with its sentence `original` replaced by `sentence`, "") or (None, why not): exactly that one sentence
    of the letter changes, into one new sentence."""
    original, sentence = (original or "").strip(), (sentence or "").strip()
    old = natural_edits.sentences(letter)
    if not sentence or len(natural_edits.sentences(sentence)) != 1 or sentence in old:
        return None, "not one new sentence"
    if old.count(original) != 1:
        return None, "'original' is not one sentence of the letter"
    at = next((m.start() for m in re.finditer(re.escape(original), letter)
               if (m.start() == 0 or letter[m.start() - 1].isspace())
               and (m.end() == len(letter) or letter[m.end()].isspace())), None)
    if at is None:
        return None, "'original' is not one sentence of the letter"
    edited = letter[:at] + sentence + letter[at + len(original):]
    if natural_edits.sentences(edited) != [sentence if s == original else s for s in old]:
        return None, "the edit does not change exactly one sentence"
    return edited, ""


def check_slip(letter, measured, original, slip):
    """(edited letter, kind, [problem]) for an editor's slip, or (None, why dropped, None)."""
    if not isinstance(slip, dict) or not all(isinstance(slip.get(k), str) and slip[k].strip()
                                             for k in ("sentence", "quantity", "why")):
        return None, "fields missing", None
    if slip["quantity"].strip() not in QUANTITIES or isinstance(slip.get("stated"), bool) or \
            not isinstance(slip.get("stated"), (int, float)):
        return None, "no listed quantity or no stated number", None
    edited, why = replaced(letter, original, slip["sentence"])
    if not edited:
        return None, why, None
    name, sentence, stated = slip["quantity"].strip(), slip["sentence"].strip(), float(slip["stated"])
    value, word = QUANTITIES[name]
    truth = value(json.loads(measured))
    if truth is None:
        return None, "the quantity is not measured here", None
    if stated not in numbers(sentence) or not re.search(word, sentence, re.I):
        return None, "the sentence does not state the quantity's value", None
    if round(stated, 3) == round(float(truth), 3):
        return None, "the stated value is the measured one", None
    if pack.unmeasured(sentence, measured):
        return None, "a number in it is not measured", None
    return edited, f"slip edit: {name}", [f'"{sentence}": the measurements give {name} {truth}, not {slip["stated"]}.']


def check_control(letter, measured, original, control):
    """(edited letter, "clean: slip-edit control", []) for an editor's paraphrase, or (None, why dropped, None)."""
    if not isinstance(control, dict) or not isinstance(control.get("sentence"), str):
        return None, "fields missing", None
    edited, why = replaced(letter, original, control["sentence"])
    if not edited:
        return None, why, None
    sentence = control["sentence"].strip()
    if numbers(sentence) != numbers(original):
        return None, "the paraphrase changes a number", None
    why = natural_edits.unsupported_in_clean(sentence, measured) or \
        ("pack.slips flags it" if pack.slips(sentence, json.loads(measured)) else "")
    return (None, why, None) if why else (edited, "clean: slip-edit control", [])


def slip_edit_rows(bases, records, set_name, controls):
    """(rows, report): each base's kept slip edit (and, with `controls`, its kept control) as judge_v4 rows carrying
    the editor and the quantity, and per editor what was kept and why the rest was dropped."""
    rows, report = [], {e: {"letters": 0, "kept": 0, "dropped": {}} for e in natural_edits.EDITORS}
    for b in bases:
        record = records.get((b["writer"], b["seed"]))
        if not record:
            continue
        stats, reply = report[record["editor"]], natural_edits.parse(record.get("raw"))
        stats["letters"] += 1
        parts = (("slip", check_slip),) + ((("control", check_control),) if controls else ())
        for part, check in parts:
            text, kind, problems = check(b["plan"]["letter"], b["measured"], reply.get("original"), reply.get(part))
            if text is None:
                stats["dropped"][f"{b['writer']}/{b['seed']}/{part}"] = kind
                continue
            stats["kept"] += 1
            quantity = reply["slip"]["quantity"].strip() if problems else ""
            rows.append({**judge_v4.row(b, kind, text, problems, set_name, f"slip-edit{'' if problems else '-control'}"),
                         "editor": record["editor"], **({"slip_kind": quantity} if problems else {})})
    return rows, report


def v6_spend(cache):
    """USD of every cached v6 call: letters and natural edits from seed FIRST on, every slip edit and the five
    trial calls of an earlier wording of SLIP_PROMPT (kept in DIR/slip-trial, unused)."""
    out = {}
    for folder in [cache / f for f, *_ in fj.WRITERS.values()] + [cache / "natural", cache / "slip", cache / "slip-trial"]:
        for p in folder.glob("*.json"):
            r = json.loads(p.read_text())
            if folder.name.startswith("slip") or r["seed"] >= FIRST:
                name = f"{folder.name}:{r['editor']}" if "editor" in r else r.get("writer", "spark-open")
                out[name] = out.get(name, 0) + r["cost_usd"]
    return out


def slip_edit_all(cache, bases, pay, key, cap):
    """The cached slip-edit records of `bases`, asked (when `pay`) in their order while the v6 cap holds, until done
    or judge_v4.PASSES passes add none."""
    records, idle = {}, 0
    while pay and idle < judge_v4.PASSES and len(records) < len(bases):
        before = len(records)
        records, _ = natural_edits.edits(cache / "slip", bases, True, key, cap, sum(v6_spend(cache).values()),
                                         SLIP_PROMPT, SLIP_SCHEMA, SLIP_CALL_USD)
        idle = 0 if len(records) > before else idle + 1
    return natural_edits.edits(cache / "slip", bases, False, key, cap, 0)[0]


def base(cache, writer, seed):
    path = cache / fj.WRITERS[writer][0] / f"{seed:04d}.json"
    return fj.as_real_site({"writer": "spark-open", **json.loads(path.read_text())})


def v5_train(cache, public, reviewed):
    """(v5's train rows as rows, v5's train letters): the lines v5's starter trained on, and its letters (v3's and
    v5's new ones, by v5's manifest), each checked to have its as-written row among those lines."""
    split = json.loads((cache / "v5" / "split.json").read_text())
    lines = judge_v4.v3_train_lines(cache / "v5" / "judge_v5.jsonl", split)
    manifest = json.loads((cache / "v5" / "judge_v5.manifest.json").read_text())
    bases = []
    for writer, n in judge_v4.TRAIN_WRITERS.items():
        bases += fj.letters(cache / fj.WRITERS[writer][0], n, 0, False, public, reviewed, writer, 0)[0]
    for writer in judge_v5.NEW_TRAIN:
        low, high = manifest["seeds"][f"train {writer}"]
        dropped = manifest["rejected_letters"][f"train {writer}"]
        bases += [base(cache, writer, s) for s in range(low, high + 1) if str(s) not in dropped]
    have = set(lines)
    letters = {b["measured"]: b for b in bases}
    if len(lines) != V5_TRAIN_ROWS or len(bases) != 210 or len(letters) != 210 or any(
            fj.line(judge_v4.row(b, "", b["plan"]["letter"], [], "", "")) not in have for b in bases):
        raise SystemExit("judge_v6: v5's train file or letters are not what v5 trained on")
    rows = []
    for x in lines:
        messages = json.loads(x)["messages"]
        facts = messages[0]["content"].split("\nMEASUREMENTS:\n", 1)[1].split("\n\nLETTER:\n", 1)[0]
        b = letters[facts]
        rows.append({"kind": "v5 train row", "planted": pack.read_problems(messages[1]["content"]) != [],
                     "messages": messages, "writer": b["writer"], "seed": b["seed"], "k": "v5"})
    if [fj.line(r) for r in rows] != lines:
        raise SystemExit("judge_v6: v5's train lines do not read back unchanged")
    return rows, bases


def real_slips(cache):
    """The 32 rows adjudication found carrying a writer slip (generator clean, final planted) in v4's and v5's test,
    rebuilt with today's prompt, the adjudication note (less its prefix and references to other rows) the problem."""
    rows = []
    for v, name in REAL_SLIPS.items():
        labels = json.loads((REPO / "provenance" / f"glimmer-judge-lora-v{v}" / "labels-frozen.json").read_text())
        split = json.loads((cache / f"v{v}" / "split.json").read_text())
        lines = (cache / f"v{v}" / name).read_text().splitlines()
        random.Random(split["starter_seed"]).shuffle(lines)
        for r in labels["rows"]:
            if not r["final_planted"] or r["generator_planted"] or r["excluded"]:
                continue
            if split["holdout"][r["index"]]["id"] != r["id"]:
                raise SystemExit(f"judge_v6: v{v} row {r['index']} is not {r['id']}")
            content = json.loads(lines[r["index"]])["messages"][0]["content"]
            facts, letter = content.split("\nMEASUREMENTS:\n", 1)[1].split("\n\nLETTER:\n", 1)
            writer, seed, k = r["id"].split("/")
            b = {"writer": writer, "seed": int(seed), "measured": facts}
            rows.append({**judge_v4.row(b, "real writer slip (adjudicated)", letter, [NOTE_NOISE.sub("", r[
                "adjudication_note"])], "train", f"v{v}-{k}"), "source": f"v{v} row {r['index']}"})
    if len(rows) != 32:
        raise SystemExit(f"judge_v6: {len(rows)} adjudicated writer slips found, 32 expected")
    return rows


def longest_tokens(jsonl, tokenizer_dir):
    """The most tokens any row of `jsonl` takes in Glimmer's chat template."""
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(tokenizer_dir)
    return max(len(tok.apply_chat_template(json.loads(x)["messages"], tokenize=True, return_dict=False))
               for x in jsonl.read_text().splitlines())


def family(r):
    return ("v5 train rows" if r["k"] == "v5" else "real writer slip" if r["kind"].startswith("real")
            else "slip edit" if r["planted"] else "slip-edit control")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", required=True, help="glimmer-ft: the letter caches, reviewed.json, v4/, v5/")
    parser.add_argument("--cap", type=float, default=12.0, help="USD of new (v6) calls, every cached v6 call counted")
    parser.add_argument("--yes", action="store_true", help="pay for missing letters and edits")
    parser.add_argument("--letters-only", action="store_true", help="stop once the letters are gathered (to review)")
    parser.add_argument("--tokenizer", help="Glimmer's tokenizer folder: check every row fits MAX_TOKENS")
    args = parser.parse_args()
    cache, out = Path(args.dir), Path(args.dir) / "v6"
    out.mkdir(exist_ok=True)
    reviewed = json.loads((cache / "reviewed.json").read_text())
    key = pack.optional_key()
    if args.yes and not key:
        raise SystemExit("judge_v6: Muse Spark needs MODEL_API_KEY (environment or .env)")
    cap = judge_v4.all_spend(cache) - sum(v6_spend(cache).values()) + args.cap  # judge_v4.all_spend's frame
    public = fj.public_spans()

    v5_rows, train_bases = v5_train(cache, public, reviewed)
    real = real_slips(cache)
    texts = [(b["plan"]["letter"], b["measured"]) for b in train_bases] + [(r["letter"], r["measured"]) for r in real]
    train_spans = set().union(*(fj.spans(t) for t, _ in texts)) - set().union(*(fj.spans(m) for _, m in texts))
    rejected, test = {}, []
    for writer in ("spark-open", "spark"):
        got, rejected[f"test {writer}"] = judge_v5.gather(cache, writer, 130, cap, args.yes, public, reviewed, key,
                                                          FIRST, train_spans)
        test += got
        judge_v5.review_list(cache, writer, rejected[f"test {writer}"])
        print(f"test {writer}: {len(got)} usable, ${v6_spend(cache).get(writer, 0):.4f} spent on its v6 letters")
    if len(test) < 260:
        raise SystemExit(f"judge_v6: {len(test)} test letters usable, 260 wanted")
    if args.letters_only:
        return
    seeds = [b["seed"] for b in test]
    if len(set(seeds)) != len(seeds) or min(seeds) < FIRST:
        raise SystemExit("judge_v6: a letter's seed was used before")

    natural_records = judge_v5.edit_all(cache, test, args.yes, key, cap)
    if len(natural_records) < len(test):
        raise SystemExit(f"judge_v6: {len(test) - len(natural_records)} test letters have no natural edit")
    test_slips = slip_edit_all(cache, test, args.yes, key, args.cap)
    if len(test_slips) < len(test):
        raise SystemExit(f"judge_v6: {len(test) - len(test_slips)} test letters have no slip edit")
    train_slips = slip_edit_all(cache, train_bases, args.yes, key, args.cap)  # as many as the cap leaves

    slip_train, slip_train_report = slip_edit_rows(train_bases, train_slips, "train", True)
    natural, natural_report = natural_edits.natural_rows(test, natural_records)
    slip_test, slip_test_report = slip_edit_rows(test, test_slips, "test-slip-edit", False)
    held = ([judge_v4.row(b, "clean: as written", b["plan"]["letter"], [], "test-asis", "asis") for b in test]
            + judge_v4.template_rows(test) + [{**r, "set": f"test-{r['k']}"} for r in natural]
            + judge_v5.test_slip_rows(test) + slip_test)
    # an edit of a letter clear of the public bench can still join a 12-word span across its new sentence: that row
    # is dropped, like any edit that fails a check (its letter's other rows stay)
    near = {id(r): f"{r['writer']}/{r['seed']}/{r['k']}" for r in held + slip_train + real
            if fj.shared(r["letter"], r["measured"], public)}
    held, slip_train = [r for r in held if id(r) not in near], [r for r in slip_train if id(r) not in near]
    train = v5_rows + slip_train + real
    clean_share = sum(not r["planted"] for r in train) / len(train)
    if clean_share < judge_v5.MIN_CLEAN_SHARE:
        raise SystemExit(f"judge_v6: train clean share {clean_share:.3f} under {judge_v5.MIN_CLEAN_SHARE}")

    public_letters = {i["letter"] for i in json.loads(fj.judge_bench.PUBLIC.read_text())}
    train_lines = [fj.line(r) for r in train]
    overlap = {"rows_checked": len(held + slip_train + real) + len(near),
               "exact_copies": sum(r["letter"] in public_letters for r in held + slip_train + real),
               "edited_rows_dropped_for_a_12_word_span": sorted(near.values()),
               "held_lines_in_train": len({fj.line(r) for r in held} & set(train_lines))}
    if overlap["exact_copies"] or overlap["held_lines_in_train"] or any(id(r) in near for r in real):
        raise SystemExit(f"judge_v6: rows overlap the public bench or train: {overlap}")
    jsonl, split = fj.write_starter(train, held, test, out, "judge_v6", "test")
    lines = jsonl.read_text().splitlines()  # the starter's _prepare, replayed on the file as written
    random.Random(fj.STARTER_SEED).shuffle(lines)
    if lines[:split["n_eval"]] != [fj.line(r) for r in held + fj.public_rows()] or \
            sorted(lines[split["n_eval"]:]) != sorted(train_lines):
        raise SystemExit("judge_v6: the starter's shuffle does not hold out exactly the v6 test and public rows")
    tokens = longest_tokens(jsonl, args.tokenizer) if args.tokenizer else None
    if tokens and tokens >= MAX_TOKENS:
        raise SystemExit(f"judge_v6: a row takes {tokens} tokens, max_seq_len is {MAX_TOKENS}")

    by_family = {}
    for r in train:
        f = by_family.setdefault(family(r), {"planted": 0, "clean": 0})
        f["planted" if r["planted"] else "clean"] += 1
    share = [fj.train_share(b["plan"]["letter"], b["measured"], train_spans) for b in test]
    spend = v6_spend(cache)
    slipped = [r for r in held if r["set"] == "test-slip-edit"]
    summary = {"file": jsonl.name, "sha256": split["sha256"], "n_eval": split["n_eval"], "train_rows": split["train_rows"],
               "sets": split["sets"], "train_clean_share": round(clean_share, 3), "train_by_family": by_family,
               "train_letters_with_slip_edits": {"asked": len(train_slips), "of": len(train_bases),
                                                 "with_a_row": len({r["seed"] for r in slip_train})},
               "test_letters_by_writer": {w: sum(b["writer"] == w for b in test) for w in fj.WRITERS},
               "seeds": {f"test {w}": [min(s), max(s)] for w in fj.WRITERS
                         if (s := [b["seed"] for b in test if b["writer"] == w])},
               "slip_edits": {"train": slip_train_report, "test": slip_test_report,
                              "test quantities": {q: sum(r["slip_kind"] == q for r in slipped) for q in QUANTITIES},
                              "test rows pack.slips flags": sum(bool(pack.slips(r["letter"], json.loads(r["measured"])))
                                                                for r in slipped)},
               "test letters without a slip-edit row": len(test) - len(slipped),
               "real_writer_slips": [r["source"] for r in real],
               "code_slip_kinds": {k: sum(r.get("slip_kind") == k for r in held if r["set"] == "test-slip")
                                   for k in judge_v5.SLIP_KINDS},
               "rejections_by_reason": {g: {c: [judge_v4.category(r) for r in why.values()].count(c)
                                            for c in dict.fromkeys(map(judge_v4.category, why.values()))}
                                        for g, why in rejected.items()},
               "rejected_letters": {g: {str(s): r for s, r in why.items()} for g, why in rejected.items()},
               "template_kinds": {k: sum(r["kind"] == k for r in held if r["set"] == "test-template") for k in judge_v4.KINDS},
               "natural_edits": natural_report,
               "test_train_share": {"max": round(max(share), 3), "median": round(statistics.median(share), 3),
                                    "rule": f"under {fj.TRAIN_SHARE:.0%}"},
               "public_bench_overlap": overlap,
               "spend_usd": {**{k: round(v, 4) for k, v in spend.items()}, "total": round(sum(spend.values()), 4),
                             "cap": args.cap},
               "longest_row": {"chars": max(len(r["messages"][0]["content"]) for r in held + train),
                               "tokens": tokens, "max_seq_len": MAX_TOKENS},
               "reviewed": {str(b["seed"]): reviewed[str(b["seed"])] for b in test if str(b["seed"]) in reviewed},
               "data": "synthetic packs only (finetune_judge.synthetic_pack): no real video, no DUT, no SinD, no out/"}
    (out / "judge_v6.manifest.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("rejected_letters", "reviewed")}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
