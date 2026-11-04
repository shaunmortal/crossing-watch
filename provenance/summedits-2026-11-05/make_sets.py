"""SummEdits (Salesforce, CC-BY-4.0) -> the judge's prompt. Seeded, stratified by domain, disjoint dev and test.
Label 1 = consistent summary (correct verdict: no problem), 0 = inconsistent (correct verdict: a problem).
Only items whose prompt is at most MAX_CHARS characters (the LoRA was trained on prompts of at most 3,072 tokens)."""
import hashlib, json, random
from collections import defaultdict
from pathlib import Path
HERE = Path(__file__).parent
SEED, PER_DOMAIN_PER_LABEL, DEV_PER_DOMAIN, MAX_CHARS = 20261105, 20, 1, 9000
PROMPT = """You review a letter before it is sent. MEASUREMENTS are the only facts.
List every problem: a claim or number the measurements do not support. Tone, wording and style are not problems.
Reply JSON only: {{"problems": ["<one short sentence each>"]}}, with [] if there are none.

MEASUREMENTS:
{doc}

LETTER:
{summary}"""
raw = HERE / "summedits.json"  # https://huggingface.co/datasets/Salesforce/summedits/resolve/main/summedits.json
items = json.loads(raw.read_text())
by = defaultdict(list)
for it in items:
    p = PROMPT.format(doc=it["doc"].strip(), summary=it["summary"].strip())
    if len(p) <= MAX_CHARS and str(it["label"]) in ("0", "1"):
        by[(it["domain"], int(it["label"]))].append({**it, "label": int(it["label"]), "prompt": p})
rng = random.Random(SEED)
dev, test = [], []
for key in sorted(by):
    pool = sorted(by[key], key=lambda x: x["id"]); rng.shuffle(pool)
    dev += pool[:DEV_PER_DOMAIN]; test += pool[DEV_PER_DOMAIN:DEV_PER_DOMAIN + PER_DOMAIN_PER_LABEL]
for name, rows in (("dev", dev), ("test", test)):
    with open(HERE / f"{name}.jsonl", "w") as f:
        for i, r in enumerate(rows):
            f.write(json.dumps({"index": i, "id": r["id"], "domain": r["domain"], "label": r["label"], "prompt": r["prompt"]}) + "\n")
print("summedits.json sha256", hashlib.sha256(raw.read_bytes()).hexdigest())
for name in ("dev", "test"):
    b = (HERE / f"{name}.jsonl").read_bytes(); n = b.count(b"\n")
    print(name, n, "rows, sha256", hashlib.sha256(b).hexdigest())
print("shortfalls:", {f"{d}/{l}": len(v) for (d, l), v in by.items() if len(v) < DEV_PER_DOMAIN + PER_DOMAIN_PER_LABEL})
