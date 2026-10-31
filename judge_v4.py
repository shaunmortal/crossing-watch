"""v4 judge file (GATES.md, "Fine-tuned Glimmer judge v4"): v3's 1,800 train rows unchanged, 200 new test letters.

Spark Open (Fireworks) and Muse Spark (Meta API) each write 100 usable test letters on fresh seeds (Spark Open's from
40000, Spark's from 50000; v1-v3 stopped at 20019 and 30068) under v3's rejection rules (finetune_judge.rejection with
the train letters' spans). Each letter gives four held-out rows: as written (clean, "test-asis"); one template lie
("test-template", the kind the fewest letters have had so far among those it can carry, ties in KINDS order); and
natural_edits' model-written lie and clean edit ("test-natural-lie", "test-natural-clean"; one edit call per letter,
editor alternating Spark / Spark Open; an edit failing natural_edits.check is dropped and recorded). The train rows are
rebuilt from v3's 150 train letters and must equal, byte for byte, the TRAIN rows of v3/judge_v3.jsonl (the starter's
Random(0) shuffle replayed). Every call is cached as in finetune_judge, so a re-run pays nothing.

Run: python3 judge_v4.py --dir DIR [--letters 100] [--cap 8] [--yes]
DIR holds v3's caches and reviewed.json; writes DIR/v4/judge_v4.jsonl, DIR/v4/split.json, DIR/v4/judge_v4.manifest.json.
"""
import argparse
import hashlib
import json
import random
import statistics
import sys
from pathlib import Path

import finetune_judge as fj
import natural_edits
import pack

FIRST = 40_000  # added to each writer's first seed: Spark Open 40000+, Spark 50000+
TRAIN_WRITERS = {"spark-open": 100, "spark": 50}  # v3's train letters (v2's 150)
KINDS = tuple(fj.LIES) + ("number in words", "km/h written as mph", "near-misses swapped")
PASSES = 6  # a failed call stops a pass; the next pass asks again (cache kept)
fj.WORKERS = 8


def v4_seed(seed):
    return seed >= FIRST  # every earlier seed is below 40000


def v4_spend(cache):
    """USD of every cached v4 call (letters and natural edits), by writer or editor."""
    out = {}
    for folder in [cache / f for f, *_ in fj.WRITERS.values()] + [cache / "natural"]:
        for p in folder.glob("*.json"):
            r = json.loads(p.read_text())
            if v4_seed(r["seed"]):
                name = f"edit:{r['editor']}" if folder.name == "natural" else r.get("writer", "spark-open")
                out[name] = out.get(name, 0) + r["cost_usd"]
    return out


def all_spend(cache):
    return sum(fj.cached_usd(cache / f) for f, *_ in fj.WRITERS.values()) + fj.cached_usd(cache / "natural")


def template_rows(test):
    """One template-lie row per letter, kinds spread evenly: each letter takes, of the kinds it can carry, the one
    fewest earlier letters took (ties in KINDS order). Seeded per letter, so the rows never change."""
    taken, rows = dict.fromkeys(KINDS, 0), []
    for b in test:
        letter, measured = b["plan"]["letter"], b["measured"]
        lies = {k: (t, p) for k, t, p in fj.planted(letter, json.loads(measured)["worst"],
                                                     random.Random(f"v4/{b['writer']}/{b['seed']}"))}
        kind = min(lies, key=lambda k: (taken[k], KINDS.index(k)))
        taken[kind] += 1
        text, problem = lies[kind]
        rows.append(row(b, kind, text, [problem], "test-template", "template"))
    return rows


def row(b, kind, text, problems, set_name, k):
    return {"kind": kind, "planted": bool(problems), "letter": text, "set": set_name, "seed": b["seed"],
            "writer": b["writer"], "measured": b["measured"], "k": k, "messages": [
                {"role": "user", "content": pack.JUDGE_PROMPT.format(facts=b["measured"], letter=text)},
                {"role": "assistant", "content": fj.reply(problems)}]}


def v3_train_lines(v3_jsonl, v3_split):
    """The lines the starter trained v3 on: its Random(seed) shuffle replayed, less the first n_eval."""
    lines = v3_jsonl.read_text().splitlines()
    random.Random(v3_split["starter_seed"]).shuffle(lines)
    return lines[v3_split["n_eval"]:]


def category(reason):
    for prefix, name in (("code check", "code check"), ("drop", "RISKY, dropped on review"),
                         ("not reviewed", "RISKY, not reviewed"), ("no km/h", "no km/h"), ("shares", "public bench span"),
                         ("no letter", "no letter")):
        if reason.startswith(prefix):
            return name
    return "train-letter share" if "train letters" in reason else reason


def gather(cache, writer, target, cap, pay, public, reviewed, key, train):
    """(bases, rejected, spent): fj.letters, passed again while a failed call left letters missing."""
    folder = cache / fj.WRITERS[writer][0]
    for _ in range(PASSES):
        bases, rejected, spent = fj.letters(folder, target, cap, pay, public, reviewed, writer, all_spend(cache), key,
                                            FIRST, train)
        if len(bases) >= target or not pay:
            break
    return bases, rejected, spent


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", required=True, help="glimmer-ft: the letter caches, reviewed.json, v3/")
    parser.add_argument("--letters", type=int, default=100, help="usable test letters per writer")
    parser.add_argument("--cap", type=float, default=8.0, help="USD of new (v4) calls, every cached v4 call counted")
    parser.add_argument("--yes", action="store_true", help="pay for missing letters and edits")
    args = parser.parse_args()
    cache, out = Path(args.dir), Path(args.dir) / "v4"
    out.mkdir(exist_ok=True)
    reviewed = json.loads((cache / "reviewed.json").read_text())
    key = pack.optional_key()
    if args.yes and not key:
        raise SystemExit("judge_v4: Muse Spark needs MODEL_API_KEY (environment or .env)")
    cap = all_spend(cache) - sum(v4_spend(cache).values()) + args.cap  # fj's caps count every cached call
    public = fj.public_spans()

    train_bases = []
    for writer, n in TRAIN_WRITERS.items():
        train_bases += fj.letters(cache / fj.WRITERS[writer][0], n, 0, False, public, reviewed, writer, 0)[0]
    train_spans = set().union(*(fj.spans(b["plan"]["letter"]) for b in train_bases)) - set().union(
        *(fj.spans(b["measured"]) for b in train_bases))
    train = fj.rows_of(train_bases)
    v3_split = json.loads((cache / "v3" / "split.json").read_text())
    v3_train = v3_train_lines(cache / "v3" / "judge_v3.jsonl", v3_split)
    if len(train) != 1800 or sorted(map(fj.line, train)) != sorted(v3_train):
        raise SystemExit("judge_v4: rebuilt train rows differ from v3's train rows, nothing written")

    test, rejected = [], {}
    for writer in ("spark-open", "spark"):
        got, why, _ = gather(cache, writer, args.letters, cap, args.yes, public, reviewed, key, train_spans)
        test, rejected[writer] = test + got, why
        for seed, reason in why.items():
            if reason.startswith("not reviewed"):
                letter = json.loads((cache / fj.WRITERS[writer][0] / f"{seed:04d}.json").read_text())["plan"]["letter"]
                print(f"to review, {writer} pack {seed}:",
                      *(s for s in pack.SENTENCE.split(letter) if fj.RISKY.search(s.lower())), sep="\n  ")
        print(f"{writer}: {len(got)} usable, ${v4_spend(cache).get(writer, 0):.4f} spent on its v4 letters")
    if len(test) < 2 * args.letters:
        raise SystemExit(f"judge_v4: {len(test)} usable test letters, {2 * args.letters} wanted, nothing written")
    v3_seeds = {(b["writer"], b["seed"]) for b in v3_split["test_letters"]} | {(b["writer"], b["seed"]) for b in train_bases}
    if {(b["writer"], b["seed"]) for b in test} & v3_seeds:
        raise SystemExit("judge_v4: a test seed was used before")

    records = {}
    for _ in range(PASSES):
        records, _ = natural_edits.edits(cache / "natural", test, args.yes, key, cap, all_spend(cache))
        if len(records) == len(test) or not args.yes:
            break
    if len(records) < len(test):
        raise SystemExit(f"judge_v4: {len(test) - len(records)} letters have no natural edit cached, nothing written")
    natural, natural_report = natural_edits.natural_rows(test, records)
    natural = [{**r, "set": f"test-{r['k']}"} for r in natural]
    held = [row(b, "clean: as written", b["plan"]["letter"], [], "test-asis", "asis") for b in test] + template_rows(
        test) + natural

    public_letters = {i["letter"] for i in json.loads(fj.judge_bench.PUBLIC.read_text())}
    near = [f"{r['writer']}/{r['seed']}/{r['k']}" for r in held if fj.shared(r["letter"], r["measured"], public)]
    overlap = {"rows_checked": len(held), "exact_copies": sum(r["letter"] in public_letters for r in held),
               "rows_sharing_a_12_word_span": near, "train_line_copies": len({fj.line(r) for r in held} & set(v3_train))}
    if overlap["exact_copies"] or near or overlap["train_line_copies"]:
        raise SystemExit(f"judge_v4: held-out rows overlap the public bench or train: {overlap}")
    jsonl, split = fj.write_starter(train, held, test, out, "judge_v4", "test")
    lines = jsonl.read_text().splitlines()  # the starter's _prepare, replayed on the file as written
    random.Random(fj.STARTER_SEED).shuffle(lines)
    hold = [fj.line(r) for r in held + fj.public_rows()]
    if lines[:split["n_eval"]] != hold or sorted(lines[split["n_eval"]:]) != sorted(v3_train):
        raise SystemExit("judge_v4: the starter's shuffle does not hold out exactly the v4 and public rows")

    share = [fj.train_share(b["plan"]["letter"], b["measured"], train_spans) for b in test]
    spend = v4_spend(cache)
    summary = {"file": jsonl.name, "sha256": split["sha256"], "n_eval": split["n_eval"], "train_rows": split["train_rows"],
               "train_identical_to_v3": True, "sets": split["sets"],
               "letters_by_writer": {w: sum(b["writer"] == w for b in test) for w in fj.WRITERS},
               "seeds": {w: [min(s), max(s)] for w in fj.WRITERS
                         if (s := [b["seed"] for b in test if b["writer"] == w])},
               "rejections_by_reason": {w: {c: [category(r) for r in why.values()].count(c)
                                            for c in dict.fromkeys(map(category, why.values()))}
                                        for w, why in rejected.items()},
               "rejected_letters": {w: {str(s): r for s, r in why.items()} for w, why in rejected.items()},
               "template_kinds": {k: sum(r["kind"] == k for r in held if r["set"] == "test-template") for k in KINDS},
               "natural_edits": natural_report,
               "test_train_share": {"max": round(max(share), 3), "median": round(statistics.median(share), 3),
                                    "rule": f"under {fj.TRAIN_SHARE:.0%}"},
               "public_bench_overlap": overlap,
               "spend_usd": {**{k: round(v, 4) for k, v in spend.items()}, "total": round(sum(spend.values()), 4),
                             "cap": args.cap},
               "longest_judge_prompt_chars": max(len(r["messages"][0]["content"]) for r in held + train),
               "reviewed": {str(b["seed"]): reviewed[str(b["seed"])] for b in test if str(b["seed"]) in reviewed},
               "data": "synthetic packs only (finetune_judge.synthetic_pack): no real video, no DUT, no SinD, no out/"}
    (out / "judge_v4.manifest.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("rejected_letters", "reviewed")}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
