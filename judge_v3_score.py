"""Re-score the fine-tuned Glimmer judge at $0 from committed files: the frozen labels, the tuned replies and Muse
Spark's and Spark Open's replies. Default: v3 (with its unseen-kind ablation); `v4`: the 1,016-row replication; `v5`: the fixed-prompt test; `v6`: the last run (tuned alone, its v4-style rows, and post
hoc either-of-two with Muse Spark).
Prints the GATES.md result tables and the pre-registered primary endpoint (exact McNemar on correct per row).
Run: python3 judge_v3_score.py [v4|v5|v6]
"""
import json
import sys
from pathlib import Path

from judge_compare import ci, flags, load_jsonl, mcnemar

V3 = Path(__file__).parent / "provenance" / "glimmer-judge-lora-v3"
V4 = Path(__file__).parent / "provenance" / "glimmer-judge-lora-v4"
V5 = Path(__file__).parent / "provenance" / "glimmer-judge-lora-v5"
V6 = Path(__file__).parent / "provenance" / "glimmer-judge-lora-v6"
LIVE = Path("live") / "predictions_served.jsonl"
SETS = (("test + natural (primary)", ("test", "natural")), ("natural (model-written)", ("natural",)),
        ("public bench", ("public",)))
V4_TEST = ("test-asis", "test-template", "test-natural-lie", "test-natural-clean")
V4_SETS = (("all new test rows (primary)", V4_TEST), ("model-written rows", ("test-natural-lie", "test-natural-clean")),
           ("letters as written", ("test-asis",)), ("public bench", ("public",)))
V5_SETS = (("all new test rows (primary)", V4_TEST + ("test-slip",)),) + V4_SETS[1:] + (("writer slips", ("test-slip",)),)
V6_SETS = (("all new test rows (tuned alone)", V4_TEST + ("test-slip", "test-slip-edit")),) + V5_SETS[1:] + (
    ("model-written slip edits", ("test-slip-edit",)), ("v4's row kinds only (no slip rows)", V4_TEST))


def replies(path, key):
    """Each row's reply text, in holdout order."""
    by_index = {r["index"]: r[key] for r in load_jsonl(path)}
    return [by_index[i] for i in range(len(by_index))]


def judges(folder=V3):
    tuned = {"Glimmer + LoRA (tuned)": flags(replies(folder / "main" / "predictions_tuned.jsonl", "answer_text"))}
    if folder == V3:
        tuned["  same, unseen-kind ablation"] = flags(replies(V3 / "unseen" / "predictions_tuned.jsonl", "answer_text"))
    if (folder / LIVE).exists():  # the same adapter served from a Fireworks on-demand deployment, temperature 0
        tuned["  same, served (deployment)"] = flags(replies(folder / LIVE, "reply"))
    return {**tuned, "Muse Spark": flags(replies(folder / "labels" / "spark.jsonl", "reply")),
            "Muse Spark Open": flags(replies(folder / "labels" / "spark-open.jsonl", "reply"))}


def main():
    folder, sets_list = {"v4": (V4, V4_SETS), "v5": (V5, V5_SETS), "v6": (V6, V6_SETS)}.get((sys.argv[1:] or [""])[0], (V3, SETS))
    rows = [r for r in json.loads((folder / "labels-frozen.json").read_text())["rows"] if not r["excluded"]]
    flagged = judges(folder)
    for title, sets in sets_list:
        picked = [r for r in rows if r["set"] in sets]
        print(f"\n{title}: {len(picked)} rows")
        right = {}
        for name, flag in flagged.items():
            lies = [flag[r["index"]] for r in picked if r["final_planted"]]
            clean = [flag[r["index"]] for r in picked if not r["final_planted"]]
            right[name] = [flag[r["index"]] == r["final_planted"] for r in picked]
            print(f"  {name:30} lies {ci(sum(lies), len(lies)):18} clean flagged {ci(sum(clean), len(clean)):16} "
                  f"correct {sum(right[name])}/{len(picked)}")
        if "  same, served (deployment)" in flagged:
            same = sum(flagged["  same, served (deployment)"][r["index"]] == flagged["Glimmer + LoRA (tuned)"][r["index"]]
                       for r in picked)
            print(f"  served vs training-session replies: same verdict on {same}/{len(picked)}")
        tuned = right["Glimmer + LoRA (tuned)"]
        for other in ("Muse Spark", "Muse Spark Open"):
            b = sum(t and not o for t, o in zip(tuned, right[other]))
            c = sum(o and not t for t, o in zip(tuned, right[other]))
            print(f"  tuned vs {other}: {b} vs {c}, exact McNemar p {mcnemar(b, c):.2g}")
        if folder == V6:  # post hoc, not pre-registered: which open judge adds more as a second reviewer beside Spark
            spark = flagged["Muse Spark"]  # a row is flagged when either reviewer flags it
            either = {name: [(spark[r["index"]] or flagged[name][r["index"]]) == r["final_planted"] for r in picked]
                      for name in ("Glimmer + LoRA (tuned)", "Muse Spark Open")}
            tuned_or, open_or = either.values()
            b = sum(t and not o for t, o in zip(tuned_or, open_or))
            c = sum(o and not t for t, o in zip(tuned_or, open_or))
            print(f"  post hoc, Spark OR tuned {sum(tuned_or)} vs Spark OR Spark Open {sum(open_or)}: "
                  f"{b} vs {c}, exact McNemar p {mcnemar(b, c):.2g}")


if __name__ == "__main__":
    main()
