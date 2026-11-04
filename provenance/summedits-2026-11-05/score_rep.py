"""Score the SummEdits replication by the rule pre-registered in GATES.md: score_ext.py's row rule, plus a
document-level sign test (per document, which judge is right on more of its rows) and a document-level bootstrap.
Run: python3 score_rep.py rep.jsonl rep-tuned.jsonl rep-spark-open.jsonl"""
import json, random, subprocess, sys
from collections import defaultdict
from math import comb
from pathlib import Path
HERE = Path(__file__).parent
row = json.loads(subprocess.check_output([sys.executable, str(HERE / "score_ext.py"), *sys.argv[1:4]], text=True))
sys.path.insert(0, str(HERE)); from score_ext import flags  # noqa: E402
rows = {r["index"]: r for r in map(json.loads, open(sys.argv[1]))}
t, s = flags(sys.argv[2]), flags(sys.argv[3])
right = lambda f, i: f.get(i, False) == (rows[i]["label"] == 0)
per = defaultdict(lambda: [0, 0])
for i, r in rows.items():
    per[r["doc_group"]][0] += right(t, i) and not right(s, i)
    per[r["doc_group"]][1] += right(s, i) and not right(t, i)
net = [w - l for w, l in per.values()]
a, b = sum(x > 0 for x in net), sum(x < 0 for x in net)
n = a + b; p = min(1.0, 2 * sum(comb(n, k) for k in range(min(a, b) + 1)) / 2 ** n) if n else 1.0
random.seed(0); boots = sorted(sum(random.choice(net) for _ in net) for _ in range(20000))
row["document_level"] = {"documents": len(per), "tuned_ahead": a, "behind": b, "p": round(p, 5),
                         "net_row_wins": sum(net), "bootstrap_95": [boots[500], boots[19500]]}
print(json.dumps(row, indent=1))
