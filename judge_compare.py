"""Same-set comparison of the v2 tuned Glimmer judges (all 4 sweep configs) with Muse Spark and Muse Spark Open on the
211 v2 holdout judge prompts (180 dev rows from 15 synthetic letters + 31 public-bench prompts), one vote each.
Offline: reads the committed replies, never an API. A reply pack.read_problems cannot read counts as not flagged.

Per judge and set: lies flagged and clean letters flagged with Wilson 95%, rows correct; paired exact McNemar
(two-sided binomial on the discordant rows) for each config against each Muse judge; mean tokens and an estimated
$ per verdict. The dev rows were used to choose among the 4 configs (B won), so dev favours the chosen config.

Run: python3 judge_compare.py
"""
import json
import math
from pathlib import Path

import pack
import writers_table
from score_humans import wilson

HERE = Path(__file__).parent
V2 = HERE / "provenance" / "glimmer-judge-lora-v2"
SPLIT = HERE / "kaggle" / "glimmer-judge-train-v2.split.json"
CONFIGS = "ABCD"
CHOSEN = "B"
MUSE = {"spark": ("Muse Spark (Meta API, effort low)", "muse-spark-1.3"),
        "spark-open": ("Muse Spark Open (Fireworks, effort low)", "accounts/fireworks/models/muse-spark-open")}
# USD per 1M prompt / sampled tokens for Glimmer evaluation sampling on Fireworks, as provenance/glimmer-judge-lora-v2.json
# ("cost": "eval_sampling_usd_est") notes it; Spark and Spark Open use writers_table.PRICES
GLIMMER_PRICE = (1.96, 4.88)
SETS = (("dev", "dev (used to choose among 4 configs)"), ("public", "public bench"), ("all", "all 211"))


def mcnemar(b, c):
    """Exact two-sided McNemar p: the binomial(b + c, 1/2) chance of a split at least as uneven as b vs c."""
    n = b + c
    if not n:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n)


def ci(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({100 * lo:.0f}-{100 * hi:.0f}%)"


def flags(replies):
    """True where read_problems lists a problem; an unreadable reply (None) is not flagged."""
    return [bool(pack.read_problems(r)) for r in replies]


def load_jsonl(path):
    return [json.loads(line) for line in path.open()]


def muse(name, labels):
    """(replies, mean prompt tokens, mean output tokens incl. reasoning, mean $) from a bench211 cache."""
    rows = {r["index"]: r for r in load_jsonl(V2 / "bench211" / f"{name}.jsonl")}
    missing = [i for i in range(len(labels)) if i not in rows]
    if missing:
        raise SystemExit(f"{name}: {len(missing)} of {len(labels)} rows not cached (first {missing[0]})")
    price = writers_table.PRICES[MUSE[name][1]]
    toks = [writers_table.tokens(rows[i].get("usage")) for i in range(len(labels))]
    prompt = [t[0] or 0 for t in toks]
    cached = [t[1] or 0 for t in toks]
    out = [t[2] or 0 for t in toks]
    usd = [((p - c) * price[0] + c * price[1] + o * price[2]) / writers_table.PER for p, c, o in zip(prompt, cached, out)]
    n = len(labels)
    return [rows[i]["reply"] for i in range(n)], sum(prompt) / n, sum(out) / n, sum(usd) / n


def config(cfg, n):
    """(replies, mean prompt tokens, mean sampled tokens, mean $) for one sweep config: the in-session totals over n."""
    preds = {p["index"]: p["answer_text"] for p in load_jsonl(V2 / cfg.lower() / "predictions_tuned.jsonl")}
    tuned = [m["eval"] for m in load_jsonl(V2 / cfg.lower() / "metrics.jsonl")
             if m.get("eval", {}).get("label") == "tuned"][-1]
    prompt, out = tuned["prompt_tokens"] / n, tuned["sampled_tokens"] / n
    return [preds[i] for i in range(n)], prompt, out, (prompt * GLIMMER_PRICE[0] + out * GLIMMER_PRICE[1]) / 1e6


def main():
    labels = json.loads(SPLIT.read_text())["holdout"]
    n = len(labels)
    planted = [lab["planted"] for lab in labels]
    judges = {f"Glimmer+LoRA {c}{' (chosen)' if c == CHOSEN else ''}": config(c, n) for c in CONFIGS}
    judges.update({MUSE[m][0]: muse(m, labels) for m in MUSE})
    flagged = {j: flags(v[0]) for j, v in judges.items()}
    unread = {j: sum(pack.read_problems(r) is None for r in v[0]) for j, v in judges.items()}
    correct = {j: [f == p for f, p in zip(fl, planted)] for j, fl in flagged.items()}
    rows_in = {s: [i for i, lab in enumerate(labels) if s == "all" or lab["set"] == s] for s, _ in SETS}

    print("| Set | Judge | Lies flagged (Wilson 95%) | Clean letters flagged (Wilson 95%) | Correct |")
    print("|---|---|---|---|---|")
    for s, label in SETS:
        idx = rows_in[s]
        lies, clean = [i for i in idx if planted[i]], [i for i in idx if not planted[i]]
        for j in judges:
            print(f"| {label} | {j} | {ci(sum(flagged[j][i] for i in lies), len(lies))} "
                  f"| {ci(sum(flagged[j][i] for i in clean), len(clean))} | {sum(correct[j][i] for i in idx)}/{len(idx)} |")

    print("\nPaired exact McNemar on correct per row: b = rows only the config gets right, c = rows only the Muse judge "
          "gets right, p two-sided.")
    print("| Set | Config | vs | b | c | p |")
    print("|---|---|---|---|---|---|")
    for s, label in SETS:
        for j in list(judges)[:len(CONFIGS)]:
            for m in (MUSE[k][0] for k in MUSE):
                b = sum(correct[j][i] and not correct[m][i] for i in rows_in[s])
                c = sum(correct[m][i] and not correct[j][i] for i in rows_in[s])
                print(f"| {label} | {j} | {m} | {b} | {c} | {mcnemar(b, c):.3g} |")

    print("\nCost per verdict (ESTIMATES): tokens x price per 1M. Muse judges: each reply's own usage (output includes "
          "reasoning), writers_table.PRICES. Glimmer+LoRA: the in-session eval totals / 211 at "
          f"${GLIMMER_PRICE[0]} / ${GLIMMER_PRICE[1]} per 1M prompt / sampled (provenance note); no deployment exists.")
    print("| Judge | Mean prompt tokens | Mean output tokens | Unreadable replies | Est. $ per verdict |")
    print("|---|---|---|---|---|")
    for j, (_, prompt, out, usd) in judges.items():
        print(f"| {j} | {prompt:.0f} | {out:.0f} | {unread[j]} | ~${usd:.4f} |")


if __name__ == "__main__":
    main()
