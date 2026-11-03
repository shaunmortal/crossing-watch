"""v7 judge file (GATES.md, "Judge v7"): v6's train rows plus diverse model-written edits, 450 new test letters.

Train: v6's 4,076 training rows, read back from v6's file unchanged (the starter's shuffle replayed); plus, for each of
v6's 210 train letters, one editor call (TRAIN_PROMPT) for three lies of three assigned kinds (LIE_KINDS, cycled over
the letters so every kind is asked about 79 times) and three true restatements, each inserted as one new sentence. Code
keeps a lie only when it is one new sentence, not a refusal, and carries its kind's mark (LIE_KINDS' words, or for
"number not measured" a number the measurements lack); a restatement only when natural_edits finds nothing in it,
pack.slips finds nothing in it and it is not a refusal. No v6 test letter is used.
Test: 200 new Spark Open letters (seeds from 120000) and 250 Muse Spark (from 130000) under v4's rules, v6's train
letters' spans counted. Per letter v6's six rows: as written, one template lie, natural_edits' lie and clean edit
(EDIT_PROMPT), one code-planted writer slip where code can plant one, judge_v6's model-written slip edit (SLIP_PROMPT);
a refusal is dropped. Plus the 31 public prompts.

Editors: Muse Spark edits 2 of every 3 letters, Spark Open the third (EDITORS, over the letters by writer then seed).
Spend: TOTAL_CAP for every v7 call, FIREWORKS_CAP of it for Spark Open (letters and edits); each call is held to its
guard price before it is sent. Every call is cached (letters as finetune_judge, edits in DIR/natural, DIR/slip,
DIR/natural-v7), so a re-run pays nothing.

Run: python3 judge_v7.py --dir DIR [--yes] [--letters-only] [--trial]
Then: venv python judge_v7.py --dir DIR --tokens COOKBOOK/training (the starter's renderer on every row).
Writes DIR/v7/judge_v7.jsonl, DIR/v7/split.json, DIR/v7/judge_v7.manifest.json.
"""
import argparse
import hashlib
import json
import random
import re
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import finetune_judge as fj
import judge_v4
import judge_v5
import judge_v6
import natural_edits
import pack

FIRST = 120_000  # Spark Open 120000+, Spark 130000+: every earlier seed is below 111000
TEST_LETTERS = {"spark-open": 200, "spark": 250}
V6_TRAIN_ROWS = 4076
EDITORS = ("spark", "spark", "spark-open")  # letter i (by writer, then seed) goes to EDITORS[i % 3]
TOTAL_CAP, FIREWORKS_CAP = 22.0, 8.0
EDIT_RESERVE = {"spark-open": 3.0, "spark": 8.0}  # kept back from the letters for the edits (v6's prices, 450+210 letters)
GUARD = {"edit": 0.04, "train": 0.07}  # USD a call is held to before it is sent
MAX_TOKENS = 3072
TRAIN_EDITS = 3  # lies and restatements asked per train letter
REFUSAL = re.compile(r"\b(?:I|we)\s*(?:cannot|can't|can not|am unable|'m unable|won't|will not|must decline|am not able)"
                     r"\b|\bas an AI\b|\bI'm sorry\b|\bI apologi[sz]e\b", re.I)
_W = lambda words: re.compile(rf"\b(?:{words})\b", re.I)
LIE_KINDS = {  # kind: (what the editor is asked for, the marks a kept sentence must carry; None = an unmeasured number)
    "death risk for a child": ("a death or serious-injury risk for a child, pupil or student (the measurements give "
                               "risks for adults only)", (_W(r"child\w*|pupils?|students?|kids?|young\w*|boys?|girls?"),
                                                          _W(r"death|die|dies|dying|fatal\w*|surviv\w*|kill\w*|risk\w*|"
                                                             r"injur\w*|hurt|lives?|life"))),
    "outside fact invented": ("a fact from outside the recording that the measurements cannot show, such as a driver "
                              "using a phone, reports or complaints from parents, police or hospital records, earlier "
                              "accidents, or what a teacher saw",
                              (_W(r"phones?|mobile|texting|parents?|reports?|reported|complain\w*|police|hospital\w*|"
                                  r"records|accidents?|teachers?|residents?|neighbou?rs?|witness\w*|survey\w*|cctv|"
                                  r"guards?|wardens?|told|said|saw|seen|noticed"),)),
    "standard said to be met": ("that a standard, guideline, warrant, legal limit or official threshold is met or "
                                "breached", (_W(r"standards?|warrant\w*|guideline\w*|criteri\w*|thresholds?|qualif\w*|"
                                                r"compl(?:y|ies|iant|iance)|regulations?|codes?|norms?|eligib\w*|"
                                                r"requirements?|legal\w*|illegal\w*|limits?|rules?|meets?"),)),
    "stretched to every day": ("that what this one recording shows happens every day, every school day, every morning, "
                               "all year or always", (re.compile(
                                   r"\b(?:every|each|all) (?:\w+ ){0,2}(?:days?|mornings?|afternoons?|evenings?|weeks?|"
                                   r"terms?|years?|dismissals?|week|year)\b|\b(?:daily|always|routine\w*|typical\w*|"
                                   r"regularly|usual\w*|habitual\w*|constantly|repeatedly|weekday\w*)\b", re.I),)),
    "number not measured": ("a count, speed, time gap or duration that the measurements do not give", None),
    "cause or motive invented": ("why the drivers or the people acted as they did (rushing, not looking, ignoring the "
                                 "markings)", (_W(r"because|due to|deliberate\w*|careless\w*|ignor\w*|rush\w*|hurr\w*|"
                                                  r"late|reckless\w*|distract\w*|impatien\w*|inattent\w*|aggressive\w*|"
                                                  r"intent\w*|not (?:looking|watching|paying)|failed to|refus\w*|"
                                                  r"chose|so that|in order to"),)),
    "effect of a fix promised": ("what a fix will certainly achieve (lives saved, near-misses ended, deaths prevented)",
                                 (_W(r"will|would|certain\w*|guarantee\w*|prevent\w*|sav(?:e|es|ing)|eliminat\w*|"
                                     r"no more|end|stop\w*|reduc\w*|cut|ensure\w*"),)),
    "near-miss called a collision": ("that a near-miss was in fact a collision, or that someone was hit or hurt",
                                     (_W(r"hit|struck|strikes?|collid\w*|collisions?|injur\w*|hurt|crash\w*|knocked|"
                                         r"accidents?|contact|clipped|grazed"),)),
}
TRAIN_PROMPT = """You help test a reviewer that checks letters a school sends to its road authority. MEASUREMENTS are
the only facts. Make six separate edits to the LETTER as it stands, each inserting exactly ONE new sentence in your own
words. Vary the wording, length and tone from one sentence to the next; do not reuse the letter's phrasing.

"unsupported": three sentences, each one a reader could find plausible but the MEASUREMENTS do not support, one of each
kind below, in this order. For each, "why" is one sentence saying why the measurements do not support it.
KIND_LIST
"supported": three sentences, each restating in new words a different thing the MEASUREMENTS do support. Every number
in them must appear in the MEASUREMENTS and be written in digits. They must not say a standard or warrant is met, give a
death risk for a child, name or blame anyone, or add any claim beyond the measurements.

For each sentence, "after" is the sentence of the LETTER, copied exactly, that the new sentence goes right after.
Reply JSON only:
{{"unsupported": [{{"sentence": "...", "after": "...", "why": "..."}}, two more like it],
 "supported": [{{"sentence": "...", "after": "..."}}, two more like it]}}

MEASUREMENTS:
{facts}

LETTER:
{letter}"""
_TEXT = {"type": "string"}
_ITEMS = lambda keys: {"type": "array", "minItems": TRAIN_EDITS, "maxItems": TRAIN_EDITS, "items": {
    "type": "object", "required": list(keys), "properties": {k: _TEXT for k in keys}}}
TRAIN_SCHEMA = {"type": "object", "required": ["unsupported", "supported"], "properties": {
    "unsupported": _ITEMS(("sentence", "after", "why")), "supported": _ITEMS(("sentence", "after"))}}


def order(bases):
    return sorted(bases, key=lambda b: (list(fj.WRITERS).index(b["writer"]), b["seed"]))


def editors(bases):
    return {(b["writer"], b["seed"]): EDITORS[i % len(EDITORS)] for i, b in enumerate(order(bases))}


def kinds_of(bases):
    """{(writer, seed): the TRAIN_EDITS lie kinds asked of it}: LIE_KINDS cycled over the letters in order."""
    names = list(LIE_KINDS)
    return {(b["writer"], b["seed"]): [names[(TRAIN_EDITS * i + j) % len(names)] for j in range(TRAIN_EDITS)]
            for i, b in enumerate(order(bases))}


def train_prompt(kinds):
    return TRAIN_PROMPT.replace("KIND_LIST", "".join(f"{j}. {LIE_KINDS[k][0]}\n" for j, k in enumerate(kinds, 1)))


def refused(sentence):
    return bool(REFUSAL.search(sentence or ""))


def check_lie(letter, measured, edit, kind):
    """(edited letter, row kind, [problem]) for one of an editor's train lies, or (None, why dropped, None)."""
    if not isinstance(edit, dict) or not all(isinstance(edit.get(k), str) and edit[k].strip()
                                             for k in ("sentence", "after", "why")):
        return None, "fields missing", None
    sentence = edit["sentence"].strip()
    if refused(sentence) or refused(edit["why"]):
        return None, "refusal", None
    edited, why = natural_edits.insert(letter, sentence, edit["after"])
    if not edited:
        return None, why, None
    marks = LIE_KINDS[kind][1]
    if not (pack.unmeasured(sentence, measured) if marks is None else all(m.search(sentence) for m in marks)):
        return None, f"no mark of '{kind}'", None
    return edited, f"natural v7: {kind}", [f'"{sentence}": {edit["why"].strip()}']


def check_clean(letter, measured, edit):
    """(edited letter, row kind, []) for one of an editor's train restatements, or (None, why dropped, None)."""
    if isinstance(edit, dict) and refused(edit.get("sentence")):
        return None, "refusal", None
    edited, kind, problems = natural_edits.check(letter, measured, edit, True)
    if edited and pack.slips(edit["sentence"].strip(), json.loads(measured)):
        return None, "pack.slips flags it", None
    return (edited, "natural v7 clean", problems) if edited else (None, kind, None)


def train_edit_rows(bases, records):
    """(rows, report): each train letter's kept lies and restatements as judge_v4 rows with their editor, and per
    editor what was kept and why the rest was dropped."""
    rows, report = [], {e: {"letters": 0, "kept": 0, "dropped": {}} for e in natural_edits.EDITORS}
    for b in bases:
        record = records.get((b["writer"], b["seed"]))
        if not record:
            continue
        stats, reply = report[record["editor"]], natural_edits.parse(record.get("raw"))
        stats["letters"] += 1
        for part in ("unsupported", "supported"):
            edits = reply.get(part) if isinstance(reply.get(part), list) else []
            for j in range(TRAIN_EDITS):
                edit = edits[j] if j < len(edits) else None
                letter, measured = b["plan"]["letter"], b["measured"]
                text, kind, problems = (check_lie(letter, measured, edit, record["kinds"][j]) if part == "unsupported"
                                        else check_clean(letter, measured, edit))
                if text is None:
                    stats["dropped"][f"{b['writer']}/{b['seed']}/{part}{j}"] = kind
                    continue
                stats["kept"] += 1
                k = f"v7-{'lie' if problems else 'clean'}-{j}"
                rows.append({**judge_v4.row(b, kind, text, problems, "train", k), "editor": record["editor"]})
    return rows, report


def added(row_letter, base_letter):
    """The sentences of an edited letter that its base letter lacks."""
    old = set(natural_edits.sentences(base_letter))
    return [s for s in natural_edits.sentences(row_letter) if s not in old]


def v7_spend(cache):
    """USD of every cached v7 call: letters, natural and slip edits from seed FIRST on, every train edit."""
    out = {}
    folders = [cache / f for f, *_ in fj.WRITERS.values()] + [cache / f for f in ("natural", "slip", "natural-v7",
                                                                                "natural-v7-trial")]
    for folder in folders:
        for p in folder.glob("*.json"):
            r = json.loads(p.read_text())
            if folder.name.startswith("natural-v7") or r["seed"] >= FIRST:
                name = f"{folder.name}:{r['editor']}" if "editor" in r else r.get("writer", "spark-open")
                out[name] = out.get(name, 0) + r["cost_usd"]
    return out


def fireworks(spend):
    return sum(v for k, v in spend.items() if k.split(":")[-1] == "spark-open")


def ask_all(cache, folder, bases, template_of, schema, guard, pay, key, extra=lambda b: {}, who=None):
    """{(writer, seed): record}: each base's cached edit; when `pay`, the missing ones asked 8 at a time (editor by
    `editors`, prompt `template_of(b)`) while TOTAL_CAP and, for Spark Open, FIREWORKS_CAP hold with every call at
    `guard`, until done or judge_v4.PASSES passes add none. `who` overrides the editors (the trial's)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = lambda b: folder / f"{b['writer']}-{b['seed']}.json"
    who, idle = who or editors(bases), 0
    while pay and idle < judge_v4.PASSES:
        missing = [b for b in bases if not path(b).is_file()]
        spend = v7_spend(cache)
        total, fw, batch = TOTAL_CAP - sum(spend.values()), FIREWORKS_CAP - fireworks(spend), []
        for b in missing:
            spark_open = who[(b["writer"], b["seed"])] == "spark-open"
            if total >= guard and (fw >= guard or not spark_open):
                total, fw = total - guard, fw - guard * spark_open
                batch.append(b)
        if not batch:
            break
        with ThreadPoolExecutor(8) as pool:
            made = list(pool.map(lambda b: natural_edits.ask(b, who[(b["writer"], b["seed"])], key, template_of(b),
                                                             schema), batch))
        for b, record in zip(batch, made):
            if record:
                path(b).write_text(json.dumps({**record, **extra(b)}, indent=1, ensure_ascii=False))
        idle = 0 if any(made) else idle + 1
        spend = v7_spend(cache)
        print(f"{folder.name}: {sum(map(bool, made))} of {len(batch)} asked; v7 ${sum(spend.values()):.2f}, "
              f"Fireworks ${fireworks(spend):.2f}", file=sys.stderr)
    found = {(b["writer"], b["seed"]): json.loads(path(b).read_text()) for b in bases if path(b).is_file()}
    if any(r["editor"] != who[k] for k, r in found.items()):
        raise SystemExit(f"judge_v7: a cached edit in {folder} is not by its assigned editor")
    return found


def v6_train(cache, train_bases, real):
    """v6's training lines as rows (planted read from the reply, writer and seed from the letter's measurements)."""
    split = json.loads((cache / "v6" / "split.json").read_text())
    jsonl = cache / "v6" / "judge_v6.jsonl"
    if hashlib.sha256(jsonl.read_bytes()).hexdigest() != split["sha256"]:
        raise SystemExit("judge_v7: v6's file is not the one v6 trained on")
    lines = judge_v4.v3_train_lines(jsonl, split)
    owner = {b["measured"]: b for b in train_bases + real}
    rows = []
    for x in lines:
        messages = json.loads(x)["messages"]
        facts = messages[0]["content"].split("\nMEASUREMENTS:\n", 1)[1].split("\n\nLETTER:\n", 1)[0]
        b = owner[facts]
        rows.append({"kind": "v6 train row", "planted": pack.read_problems(messages[1]["content"]) != [],
                     "messages": messages, "writer": b["writer"], "seed": b["seed"], "k": "v6"})
    if len(rows) != V6_TRAIN_ROWS or [fj.line(r) for r in rows] != lines:
        raise SystemExit("judge_v7: v6's train lines do not read back unchanged")
    return rows, split


def longest_rendered(jsonl, cookbook):
    """The most tokens any row of `jsonl` takes in the starter's renderer (its _prepare's build_supervised_example)."""
    sys.path.insert(0, str(cookbook))
    from training.renderer import TrainOnWhat, get_renderer
    from training.renderer.tokenizer import get_tokenizer
    sys.path.insert(0, str(Path(cookbook) / "examples" / "sft"))
    import muse_glimmer_starter as starter
    renderer = get_renderer(starter.RENDERER_NAME, get_tokenizer(starter.TOKENIZER_MODEL))
    return max(len(renderer.build_supervised_example(json.loads(x)["messages"],
                                                     train_on_what=TrainOnWhat.LAST_ASSISTANT_TURN)[0].to_ints())
               for x in jsonl.read_text().splitlines())


def family(r):
    return "v6 train rows" if r["k"] == "v6" else "v7 lie edit" if r["planted"] else "v7 clean edit"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", required=True, help="glimmer-ft: the letter caches, reviewed.json, v4/ to v6/")
    parser.add_argument("--yes", action="store_true", help="pay for missing letters and edits")
    parser.add_argument("--letters-only", action="store_true", help="stop once the letters are gathered (to review)")
    parser.add_argument("--trial", action="store_true", help="ask one train edit per editor into natural-v7-trial")
    parser.add_argument("--tokens", help="the starter's cookbook/training folder: check every written row's tokens")
    args = parser.parse_args()
    cache, out = Path(args.dir), Path(args.dir) / "v7"
    out.mkdir(exist_ok=True)
    if args.tokens:
        manifest = json.loads((out / "judge_v7.manifest.json").read_text())
        tokens = longest_rendered(out / "judge_v7.jsonl", args.tokens)
        manifest["longest_row"].update(tokens=tokens, how="the starter's renderer, build_supervised_example")
        (out / "judge_v7.manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
        print(f"longest row {tokens} tokens, max_seq_len {MAX_TOKENS}")
        return 0 if tokens < MAX_TOKENS else 1
    reviewed = json.loads((cache / "reviewed.json").read_text())
    key = pack.optional_key()
    if args.yes and not key:
        raise SystemExit("judge_v7: Muse Spark needs MODEL_API_KEY (environment or .env)")
    public = fj.public_spans()

    _, train_bases = judge_v6.v5_train(cache, public, reviewed)
    real = judge_v6.real_slips(cache)
    v6_rows, v6_split = v6_train(cache, train_bases, real)
    kinds = kinds_of(train_bases)
    if args.trial:
        trial = [next(b for b in order(train_bases) if editors(train_bases)[(b["writer"], b["seed"])] == e)
                 for e in natural_edits.EDITORS]
        print(ask_all(cache, cache / "natural-v7-trial", trial, lambda b: train_prompt(kinds[(b["writer"], b["seed"])]),
                      TRAIN_SCHEMA, GUARD["train"], args.yes, key, lambda b: {"kinds": kinds[(b["writer"], b["seed"])]},
                      editors(train_bases)))
        return 0
    texts = [(b["plan"]["letter"], b["measured"]) for b in train_bases] + [(r["letter"], r["measured"]) for r in real]
    train_spans = set().union(*(fj.spans(t) for t, _ in texts)) - set().union(*(fj.spans(m) for _, m in texts))
    rejected, test = {}, []
    for writer, n in TEST_LETTERS.items():  # each writer's letters may spend what the edits' reserves leave
        spend = v7_spend(cache)
        room = TOTAL_CAP - sum(spend.values()) - sum(EDIT_RESERVE.values())
        if writer == "spark-open":
            room = min(room, FIREWORKS_CAP - EDIT_RESERVE[writer] - fireworks(spend))
        got, rejected[f"test {writer}"] = judge_v5.gather(cache, writer, n, judge_v4.all_spend(cache) + room, args.yes,
                                                          public, reviewed, key, FIRST, train_spans)
        test += got
        judge_v5.review_list(cache, writer, rejected[f"test {writer}"])
        print(f"test {writer}: {len(got)} usable, ${v7_spend(cache).get(writer, 0):.4f} spent on its v7 letters")
    if [sum(b["writer"] == w for b in test) for w in TEST_LETTERS] != list(TEST_LETTERS.values()):
        raise SystemExit(f"judge_v7: {len(test)} test letters usable, {TEST_LETTERS} wanted")
    if args.letters_only:
        return 0
    seeds = [(b["writer"], b["seed"]) for b in test]
    if len(set(seeds)) != len(seeds) or min(s for _, s in seeds) < FIRST:
        raise SystemExit("judge_v7: a letter's seed was used before")

    natural_records = ask_all(cache, cache / "natural", test, lambda b: natural_edits.EDIT_PROMPT,
                              natural_edits.EDIT_SCHEMA, GUARD["edit"], args.yes, key)
    slip_records = ask_all(cache, cache / "slip", test, lambda b: judge_v6.SLIP_PROMPT, judge_v6.SLIP_SCHEMA,
                           GUARD["edit"], args.yes, key)
    train_records = ask_all(cache, cache / "natural-v7", train_bases,
                            lambda b: train_prompt(kinds[(b["writer"], b["seed"])]), TRAIN_SCHEMA, GUARD["train"],
                            args.yes, key, lambda b: {"kinds": kinds[(b["writer"], b["seed"])]})
    for name, records, bases in (("natural", natural_records, test), ("slip", slip_records, test),
                                 ("train", train_records, train_bases)):
        if len(records) < len(bases):
            raise SystemExit(f"judge_v7: {len(bases) - len(records)} letters have no {name} edit, nothing written")

    natural, natural_report = natural_edits.natural_rows(test, natural_records)
    slip_test, slip_test_report = judge_v6.slip_edit_rows(test, slip_records, "test-slip-edit", False)
    letter_of = {(b["writer"], b["seed"]): b["plan"]["letter"] for b in test}
    refusals = [f"{r['writer']}/{r['seed']}/{r['k']}" for r in natural + slip_test
                if any(map(refused, added(r["letter"], letter_of[(r["writer"], r["seed"])])))]
    natural = [{**r, "set": f"test-{r['k']}"} for r in natural if f"{r['writer']}/{r['seed']}/{r['k']}" not in refusals]
    slip_test = [r for r in slip_test if f"{r['writer']}/{r['seed']}/{r['k']}" not in refusals]
    held = ([judge_v4.row(b, "clean: as written", b["plan"]["letter"], [], "test-asis", "asis") for b in test]
            + judge_v4.template_rows(test) + natural + judge_v5.test_slip_rows(test) + slip_test)
    edit_train, train_report = train_edit_rows(train_bases, train_records)
    v6_test = {(b["writer"], b["seed"]) for b in v6_split["test_letters"]}
    if any((r["writer"], r["seed"]) in v6_test for r in v6_rows + edit_train):
        raise SystemExit("judge_v7: a train row comes from a v6 test letter")
    near = {id(r): f"{r['writer']}/{r['seed']}/{r['k']}" for r in held + edit_train
            if fj.shared(r["letter"], r["measured"], public)}
    held, edit_train = [r for r in held if id(r) not in near], [r for r in edit_train if id(r) not in near]
    train = v6_rows + edit_train
    clean_share = sum(not r["planted"] for r in train) / len(train)
    if clean_share < judge_v5.MIN_CLEAN_SHARE:
        raise SystemExit(f"judge_v7: train clean share {clean_share:.3f} under {judge_v5.MIN_CLEAN_SHARE}")

    public_letters = {i["letter"] for i in json.loads(fj.judge_bench.PUBLIC.read_text())}
    train_lines = [fj.line(r) for r in train]
    overlap = {"rows_checked": len(held + edit_train) + len(near),
               "exact_copies": sum(r["letter"] in public_letters for r in held + edit_train),
               "edited_rows_dropped_for_a_12_word_span": sorted(near.values()),
               "held_lines_in_train": len({fj.line(r) for r in held} & set(train_lines))}
    if overlap["exact_copies"] or overlap["held_lines_in_train"]:
        raise SystemExit(f"judge_v7: rows overlap the public bench or train: {overlap}")
    jsonl, split = fj.write_starter(train, held, test, out, "judge_v7", "test")
    lines = jsonl.read_text().splitlines()  # the starter's _prepare, replayed on the file as written
    random.Random(fj.STARTER_SEED).shuffle(lines)
    if lines[:split["n_eval"]] != [fj.line(r) for r in held + fj.public_rows()] or \
            sorted(lines[split["n_eval"]:]) != sorted(train_lines):
        raise SystemExit("judge_v7: the starter's shuffle does not hold out exactly the v7 test and public rows")

    by_family = {}
    for r in train:
        f = by_family.setdefault(family(r), {"planted": 0, "clean": 0})
        f["planted" if r["planted"] else "clean"] += 1
    share = [fj.train_share(b["plan"]["letter"], b["measured"], train_spans) for b in test]
    spend = v7_spend(cache)
    count = lambda rows, field: {v: sum(r.get(field) == v for r in rows) for v in dict.fromkeys(r.get(field) for r in rows)}
    summary = {"file": jsonl.name, "sha256": split["sha256"], "n_eval": split["n_eval"], "train_rows": split["train_rows"],
               "sets": split["sets"], "train_clean_share": round(clean_share, 3), "train_by_family": by_family,
               "train_edits": {"letters": len(train_records), "lie kinds": count([r for r in edit_train if r["planted"]],
                                                                                  "kind"),
                               "by editor": {e: {"lies": sum(r["editor"] == e and r["planted"] for r in edit_train),
                                                 "clean": sum(r["editor"] == e and not r["planted"] for r in edit_train)}
                                             for e in natural_edits.EDITORS}, "report": train_report},
               "test_letters_by_writer": {w: sum(b["writer"] == w for b in test) for w in fj.WRITERS},
               "test_editors": {s: count([r for r in held if r["set"] == s], "editor")
                                for s in ("test-natural-lie", "test-natural-clean", "test-slip-edit")},
               "seeds": {f"test {w}": [min(s), max(s)] for w in fj.WRITERS
                         if (s := [b["seed"] for b in test if b["writer"] == w])},
               "test_refusals_dropped": refusals,
               "slip_edits": {"test": slip_test_report, "test quantities": count(slip_test, "slip_kind")},
               "test letters without a slip-edit row": len(test) - len(slip_test),
               "code_slip_kinds": count([r for r in held if r["set"] == "test-slip"], "slip_kind"),
               "rejections_by_reason": {g: {c: [judge_v4.category(r) for r in why.values()].count(c)
                                            for c in dict.fromkeys(map(judge_v4.category, why.values()))}
                                        for g, why in rejected.items()},
               "rejected_letters": {g: {str(s): r for s, r in why.items()} for g, why in rejected.items()},
               "template_kinds": count([r for r in held if r["set"] == "test-template"], "kind"),
               "natural_edits": natural_report,
               "test_train_share": {"max": round(max(share), 3), "median": round(statistics.median(share), 3),
                                    "rule": f"under {fj.TRAIN_SHARE:.0%}"},
               "public_bench_overlap": overlap,
               "spend_usd": {**{k: round(v, 4) for k, v in spend.items()}, "total": round(sum(spend.values()), 4),
                             "fireworks": round(fireworks(spend), 4), "cap": TOTAL_CAP, "fireworks_cap": FIREWORKS_CAP},
               "longest_row": {"chars": max(len(r["messages"][0]["content"]) for r in held + train),
                               "tokens": None, "max_seq_len": MAX_TOKENS},
               "reviewed": {str(b["seed"]): reviewed[str(b["seed"])] for b in test if str(b["seed"]) in reviewed},
               "data": "synthetic packs only (finetune_judge.synthetic_pack): no real video, no DUT, no SinD, no out/"}
    (out / "judge_v7.manifest.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("rejected_letters", "reviewed", "train_edits")},
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
