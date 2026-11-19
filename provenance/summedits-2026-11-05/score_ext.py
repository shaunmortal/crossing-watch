"""Score the SummEdits run by the rule pre-registered in GATES.md: a verdict is right when it lists a problem exactly
for the inconsistent summaries (label 0); an unreadable reply or a missing row counts as 'no problem', as in v6.
Run: python3 score_ext.py test.jsonl tuned.jsonl spark-open.jsonl"""
import json, re, sys
from collections import defaultdict
from math import comb

def problems(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m[0]) if m else None
    except json.JSONDecodeError:
        return None
    return [p for p in d["problems"] if isinstance(p, str) and p.strip()] if isinstance(d, dict) and isinstance(d.get("problems"), list) else None

def flags(path):
    return {r["index"]: bool(problems(r["reply"])) for r in map(json.loads, open(path))}

def sign(w, l):
    n = w + l
    return min(1.0, 2 * sum(comb(n, k) for k in range(min(w, l) + 1)) / 2 ** n) if n else 1.0

rows = {r["index"]: r for r in map(json.loads, open(sys.argv[1]))}
t, s = flags(sys.argv[2]), flags(sys.argv[3])
right = lambda f, i: f.get(i, False) == (rows[i]["label"] == 0)
def bal(f):
    inc = [i for i in rows if rows[i]["label"] == 0]; con = [i for i in rows if rows[i]["label"] == 1]
    return round(50 * (sum(right(f, i) for i in inc) / len(inc) + sum(right(f, i) for i in con) / len(con)), 1)
w = sum(right(t, i) and not right(s, i) for i in rows); l = sum(right(s, i) and not right(t, i) for i in rows)
dom = defaultdict(lambda: [0, 0, 0])
for i, r in rows.items():
    d = dom[r["domain"]]; d[0] += right(t, i); d[1] += right(s, i); d[2] += 1
unread = {name: sum(problems(r["reply"]) is None for r in map(json.loads, open(p))) for name, p in (("tuned", sys.argv[2]), ("spark_open", sys.argv[3]))}
out = {"rows": len(rows), "answered": {"tuned": len(t), "spark_open": len(s)}, "unreadable": unread,
       "right": {"tuned": sum(right(t, i) for i in rows), "spark_open": sum(right(s, i) for i in rows)},
       "balanced_accuracy_pct": {"tuned": bal(t), "spark_open": bal(s)},
       "tuned_vs_spark_open": {"wins": w, "losses": l, "p": round(sign(w, l), 5)},
       "per_domain_right_tuned_spark_open_of": {k: v for k, v in sorted(dom.items())}}
out["pass_bar_met"] = w > l and out["tuned_vs_spark_open"]["p"] < 0.05
print(json.dumps(out, indent=1))
