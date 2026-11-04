# The tuned judge on SummEdits, a public human-labelled benchmark (5 Nov 2026)

Pre-registered in GATES.md ("The tuned judge on a public benchmark: SummEdits") before the deployment was created.
SummEdits: Laban et al. 2023, Salesforce, CC-BY-4.0, https://huggingface.co/datasets/Salesforce/summedits
(`summedits.json` sha256 21e34593330020d02b7d92f4651fdcc550f7d79a2f899392f106fd816c215a89; not copied here).

| File | What it is |
|---|---|
| `make_sets.py` | builds `dev.jsonl` (20 rows) and `test.jsonl` (400 rows: 20 consistent and 20 inconsistent per domain, seed 20261105) from `summedits.json` |
| `test.jsonl`, `dev.jsonl` | every prompt as asked (CC-BY-4.0 text from SummEdits) |
| `test-tuned.jsonl`, `dev-tuned.jsonl` | the v6 adapter's replies, each with its Fireworks request id (account masked) |
| `test-spark-open.jsonl`, `smoke-spark-open.jsonl` | Muse Spark Open's replies with request ids (the smoke file is the 5 dev rows read before the pre-registration) |
| `ask_ext.py`, `ext_run.sh`, `ext_run.log` | the run as it was done: deployment created 18:38 UTC, ready 18:40, deleted 18:42 UTC (4 Nov), about 4 GPU-minutes |
| `score_ext.py`, `score.json` | the pre-registered score |

Result: the tuned judge right on 340 of 400, Muse Spark Open 322 (balanced accuracy 85.0% vs 80.5%); head to head 50
vs 32, exact sign test p 0.060, so the pre-registered bar (p < 0.05) is not met. The tuned judge is ahead in 8 of
the 10 domains. Re-score at $0 from this folder: `python3 score_ext.py test.jsonl test-tuned.jsonl test-spark-open.jsonl`.
