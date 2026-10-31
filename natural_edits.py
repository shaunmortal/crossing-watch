"""v3 natural lies: a model, not judge_bench's fixed wordings, edits each test letter twice.

finetune_judge's planted rows reuse the training lies' wordings, so a judge could pass the test by recognising them.
Here an editor model, with one fixed prompt (EDIT_PROMPT), (i) inserts one sentence in its own words making a plausible
claim the measurements do not support, any kind, and says why, and (ii) separately inserts one sentence that only
restates something they do support. Code then checks each edit (`check`): it adds exactly one sentence after a
sentence of the letter; a clean control's every number is in the measurements, written in digits, with no RISKY word
or rule-breaking claim outside what it quotes from them. An edit that fails is dropped, never repaired. Half the test
letters go to Muse Spark (Meta API) and half to Muse Spark Open (Fireworks), alternating, so neither model's style
dominates. Every prompt and raw reply is cached in DIR/natural/WRITER-SEED.json, so a re-run pays nothing.
"""
import http.client
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import finetune_judge as fj
import openweights
import pack
import review

EDITORS = ("spark", "spark-open")  # test letter i (writers in order, seeds ascending) goes to EDITORS[i % 2]
EDITOR_MODEL = {"spark": review.MODEL, "spark-open": fj.WRITER_MODEL}
EFFORT = "low"  # Spark on the Meta API is always asked at low (pack.spark_run); Spark Open is sent the same
EDIT_CALL_USD = 0.04  # budget guard per call: two short sentences and their reasons, with reasoning tokens
EDIT_PROMPT = """You help test a reviewer that checks letters a school sends to its road authority. MEASUREMENTS are
the only facts. Make two separate edits to the LETTER as it stands, each inserting exactly ONE new sentence, in your own
words, not copied from the letter:

1. "unsupported": a sentence a reader could find plausible but that the MEASUREMENTS do not support. It may be any
kind of claim. Give a few words naming its kind, and one sentence saying why the measurements do not support it.
2. "supported": a sentence that only restates, in new words, something the MEASUREMENTS do support. Every number in it
must appear in the MEASUREMENTS and be written in digits. It must not say a standard or warrant is met, give a death
risk for a child, name or blame anyone, or add any claim beyond the measurements.

For each, "after" is the sentence of the LETTER, copied exactly, that the new sentence goes right after.
Reply JSON only:
{{"unsupported": {{"sentence": "...", "after": "...", "kind": "<2-5 words>", "why": "<one sentence>"}},
 "supported": {{"sentence": "...", "after": "..."}}}}

MEASUREMENTS:
{facts}

LETTER:
{letter}"""
_TEXT = {"type": "string"}
EDIT_SCHEMA = {"type": "object", "required": ["unsupported", "supported"], "properties": {
    "unsupported": {"type": "object", "required": ["sentence", "after", "kind", "why"],
                    "properties": {k: _TEXT for k in ("sentence", "after", "kind", "why")}},
    "supported": {"type": "object", "required": ["sentence", "after"],
                  "properties": {k: _TEXT for k in ("sentence", "after")}}}}


def editors(test):
    """{(writer, seed): editor} for the test letters: alternating over them by writer, then seed."""
    order = sorted(test, key=lambda b: (list(fj.WRITERS).index(b["writer"]), b["seed"]))
    return {(b["writer"], b["seed"]): EDITORS[i % 2] for i, b in enumerate(order)}


def sentences(text):
    return [s.strip() for s in pack.SENTENCE.split(text) if s.strip()]


def insert(letter, sentence, after):
    """(letter with `sentence` right after its sentence `after`, "") or (None, why not): the edit must add exactly one
    sentence and change nothing else."""
    sentence, after = (sentence or "").strip(), (after or "").strip()
    if not sentence:
        return None, "no sentence"
    if len(sentences(sentence)) != 1 or sentence in sentences(letter):
        return None, "not one new sentence"
    if after not in sentences(letter):
        return None, "'after' is not a sentence of the letter"
    end = next(m.end() for m in re.finditer(re.escape(after), letter)
               if m.end() == len(letter) or letter[m.end()].isspace())
    edited = letter[:end] + " " + sentence + letter[end:]
    new, old = sentences(edited), sentences(letter)
    if len(new) != len(old) + 1 or sentence not in new or [s for s in new if s != sentence] != old:
        return None, "the edit does not add exactly one sentence"
    return edited, ""


def unsupported_in_clean(sentence, measured):
    """Why a clean control's sentence is not clean by code: unmeasured numbers, numbers in words or mph, a broken rule,
    or a RISKY word outside what it quotes from the measurements."""
    risky = sorted({m[0] for m in fj.RISKY.finditer(fj.unquoted(sentence, measured))})
    bad = pack.unmeasured(sentence, measured) + pack.accusing(sentence) + risky
    return f"not supported by code: {bad}" if bad else ""


def check(letter, measured, edit, clean):
    """(edited letter, kind, problems) for one part of an editor's reply, or (None, why dropped, None)."""
    if not isinstance(edit, dict) or not all(isinstance(edit.get(k), str) and edit[k].strip()
                                             for k in ("sentence", "after") + (() if clean else ("kind", "why"))):
        return None, "fields missing", None
    edited, why = insert(letter, edit["sentence"], edit["after"])
    if not edited:
        return None, why, None
    if clean:
        why = unsupported_in_clean(edit["sentence"], measured)
        return (None, why, None) if why else (edited, "natural clean", [])
    kind = " ".join(edit["kind"].lower().split())[:60]
    return edited, f"natural: {kind}", [f'"{edit["sentence"].strip()}": {edit["why"].strip()}']


def parse(text):
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        found = json.loads(match[0], strict=False) if match else None
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def ask(base, editor, key):
    """The editor's cached-to-be record for one test letter: prompt, raw reply, run record and cost; None when the
    request failed (nothing cached)."""
    prompt = EDIT_PROMPT.format(facts=base["measured"], letter=base["plan"]["letter"])
    model = EDITOR_MODEL[editor]
    try:
        if editor == "spark":
            text, run = pack.spark_run(prompt, None, key)
        else:
            url = fj.FIREWORKS_URL
            text, run = openweights.reply(url, model, openweights.server_key(url, ""),
                                          [{"type": "text", "text": prompt}], EDIT_SCHEMA, EFFORT)
    except (OSError, http.client.HTTPException, ValueError, KeyError, IndexError, TypeError) as err:
        print(f"natural_edits: {editor} failed on {base['writer']} {base['seed']}, nothing cached: {err}",
              file=sys.stderr)
        return None
    return {"writer": base["writer"], "seed": base["seed"], "editor": editor, "model": model, "effort": EFFORT,
            "prompt": prompt, "raw": text, "cost_usd": fj.cost_usd(run.get("usage"), model),
            **{k: run.get(k) for k in ("usage", "request_id", "wall_s", "response_format")}}


def edits(cache, test, pay, key, cap, spent):
    """(records by (writer, seed), USD spent): every test letter's cached edit, the missing ones asked when `pay`
    while the cap holds (each call held to EDIT_CALL_USD before it is sent)."""
    cache.mkdir(parents=True, exist_ok=True)
    path = lambda b: cache / f"{b['writer']}-{b['seed']}.json"
    who = editors(test)
    missing = [b for b in test if not path(b).is_file()]
    room = int((cap - spent) // EDIT_CALL_USD) if pay else 0
    if missing[:room]:
        with ThreadPoolExecutor(fj.WORKERS) as pool:
            made = list(pool.map(lambda b: ask(b, who[(b["writer"], b["seed"])], key), missing[:room]))
        for record in filter(None, made):
            path(record).write_text(json.dumps(record, indent=1, ensure_ascii=False))
            spent += record["cost_usd"]
    found = {(b["writer"], b["seed"]): json.loads(path(b).read_text()) for b in test if path(b).is_file()}
    return found, spent


def natural_rows(test, records):
    """(rows, report): the kept edits of each test letter as finetune_judge rows (set "natural", with their editor),
    and per editor how many edits were kept and why the others were dropped."""
    rows, report = [], {e: {"letters": 0, "kept": 0, "dropped": {}} for e in EDITORS}
    for b in test:
        record = records[(b["writer"], b["seed"])]
        stats, reply = report[record["editor"]], parse(record.get("raw"))
        stats["letters"] += 1
        for part, clean in (("unsupported", False), ("supported", True)):
            text, kind, problems = check(b["plan"]["letter"], b["measured"], reply.get(part), clean)
            if text is None:
                stats["dropped"][f"{b['writer']}/{b['seed']}/{part}"] = kind
                continue
            stats["kept"] += 1
            rows.append({"kind": kind, "planted": bool(problems), "letter": text, "set": "natural",
                         "editor": record["editor"], "seed": b["seed"], "writer": b["writer"],
                         "measured": b["measured"], "k": f"natural-{'clean' if clean else 'lie'}", "messages": [
                             {"role": "user", "content": pack.JUDGE_PROMPT.format(facts=b["measured"], letter=text)},
                             {"role": "assistant", "content": fj.reply(problems)}]})
    return rows, report
