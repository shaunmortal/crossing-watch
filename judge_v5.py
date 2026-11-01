"""v5 judge file (GATES.md, "Fine-tuned Glimmer judge v5"): the clarified prompt, writer-slip rows, 260 new test letters.

Train: v3's 150 train letters, their rows rebuilt with today's pack.JUDGE_PROMPT (checked equal to v3's train rows but
for the prompt's new sentence), plus NEW_TRAIN new letters (Spark Open from seed 60000, Spark from 70000) under v3's
rules; a new letter pack.slips flags is not used, so no as-written train row is labelled clean over a slip. Each train
letter gives finetune_judge's template lies and clean rows (7 and 5, as v3/v4), natural_edits' lie and clean edit
(where one is cached: the new letters' first, then v3's as the cap allows), 2-3 writer-slip lies planted by code and
true restatements of the first two of those kinds as clean controls.
Test: 130 new letters per writer (Spark Open from 80000, Spark from 90000) under v4's rules, every train letter's spans
counted. Per letter: as written, one template lie (judge_v4.template_rows), natural_edits' lie and clean edit (editor
alternating), and one writer-slip lie where code can plant one (of the kinds it can carry, the one fewest earlier
letters took, ties in SLIP_KINDS order). The 31 public prompts are rebuilt with the new prompt.

Writer slips: a maker in SLIPS takes the measurements and gives one sentence whose every number is in them, false by
construction (a lie) or true (a control); `holds` reads the sentence back and checks it against the measurements. A
lie that holds, a control that does not, a lie with an unmeasured number or a control code would object to stops the
run. Every call is cached as in finetune_judge, so a re-run pays nothing.

Run: python3 judge_v5.py --dir DIR [--cap 10] [--yes] [--letters-only]
DIR holds the caches, reviewed.json and v3/; writes DIR/v5/judge_v5.jsonl, DIR/v5/split.json, DIR/v5/judge_v5.manifest.json.
"""
import argparse
import json
import random
import re
import statistics
import sys
from pathlib import Path

import finetune_judge as fj
import judge_bench
import judge_v4
import natural_edits
import pack

TRAIN_FIRST, TEST_FIRST = 60_000, 80_000  # added to each writer's first seed (Spark Open 0, Spark 10000)
NEW_TRAIN = {"spark-open": 30, "spark": 30}
PASSES = judge_v4.PASSES
MIN_CLEAN_SHARE = 0.40
NEW_SENTENCE = (' Ordinals ("first", "second", "third") and descriptions of how the measurement\nwas made (tracking, '
                'road-plane geometry, the definitions) are not problems either.')  # b3b1fbe's addition to the prompt
NUM = r"(\d+(?:\.\d+)?)"
fj.WORKERS = 8


def many(n, one, more):
    return f"{n} {one if n == 1 else more}"


def closest(facts, rng, lie):
    """A "closest" time gap: a lie names a measured gap that is not the smallest."""
    pets = sorted({e["pet_s"] for e in facts["worst"]})
    if lie and len(pets) < 2:
        return None
    x = rng.choice(pets[1:]) if lie else pets[0]
    sentence = rng.choice(("The closest near-miss measured had a time gap of {} s.",
                           "At its tightest, a vehicle and a person were on the same spot {} s apart.")).format(x)
    return sentence, f"the closest measured time gap was {pets[0]} s, not {x} s."


def order(facts, rng, lie):
    """Who reached the spot first: a lie puts one near-miss's vehicle after (before) the pedestrian when the counts
    say no near-miss had the person (the vehicle) there first."""
    pf, vf = facts["person_first"], facts["vehicle_first"]
    if not lie:
        return f"The vehicle reached the spot first in {vf} of the measured near-misses and the person in {pf}.", ""
    sides = [side for side, n in (("after", pf), ("before", vf)) if n == 0]
    if not sides:
        return None
    side, e = rng.choice(sides), rng.choice(facts["worst"])
    return (f"In the near-miss with a time gap of {e['pet_s']} s, the {e['vehicle']} reached the spot {side} the "
            f"pedestrian.", f"the measurements count 0 near-misses with the {'person' if side == 'after' else 'vehicle'}"
                            " on the spot first.")


def count(facts, rng, lie):
    """The count of serious near-misses or close passes: a lie gives another measured count (the other tier's first)."""
    serious = rng.random() < 0.5
    truth, other = (facts["serious_near_misses"], facts["close_passes"])[::1 if serious else -1]
    x = truth
    if lie:
        obs = facts["observed"]
        wrong = [v for v in (facts["person_first"], facts["vehicle_first"], obs["gaps_12s"], obs["gaps_6s"]) if v != truth]
        if other == truth and not wrong:
            return None
        x = other if other != truth else rng.choice(wrong)
    if serious:
        sentence, noun = f"The recording showed {many(x, 'serious near-miss', 'serious near-misses')} in all.", \
            "serious near-misses"
    else:
        sentence, noun = f"In total, {many(x, 'close pass', 'close passes')} {'was' if x == 1 else 'were'} measured.", \
            "close passes"
    return sentence, f"the measurements count {truth} {noun}, not {x}."


def gaps(facts, rng, lie):
    """Gaps with no moving vehicle: a lie gives another measured count as the count of gaps of 6 s (or 12 s) or more,
    or the 6 s share as the share inside gaps of 12 s or more when fewer gaps reached 12 s."""
    obs = facts["observed"]
    g6, g12, share = obs["gaps_6s"], obs["gaps_12s"], obs["gap_6s_share_pct"]
    counted = lambda n, t: f"The video showed {many(n, 'gap', 'gaps')} of {t} s or more with no moving vehicle."
    shared = lambda t: f"{share}% of the time was inside gaps of {t} s or more."
    if not lie:
        return rng.choice((counted(g6, 6), counted(g12, 12), shared(6))), ""
    options = [(counted(x, 6), f"the measurements count {g6} gaps of 6 s or more, not {x}.")
               for x in dict.fromkeys((g12, obs["crossings"])) if x != g6]
    options += [(counted(g6, 12), f"the measurements count {g12} gaps of 12 s or more, not {g6}.")] if g6 != g12 else []
    options += [(shared(12), f"{share}% of the time was inside gaps of 6 s or more; only {g12} of those {g6} gaps "
                             "lasted 12 s or more, so less of the time was inside gaps of 12 s or more.")] if g12 < g6 else []
    return rng.choice(options) if options else None


def cut_short(facts, rng, lie):
    """Gaps cut short by the recording's ends: a lie says more than two were."""
    if not lie:
        return "The first and last gaps of 6 s or more are cut short by the video.", ""
    obs = facts["observed"]
    found = [n for n in dict.fromkeys((obs["gaps_6s"], obs["crossings"])) if n > pack.VIDEO_EDGES]
    if not found:
        return None
    n = rng.choice(found)
    return (f"{n} gaps were cut short by the start or end of the video.",
            f"only the first and last gap can be cut short by the video, not {n}.")


SLIPS = {"closest gap": closest, "order of arrival": order, "near-miss count": count, "gap count or share": gaps,
         "gaps cut short": cut_short}
SLIP_KINDS = tuple(SLIPS)


def holds(kind, sentence, facts):
    """Whether the measurements establish `sentence`, read back from its words (not from how it was made)."""
    obs = facts["observed"]
    if kind == "closest gap":
        return float(re.search(NUM + r" s\b", sentence)[1]) == min(e["pet_s"] for e in facts["worst"])
    if kind == "order of arrival":
        if pack.PERSON_FIRST.search(sentence):
            return facts["person_first"] > 0
        if pack.VEHICLE_FIRST.search(sentence):
            return facts["vehicle_first"] > 0
        m = re.search(r"first in (\d+) .* person in (\d+)", sentence)
        return (int(m[1]), int(m[2])) == (facts["vehicle_first"], facts["person_first"])
    if kind == "near-miss count":
        m = re.search(r"(\d+) (serious near-miss|close pass)", sentence)
        return int(m[1]) == facts["serious_near_misses" if m[2].startswith("serious") else "close_passes"]
    if kind == "gap count or share":
        if m := re.search(NUM + r"% of the time was inside gaps of (6|12) s", sentence):
            return float(m[1]) == obs["gap_6s_share_pct"] and (m[2] == "6" or obs["gaps_12s"] == obs["gaps_6s"])
        m = re.search(r"(\d+) gaps? of (6|12) s or more", sentence)
        return int(m[1]) == obs[f"gaps_{m[2]}s"]
    m = pack.CUT_SHORT.search(sentence)
    return float(m[1]) <= pack.VIDEO_EDGES if m else bool(pack.EDGES_NAMED.search(sentence))


def plant(kind, letter, measured, rng, lie):
    """(letter with the slip or control inserted, the sentence, why it is false) or None when this letter's
    measurements cannot carry a `kind` lie. Raises when the sentence is not what it is meant to be."""
    facts = json.loads(measured)
    made = SLIPS[kind](facts, rng, lie)
    if made is None:
        return None
    sentence, why = made
    if holds(kind, sentence, facts) == lie:
        raise AssertionError(f"{kind} {'lie holds' if lie else 'control does not hold'}: {sentence!r}")
    if lie and pack.unmeasured(sentence, measured):
        raise AssertionError(f"{kind} lie has unmeasured numbers: {sentence!r}")
    if not lie and (natural_edits.unsupported_in_clean(sentence, measured) or pack.slips(sentence, facts)):
        raise AssertionError(f"{kind} control is not clean by code: {sentence!r}")
    text = judge_bench.inserted(letter, sentence)
    return (text, sentence, why) if text else None


def slip_row(b, kind, lie, set_name, k):
    """A judge_v4 row with one writer slip (or its control) planted in base letter `b`; None if it cannot carry one."""
    made = plant(kind, b["plan"]["letter"], b["measured"], random.Random(f"v5/{set_name}/{b['writer']}/{b['seed']}/"
                                                                         f"{kind}/{lie}"), lie)
    if not made:
        return None
    text, sentence, why = made
    return {**judge_v4.row(b, f"slip: {kind}" if lie else f"clean: slip control ({kind})", text,
                           [f'"{sentence}": {why}'] if lie else [], set_name, k), "slip_kind": kind}


def train_rows(bases, records):
    """Each train letter's rows: finetune_judge's template lies and clean rows, its natural edits when cached, 2-3
    slip lies and controls of the first two of their kinds. Seeded per letter, so the rows never change."""
    rows = fj.rows_of(bases)
    rows += natural_edits.natural_rows([b for b in bases if (b["writer"], b["seed"]) in records], records)[0]
    for b in bases:
        rng = random.Random(f"v5/train-slips/{b['writer']}/{b['seed']}")
        lies = [r for kind in rng.sample(SLIP_KINDS, len(SLIP_KINDS)) if (r := slip_row(b, kind, True, "train", kind))]
        lies = lies[:rng.choice((2, 3))]
        rows += lies + [slip_row(b, r["slip_kind"], False, "train", f"control {r['slip_kind']}") for r in lies[:2]]
    return rows


def test_slip_rows(test):
    """One slip-lie row per test letter that can carry one: of the kinds it can, the one fewest earlier letters took."""
    taken, rows = dict.fromkeys(SLIP_KINDS, 0), []
    for b in test:
        made = {kind: r for kind in SLIP_KINDS if (r := slip_row(b, kind, True, "test-slip", "slip"))}
        if made:
            kind = min(made, key=lambda k: (taken[k], SLIP_KINDS.index(k)))
            taken[kind] += 1
            rows.append(made[kind])
    return rows


def v5_record(natural, seed):
    """A cached call v5 paid for: a letter from seed 60000 on, or an edit of such a letter or of a v3 train letter."""
    return seed >= TRAIN_FIRST or (natural and seed < fj.TEST_SEEDS)


def v5_spend(cache):
    out = {}
    for folder in [cache / f for f, *_ in fj.WRITERS.values()] + [cache / "natural"]:
        for p in folder.glob("*.json"):
            r = json.loads(p.read_text())
            if v5_record(folder.name == "natural", r["seed"]):
                name = f"edit:{r['editor']}" if folder.name == "natural" else r.get("writer", "spark-open")
                out[name] = out.get(name, 0) + r["cost_usd"]
    return out


def gather(cache, writer, target, cap, pay, public, reviewed, key, first, train=None, slip_free=False):
    """(bases, rejected): fj.letters until `target` pass, asked again after a failed call; with `slip_free` (train) a
    letter pack.slips flags is rejected and replaced."""
    folder, want, idle = cache / fj.WRITERS[writer][0], target, 0
    while True:
        bases, rejected, _ = fj.letters(folder, want, cap, pay, public, reviewed, writer, judge_v4.all_spend(cache),
                                        key, first, train)
        slipped = {b["seed"]: f"writer slip, train only: {s[0][1]}" for b in bases
                   if slip_free and (s := pack.slips(b["plan"]["letter"], json.loads(b["measured"])))}
        kept = [b for b in bases if b["seed"] not in slipped]
        if len(kept) >= target or not pay:
            return kept[:target], {**rejected, **slipped}
        if len(bases) >= want:
            want = target + len(slipped)
        elif (idle := idle + 1) >= PASSES:
            return kept, {**rejected, **slipped}


def edit_all(cache, bases, pay, key, cap):
    """natural_edits' cached records for `bases`, asked (when `pay`) until done or PASSES passes add none."""
    records, idle = {}, 0
    while pay and idle < PASSES and len(records) < len(bases):
        before = len(records)
        records, _ = natural_edits.edits(cache / "natural", bases, True, key, cap, judge_v4.all_spend(cache))
        idle = 0 if len(records) > before else idle + 1
    return natural_edits.edits(cache / "natural", bases, False, key, cap, 0)[0]


def review_list(cache, writer, why):
    for seed, reason in why.items():
        if reason.startswith("not reviewed"):
            letter = json.loads((cache / fj.WRITERS[writer][0] / f"{seed:04d}.json").read_text())["plan"]["letter"]
            print(f"to review, {writer} pack {seed}:",
                  *(s for s in pack.SENTENCE.split(letter) if fj.RISKY.search(s.lower())), sep="\n  ")


def kinds_of(rows):
    out = {}
    for r in rows:
        out[r["kind"]] = out.get(r["kind"], 0) + 1
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", required=True, help="glimmer-ft: the letter caches, reviewed.json, v3/")
    parser.add_argument("--cap", type=float, default=10.0, help="USD of new (v5) calls, every cached v5 call counted")
    parser.add_argument("--yes", action="store_true", help="pay for missing letters and edits")
    parser.add_argument("--letters-only", action="store_true", help="stop once the letters are gathered (to review)")
    args = parser.parse_args()
    cache, out = Path(args.dir), Path(args.dir) / "v5"
    out.mkdir(exist_ok=True)
    reviewed = json.loads((cache / "reviewed.json").read_text())
    key = pack.optional_key()
    if args.yes and not key:
        raise SystemExit("judge_v5: Muse Spark needs MODEL_API_KEY (environment or .env)")
    cap = judge_v4.all_spend(cache) - sum(v5_spend(cache).values()) + args.cap  # fj's caps count every cached call
    public = fj.public_spans()

    v3_bases = []
    for writer, n in judge_v4.TRAIN_WRITERS.items():
        v3_bases += fj.letters(cache / fj.WRITERS[writer][0], n, 0, False, public, reviewed, writer, 0)[0]
    v3_split = json.loads((cache / "v3" / "split.json").read_text())
    v3_train = judge_v4.v3_train_lines(cache / "v3" / "judge_v3.jsonl", v3_split)
    old = json.dumps(NEW_SENTENCE, ensure_ascii=False)[1:-1]
    if NEW_SENTENCE not in pack.JUDGE_PROMPT or sorted(fj.line(r).replace(old, "") for r in fj.rows_of(v3_bases)) != \
            sorted(v3_train):
        raise SystemExit("judge_v5: v3's train letters do not rebuild v3's train rows but for the new sentence")

    rejected, new_train, test = {}, [], []
    for writer, n in NEW_TRAIN.items():
        got, rejected[f"train {writer}"] = gather(cache, writer, n, cap, args.yes, public, reviewed, key, TRAIN_FIRST,
                                                  slip_free=True)
        new_train += got
        review_list(cache, writer, rejected[f"train {writer}"])
        print(f"train {writer}: {len(got)} usable")
    train_bases = v3_bases + new_train
    train_spans = set().union(*(fj.spans(b["plan"]["letter"]) for b in train_bases)) - set().union(
        *(fj.spans(b["measured"]) for b in train_bases))
    for writer in ("spark-open", "spark"):
        got, rejected[f"test {writer}"] = gather(cache, writer, 130, cap, args.yes, public, reviewed, key, TEST_FIRST,
                                                 train_spans)
        test += got
        review_list(cache, writer, rejected[f"test {writer}"])
        print(f"test {writer}: {len(got)} usable, ${v5_spend(cache).get(writer, 0):.4f} spent on its v5 letters")
    if len(new_train) < sum(NEW_TRAIN.values()) or len(test) < 260:
        raise SystemExit(f"judge_v5: {len(new_train)} new train and {len(test)} test letters usable, 60 and 260 wanted")
    if args.letters_only:
        return
    seeds = [b["seed"] for b in new_train + test]
    if len(set(seeds)) != len(seeds) or min(seeds) < TRAIN_FIRST:
        raise SystemExit("judge_v5: a letter's seed was used before")

    test_records = edit_all(cache, test, args.yes, key, cap)
    if len(test_records) < len(test):
        raise SystemExit(f"judge_v5: {len(test) - len(test_records)} test letters have no natural edit, nothing written")
    train_records = {**edit_all(cache, new_train, args.yes, key, cap), **edit_all(cache, v3_bases, args.yes, key, cap)}

    train = train_rows(train_bases, train_records)
    clean_share = sum(not r["planted"] for r in train) / len(train)
    if clean_share < MIN_CLEAN_SHARE:
        raise SystemExit(f"judge_v5: train clean share {clean_share:.3f} under {MIN_CLEAN_SHARE}")
    natural, natural_report = natural_edits.natural_rows(test, test_records)
    natural = [{**r, "set": f"test-{r['k']}"} for r in natural]
    held = ([judge_v4.row(b, "clean: as written", b["plan"]["letter"], [], "test-asis", "asis") for b in test]
            + judge_v4.template_rows(test) + natural + test_slip_rows(test))

    public_letters = {i["letter"] for i in json.loads(fj.judge_bench.PUBLIC.read_text())}
    near = [f"{r['writer']}/{r['seed']}/{r['k']}" for r in held + train if fj.shared(r["letter"], r["measured"], public)]
    train_lines = [fj.line(r) for r in train]
    overlap = {"rows_checked": len(held + train), "exact_copies": sum(r["letter"] in public_letters for r in held + train),
               "rows_sharing_a_12_word_span": near, "held_lines_in_train": len({fj.line(r) for r in held} & set(train_lines))}
    if overlap["exact_copies"] or near or overlap["held_lines_in_train"]:
        raise SystemExit(f"judge_v5: rows overlap the public bench or train: {overlap}")
    jsonl, split = fj.write_starter(train, held, test, out, "judge_v5", "test")
    lines = jsonl.read_text().splitlines()  # the starter's _prepare, replayed on the file as written
    random.Random(fj.STARTER_SEED).shuffle(lines)
    if lines[:split["n_eval"]] != [fj.line(r) for r in held + fj.public_rows()] or \
            sorted(lines[split["n_eval"]:]) != sorted(train_lines):
        raise SystemExit("judge_v5: the starter's shuffle does not hold out exactly the v5 test and public rows")

    share = [fj.train_share(b["plan"]["letter"], b["measured"], train_spans) for b in test]
    spend = v5_spend(cache)
    family = lambda r: ("slip" if "slip_kind" in r else "natural" if str(r["k"]).startswith("natural")
                        else "as written" if r["kind"] in ("clean: as written",) else "template")
    by_family = {}
    for r in train:
        f = by_family.setdefault(family(r), {"planted": 0, "clean": 0})
        f["planted" if r["planted"] else "clean"] += 1
    summary = {"file": jsonl.name, "sha256": split["sha256"], "n_eval": split["n_eval"], "train_rows": split["train_rows"],
               "sets": split["sets"], "train_clean_share": round(clean_share, 3), "train_by_family": by_family,
               "train_letters": {"v3": len(v3_bases), "new": {w: sum(b["writer"] == w for b in new_train) for w in NEW_TRAIN},
                                 "with_natural_edits": {"v3": sum((b["writer"], b["seed"]) in train_records for b in v3_bases),
                                                        "new": sum((b["writer"], b["seed"]) in train_records for b in new_train)}},
               "test_letters_by_writer": {w: sum(b["writer"] == w for b in test) for w in fj.WRITERS},
               "seeds": {f"{name} {w}": [min(s), max(s)] for name, group in (("train", new_train), ("test", test))
                         for w in fj.WRITERS if (s := [b["seed"] for b in group if b["writer"] == w])},
               "slip_kinds": {"train lies": {k: sum(r.get("slip_kind") == k and r["planted"] for r in train) for k in SLIP_KINDS},
                              "train controls": {k: sum(r.get("slip_kind") == k and not r["planted"] for r in train)
                                                 for k in SLIP_KINDS},
                              "test": {k: sum(r.get("slip_kind") == k for r in held) for k in SLIP_KINDS},
                              "test letters without a slip row": len(test) - sum("slip_kind" in r for r in held)},
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
               "longest_judge_prompt_chars": max(len(r["messages"][0]["content"]) for r in held + train),
               "train_kinds": kinds_of(train),
               "reviewed": {str(b["seed"]): reviewed[str(b["seed"])] for b in new_train + test if str(b["seed"]) in reviewed},
               "data": "synthetic packs only (finetune_judge.synthetic_pack): no real video, no DUT, no SinD, no out/"}
    (out / "judge_v5.manifest.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("rejected_letters", "reviewed", "train_kinds")},
                     indent=1))


if __name__ == "__main__":
    sys.exit(main())
