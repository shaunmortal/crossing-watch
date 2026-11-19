"""Replication set for the pre-registered SummEdits replication: 60 consistent and 60 inconsistent rows per domain
(1,200), seed 20261106, from items whose prompt is at most 9,000 characters and that appear nowhere in dev.jsonl or
test.jsonl. SummEdits makes several edits of one document, so a document can recur (doc_group marks it); the
pre-registration adds a document-level check for that. Same prompt as make_sets.py."""
import hashlib, json, random
from collections import defaultdict
from pathlib import Path
HERE = Path(__file__).parent
import importlib.util
spec = importlib.util.spec_from_file_location("ms", HERE / "make_sets.py")
PROMPT, MAX_CHARS = None, None
src = (HERE / "make_sets.py").read_text()
ns = {}
exec(src.split("raw = HERE")[0], {"__file__": str(HERE / "make_sets.py"), "__name__": "x"}, ns)
PROMPT, MAX_CHARS = ns["PROMPT"], ns["MAX_CHARS"]
SEED, PER = 20261106, 60
items = json.loads((HERE / "summedits.json").read_text())
used_ids = {json.loads(l)["id"] for f in ("dev.jsonl", "test.jsonl") for l in open(HERE / f)}
doc_of = {it["id"]: it["doc"].strip() for it in items}
used_docs = {doc_of[i] for i in used_ids}
by = defaultdict(list)
for it in items:
    if it["id"] in used_ids or str(it["label"]) not in ("0", "1"):
        continue
    p = PROMPT.format(doc=it["doc"].strip(), summary=it["summary"].strip())
    if len(p) <= MAX_CHARS:
        by[(it["domain"], int(it["label"]))].append({**it, "label": int(it["label"]), "prompt": p})
short = {f"{d}/{l}": len(v) for (d, l), v in by.items() if len(v) < PER}
if short:
    raise SystemExit(f"too few rows: {short}")
rng = random.Random(SEED); rows = []
for key in sorted(by):
    pool = sorted(by[key], key=lambda x: x["id"]); rng.shuffle(pool); rows += pool[:PER]
docs = {}
with open(HERE / "rep.jsonl", "w") as f:
    for i, r in enumerate(rows):
        d = docs.setdefault(r["doc"].strip(), len(docs))
        f.write(json.dumps({"index": i, "id": r["id"], "domain": r["domain"], "label": r["label"], "doc_group": d, "prompt": r["prompt"]}) + "\n")
b = (HERE / "rep.jsonl").read_bytes()
print("rep.jsonl", b.count(b"\n"), "rows,", len(docs), "documents, sha256", hashlib.sha256(b).hexdigest())
