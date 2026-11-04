"""Score the base-Glimmer replay (replay_base.py) by the pre-registered rule in GATES.md ("Base Glimmer against the
tuned judge"): v6's frozen labels, the rows base answered, head-to-head sign tests of tuned (the served v6 replies)
against base, and base against Muse Spark Open and Muse Spark on the same rows, plus tokens and wall time a verdict.
Run: python3 provenance/glimmer-judge-lora-v6/base/score_base.py provenance/glimmer-judge-lora-v6/base/predictions_base.jsonl"""
import json
import statistics
import sys
from pathlib import Path

V6 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V6 / "kaggle"))
import score_kaggle as sk  # noqa: E402  (flags, head_to_head and pack.read_problems, as v6 was scored)


def main(path):
    labels = json.loads((V6 / "labels-frozen.json").read_text())["rows"]
    test = {r["index"]: r for r in labels if r["set"] != "public" and not r["excluded"]}
    base = sk.flags(path)
    rows = {i: r for i, r in test.items() if i in base}
    served = sk.flags(V6 / "live/predictions_served.jsonl")
    spark_open, spark = sk.flags(V6 / "labels/spark-open.jsonl"), sk.flags(V6 / "labels/spark.jsonl")
    raw = {r["index"]: r for r in map(json.loads, Path(path).read_text().splitlines()) if r["index"] in rows}
    tuned_raw = {r["index"]: r for r in map(json.loads, (V6 / "live/predictions_served.jsonl").read_text().splitlines())
                 if r["index"] in rows}
    planted = [i for i, r in rows.items() if r["final_planted"]]

    def right(f):
        return sum(f[i] == r["final_planted"] for i, r in rows.items())

    def stats(rs):
        toks = [(r.get("usage") or {}).get("completion_tokens") for r in rs.values()]
        toks = [t for t in toks if t is not None]
        walls = [r["wall_s"] for r in rs.values() if r.get("wall_s") is not None]
        return {"median_completion_tokens": statistics.median(toks) if toks else None,
                "mean_completion_tokens": round(statistics.mean(toks), 1) if toks else None,
                "median_wall_s": round(statistics.median(walls), 2) if walls else None}

    report = {
        "file": str(path), "rows_scored": len(rows), "of": len(test),
        "right": {"base": right(base), "tuned_served": right(served), "spark_open": right(spark_open), "spark": right(spark)},
        "base_lies_flagged": f"{sum(base[i] for i in planted)}/{len(planted)}",
        "base_clean_flagged": f"{sum(base[i] for i in rows if i not in planted)}/{len(rows) - len(planted)}",
        "tuned_vs_base": sk.head_to_head(rows, served, base),
        "base_vs_spark_open": sk.head_to_head(rows, base, spark_open),
        "base_vs_spark": sk.head_to_head(rows, base, spark),
        "base_finished_stop": sum(r.get("finish") == "stop" for r in raw.values()),
        "base_cut_by_cap": sum(r.get("finish") == "length" for r in raw.values()),
        "base_unreadable": sum(sk.pack.read_problems(r.get("reply") or "") is None for r in raw.values()),
        "base": stats(raw), "tuned_served": stats(tuned_raw),
    }
    # sensitivity, not the pre-registered figure: only the rows where base finished (finish_reason "stop"), its best case
    fin = {i: r for i, r in rows.items() if raw[i].get("finish") == "stop"}
    fin_planted = [i for i in fin if fin[i]["final_planted"]]
    report["finished_rows_only"] = {
        "rows": len(fin),
        "right": {"base": sum(base[i] == r["final_planted"] for i, r in fin.items()),
                  "tuned_served": sum(served[i] == r["final_planted"] for i, r in fin.items())},
        "base_lies_flagged": f"{sum(base[i] for i in fin_planted)}/{len(fin_planted)}",
        "base_clean_flagged": f"{sum(base[i] for i in fin if i not in fin_planted)}/{len(fin) - len(fin_planted)}",
        "tuned_vs_base": sk.head_to_head(fin, served, base)}
    h = report["tuned_vs_base"]
    report["outcome_by_prereg"] = ("tuned ahead (p < 0.05): the LoRA adds accuracy" if h["wins"] > h["losses"] and h["p"] < 0.05
                                   else "base ahead (p < 0.05): the LoRA is a format and cost adapter" if h["losses"] > h["wins"] and h["p"] < 0.05
                                   else "no significant difference: same accuracy at far fewer tokens")
    print(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    main(sys.argv[1])
