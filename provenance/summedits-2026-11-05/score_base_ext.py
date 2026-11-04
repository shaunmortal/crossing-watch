"""Score base Glimmer on the SummEdits replication rows by the rule pre-registered in GATES.md ("Base Glimmer on the
SummEdits replication rows"): for each arm, on the rows it answered, right for base, the tuned judge and Muse Spark
Open; exact sign tests tuned vs base and base vs Spark Open; finished and cut-off counts; median tokens and seconds;
and, as a sensitivity, the rows base finished. Run: python3 score_base_ext.py rep.jsonl rep-tuned.jsonl
rep-spark-open.jsonl rep-base-cap256.jsonl rep-base-cap8192.jsonl"""
import json, re, statistics, sys
from math import comb

def problems(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m[0]) if m else None
    except json.JSONDecodeError:
        return None
    return [x for x in d["problems"] if isinstance(x, str) and x.strip()] if isinstance(d, dict) and isinstance(d.get("problems"), list) else None

def load(path):
    return {r["index"]: r for r in map(json.loads, open(path))}

def sign(w, l):
    n = w + l
    return min(1.0, 2 * sum(comb(n, k) for k in range(min(w, l) + 1)) / 2 ** n) if n else 1.0

rows = load(sys.argv[1]); tuned, spark = load(sys.argv[2]), load(sys.argv[3])
flag = lambda rs: {i: bool(problems(r["reply"])) for i, r in rs.items()}
ft, fs = flag(tuned), flag(spark)
right = lambda f, i: f.get(i, False) == (rows[i]["label"] == 0)
def h2h(a, b, ids):
    w = sum(right(a, i) and not right(b, i) for i in ids); l = sum(right(b, i) and not right(a, i) for i in ids)
    return {"wins": w, "losses": l, "p": sign(w, l)}
def med(rs, key):
    v = [k for k in (key(r) for r in rs) if k is not None]
    return statistics.median(v) if v else None
out = {}
for path in sys.argv[4:]:
    base = load(path); fb = flag(base); ids = sorted(base)
    fin = [i for i in ids if base[i].get("finish") == "stop"]
    arm = {"rows_answered": len(ids), "finished": len(fin), "cut_off": sum(base[i].get("finish") == "length" for i in ids),
           "unreadable": sum(problems(base[i]["reply"]) is None for i in ids),
           "right": {"base": sum(right(fb, i) for i in ids), "tuned": sum(right(ft, i) for i in ids), "spark_open": sum(right(fs, i) for i in ids)},
           "tuned_vs_base": h2h(ft, fb, ids), "base_vs_spark_open": h2h(fb, fs, ids),
           "base_median_tokens": med(base.values(), lambda r: (r.get("usage") or {}).get("completion_tokens")),
           "base_median_wall_s": med(base.values(), lambda r: r.get("wall_s")),
           "finished_rows_only": {"rows": len(fin), "right": {"base": sum(right(fb, i) for i in fin), "tuned": sum(right(ft, i) for i in fin), "spark_open": sum(right(fs, i) for i in fin)},
                                  "tuned_vs_base": h2h(ft, fb, fin)}}
    h = arm["tuned_vs_base"]
    arm["outcome_by_prereg"] = ("tuned ahead of base (p < 0.05)" if h["wins"] > h["losses"] and h["p"] < 0.05
                                else "base ahead of tuned (p < 0.05)" if h["losses"] > h["wins"] and h["p"] < 0.05 else "no significant difference")
    out[path.split("/")[-1]] = arm
print(json.dumps(out, indent=1))
