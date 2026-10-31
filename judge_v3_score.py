"""Re-score the v3 fine-tuned Glimmer judge at $0 from committed files: the frozen labels, the tuned replies (main
run and the unseen-kind ablation) and Muse Spark's and Spark Open's replies. Prints the GATES.md "v3: result" table
and the pre-registered primary endpoint (exact McNemar on correct per row, test + natural rows).
Run: python3 judge_v3_score.py
"""
import json
from pathlib import Path

from judge_compare import ci, flags, load_jsonl, mcnemar

V3 = Path(__file__).parent / "provenance" / "glimmer-judge-lora-v3"
SETS = (("test + natural (primary)", ("test", "natural")), ("natural (model-written)", ("natural",)),
        ("public bench", ("public",)))


def replies(path, key):
    """Each row's reply text, in holdout order."""
    by_index = {r["index"]: r[key] for r in load_jsonl(path)}
    return [by_index[i] for i in range(len(by_index))]


def judges():
    return {"Glimmer + LoRA v3": flags(replies(V3 / "main" / "predictions_tuned.jsonl", "answer_text")),
            "  same, unseen-kind ablation": flags(replies(V3 / "unseen" / "predictions_tuned.jsonl", "answer_text")),
            "Muse Spark": flags(replies(V3 / "labels" / "spark.jsonl", "reply")),
            "Muse Spark Open": flags(replies(V3 / "labels" / "spark-open.jsonl", "reply"))}


def main():
    rows = [r for r in json.loads((V3 / "labels-frozen.json").read_text())["rows"] if not r["excluded"]]
    flagged = judges()
    for title, sets in SETS:
        picked = [r for r in rows if r["set"] in sets]
        print(f"\n{title}: {len(picked)} rows")
        right = {}
        for name, flag in flagged.items():
            lies = [flag[r["index"]] for r in picked if r["final_planted"]]
            clean = [flag[r["index"]] for r in picked if not r["final_planted"]]
            right[name] = [flag[r["index"]] == r["final_planted"] for r in picked]
            print(f"  {name:30} lies {ci(sum(lies), len(lies)):18} clean flagged {ci(sum(clean), len(clean)):16} "
                  f"correct {sum(right[name])}/{len(picked)}")
        tuned = right["Glimmer + LoRA v3"]
        for other in ("Muse Spark", "Muse Spark Open"):
            b = sum(t and not o for t, o in zip(tuned, right[other]))
            c = sum(o and not t for t, o in zip(tuned, right[other]))
            print(f"  v3 vs {other}: {b} vs {c}, exact McNemar p {mcnemar(b, c):.2g}")


if __name__ == "__main__":
    main()
