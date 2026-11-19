"""Post hoc, not pre-registered: v6's tuned judge against Muse Spark Open counted per LETTER instead of per row.
The 1,501 test rows come from 260 letters, so rows from one letter are not independent, which McNemar assumes.
Per letter: does the tuned judge win more of that letter's disagreement rows than Spark Open? Then a sign test over
letters and a letter-level (cluster) bootstrap of the net wins. Standard library, no key.
Run from the repo root: python3 provenance/glimmer-judge-lora-v6/letter_level_check.py"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import judge_v3_score as j  # noqa: E402  (the v6 scorer: frozen labels, each judge's flags, exact McNemar)

rows = [r for r in json.loads((j.V6 / "labels-frozen.json").read_text())["rows"] if not r["excluded"]]
rows = [r for r in rows if r["set"] in j.V6_SETS[0][1]]
flags = j.judges(j.V6)
tuned, spark_open = flags["Glimmer + LoRA (tuned)"], flags["Muse Spark Open"]
per = defaultdict(lambda: [0, 0])
for r in rows:
    letter = "/".join(r["id"].split("/")[:2])
    t, o = tuned[r["index"]] == r["final_planted"], spark_open[r["index"]] == r["final_planted"]
    per[letter][0] += t and not o
    per[letter][1] += o and not t
net = [w - l for w, l in per.values()]
ahead, behind = sum(x > 0 for x in net), sum(x < 0 for x in net)
random.seed(0)
boots = sorted(sum(random.choice(net) for _ in net) for _ in range(20000))
print(f"rows {len(rows)}, letters {len(per)}, row-level tuned vs Spark Open {sum(w for w, _ in per.values())} vs {sum(l for _, l in per.values())}")
print(f"letters where tuned is ahead {ahead}, behind {behind}, exact sign test p {j.mcnemar(ahead, behind):.5f}")
print(f"net row wins {sum(net)}, letter-level bootstrap 95% interval {boots[500]} to {boots[19500]}")
