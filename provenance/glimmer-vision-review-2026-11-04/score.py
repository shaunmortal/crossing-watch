"""Scores the crop-review test exactly as RULE.md says. Set A from the reply logs in this folder alone ($0, anyone);
set B from validate_offline.py's --json outputs (the repo's scorer; DUT and our caches are not redistributed).
Run: python3 score.py B_GLIMMER.json B_SPARK.json B_SPARK_OPEN.json > results.json
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BY_EYE = {"c116/0": False, "c483/0": True, "c169/0": True, "c589/0": True}  # GATES.md, gate run ruled by eye, 2 Nov
WALKERS = ("c169/0", "c483/0", "c589/0")
TOTALS = ("conflicts", "matched", "missed", "missed_by_review", "missed_at_threshold", "extra", "extra_at_threshold",
          "unreviewed", "found_before_review")


def rows(name, wanted_set):
    return [json.loads(line) for line in (HERE / name).read_text().splitlines()
            if json.loads(line).get("set") == wanted_set]


def score_a(name):
    """Agreement with Spark's keep/remove, right on the reference labels, walkers kept; unreadable = wrong."""
    by_item = {}
    for r in rows(name, "A"):
        by_item[r["item"]] = r  # one call per crop; a later row would only be a logged transport failure's retry
    agree = right = road = 0
    for pid, r in by_item.items():
        readable = r.get("readable", False)
        spark, ref = r["spark_keep"], BY_EYE.get(pid, r["spark_keep"])
        agree += readable and r["keep"] == spark
        right += readable and r["keep"] == ref
        road += readable and r["road_user"] == r["spark_road_user"]
    disagree = sorted(pid for pid, r in by_item.items() if not r.get("readable") or r["keep"] != r["spark_keep"])
    return {"n": len(by_item), "agree_with_spark": agree, "right_on_reference": right, "road_user_same_as_spark": road,
            "by_eye_walkers_kept": sum(by_item[w].get("keep", False) for w in WALKERS if w in by_item),
            "unreadable": sum(not r.get("readable") for r in by_item.values()),
            "disagreements": [{"piece": p, "spark": by_item[p]["spark_road_user"], "model": by_item[p].get("road_user"),
                               "model_keep": by_item[p].get("keep")} for p in disagree],
            "calls": calls(by_item.values())}


def calls(rs):
    rs = list(rs)
    usage = [r.get("usage") or {} for r in rs]
    return {"replies": len(rs), "finish_stop": sum(r.get("finish_reason") == "stop" for r in rs),
            "prompt_tokens": sum(u.get("prompt_tokens", 0) for u in usage),
            "completion_tokens": sum(u.get("completion_tokens", 0) for u in usage),
            "median_wall_s": sorted(r.get("wall_s", 0) for r in rs)[len(rs) // 2] if rs else None,
            "params": sorted({p for r in rs for p in r.get("params", [])})}


def totals(path):
    return {Path(run).name: {k: v["total"][k] for k in TOTALS} for run, v in json.loads(Path(path).read_text()).items()}


def main():
    spark_a = sum(r["spark_keep"] == BY_EYE.get(r["item"], r["spark_keep"]) for r in rows("replies-A-glimmer.jsonl", "A"))
    out = {"A": {"muse_spark": {"n": 32, "agree_with_spark": 32, "right_on_reference": spark_a, "by_eye_walkers_kept": 3},
                 "muse_glimmer_30b": score_a("replies-A-glimmer.jsonl"),
                 "muse_spark_open": score_a("replies-A-spark-open.jsonl")}}
    if len(sys.argv) == 4:
        glimmer, spark, spark_open = (totals(p) for p in sys.argv[1:])
        out["B"] = {"muse_glimmer_30b": glimmer, "muse_spark": spark, "muse_spark_open": spark_open,
                    "glimmer_calls": calls(rows("replies-B-glimmer.jsonl", "B")),
                    "glimmer_unreadable": sum(not r.get("readable") for r in rows("replies-B-glimmer.jsonl", "B"))}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
