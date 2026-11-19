"""Score a replay of the v6 holdout (GATES.md, "Tuned judge v6 on a free Kaggle GPU"): the v6 test rows (not public,
not excluded) against the labels frozen on 1 Nov, and against the saved Muse Spark Open, Muse Spark and Fireworks replies.
Run: python3 score_kaggle.py PREDICTIONS.jsonl   (predictions_served.jsonl gives v6's recorded 1,442 and 82 vs 43)
"""
import json
import sys
from math import comb
from pathlib import Path

V6 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V6.parents[1]))
import pack  # noqa: E402


def flags(path):
    """index -> flagged (an unreadable reply or a failed row counts as not flagged, as v6 was scored)."""
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    return {r["index"]: bool(pack.read_problems(r.get("reply") or "")) for r in rows}


def sign_test(wins, losses):
    """Exact two-sided sign test on the rows where exactly one side is right."""
    n = wins + losses
    return min(1.0, 2 * sum(comb(n, k) for k in range(min(wins, losses) + 1)) / 2 ** n) if n else 1.0


def head_to_head(rows, mine, theirs):
    wins = sum(mine[i] == r["final_planted"] != theirs[i] for i, r in rows.items())
    losses = sum(theirs[i] == r["final_planted"] != mine[i] for i, r in rows.items())
    return {"wins": wins, "losses": losses, "p": round(sign_test(wins, losses), 5)}


def main(path):
    labels = json.loads((V6 / "labels-frozen.json").read_text())["rows"]
    test = {r["index"]: r for r in labels if r["set"] != "public" and not r["excluded"]}
    mine = flags(path)
    rows = {i: r for i, r in test.items() if i in mine}  # a replay cut by the wall cap scores its prefix
    others = {"spark_open": flags(V6 / "labels/spark-open.jsonl"), "spark": flags(V6 / "labels/spark.jsonl"),
              "served": flags(V6 / "live/predictions_served.jsonl")}
    planted = [i for i, r in rows.items() if r["final_planted"]]
    report = {
        "file": str(path), "test_rows_scored": len(rows), "of": len(test),
        "right": sum(mine[i] == r["final_planted"] for i, r in rows.items()),
        "lies_flagged": f"{sum(mine[i] for i in planted)}/{len(planted)}",
        "clean_flagged": f"{sum(mine[i] for i in rows if i not in planted)}/{len(rows) - len(planted)}",
        "same_verdict_as_served": sum(mine[i] == others["served"][i] for i in rows),
        "vs_spark_open": head_to_head(rows, mine, others["spark_open"]),
        "vs_spark": head_to_head(rows, mine, others["spark"]),
        "spark_open_right": sum(others["spark_open"][i] == r["final_planted"] for i, r in rows.items()),
        "spark_right": sum(others["spark"][i] == r["final_planted"] for i, r in rows.items()),
    }
    report["pass_bar_met"] = report["vs_spark_open"]["wins"] > report["vs_spark_open"]["losses"] \
        and report["vs_spark_open"]["p"] < 0.05
    print(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    main(sys.argv[1])
