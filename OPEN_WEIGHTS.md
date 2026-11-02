# Open weights in Crossing Watch: what runs, what we measured, how to check it

One page for the Open Weights review. Every open-weights call runs on our own (Kaggle) hardware or on partner inference
(Fireworks), never on Meta's hosted API. Every judge number below re-scores at $0 from committed files.

## What the open-weights models do here

| Job | Open-weights model | Where it runs | Measured result |
|---|---|---|---|
| Write the letter to the road authority | Muse Glimmer 30B (sha256-checked GGUF) | Kaggle, free 2 x T4, llama.cpp | sample letter in 313 s, every number passed the code check on try 2 ([record](<removed-run-record>)) |
| Write the letter, fast path | Muse Spark Open | Fireworks serverless | sample letter in 55.5 s, $0.012, request id committed ([writers table](kaggle/open-weights.md#writers-table)) |
| Check the letter for unsupported claims | **Muse Glimmer 30B + our LoRA** (training $0, promotional) | Fireworks on-demand deployment, 1 x H200 (served 2 Nov 2026), and Serverless Training | beats Muse Spark Open in every pre-registered blind test (below); served, it gives the same verdict on 1,499 of 1,501 v6 rows |
| Decide whether a tracked person is a pedestrian | Muse Spark Open | Fireworks serverless | drone ground truth (DUT): crowd 49 of 52 near-misses kept vs Muse Spark's 47; vehicle crowd 48 vs 48 ([table](kaggle/open-weights.md#spark-free-mode)) |

## The fine-tuned judge: four pre-registered blind tests

Each test was written down in [GATES.md](GATES.md) before any letter, label or run; labels were frozen and committed
before any tuned reply was read (git order: pre-registration, frozen labels, then tuned replies). Rows are synthetic
letters written by Muse Spark and Muse Spark Open, with lies and slips planted by templates, by code and by the models.

| Test (new rows) | Tuned Glimmer | Muse Spark Open | Muse Spark | Tuned vs Spark Open | Tuned vs Spark |
|---|---|---|---|---|---|
| v3 (417) | 410 | 402 | 396 | 11 vs 3, p 0.057 | ahead only through a prompt ambiguity, since fixed |
| v4 (1,016) | 998 | 980 | 959 | **28 vs 10, p 0.005** | same ambiguity; 16 vs 18 with it set aside |
| v5 (1,278), prompt fixed | 1,260 | 1,247 | 1,271 | **22 vs 9, p 0.029** | Spark ahead, p 0.043 |
| v6 (1,501), tuned alone | 1,442 | 1,403 | 1,467 | **82 vs 43, p 0.0006** | Spark ahead, p 0.011 |

- **Ahead of Muse Spark Open in all four tests; significant in the last three.** Holm-corrected for three tests, all
  three still hold (0.0006 < 0.017, 0.005 < 0.025, 0.029 < 0.05).
- **Muse Spark (closed) stays ahead overall.** It catches more lies a model words in its own way and more slips the
  letter writers make themselves. We report this as measured; no test is left out.
- **v6's pre-registered primary was the system, tuned + code check:** 1,445 right; vs Spark Open 84 vs 42, p 0.00023;
  Spark ahead, p 0.023.
- **Where v6's margin comes from:** model-written slip edits, 55 vs 8, a row kind v6 trained on. On v4's row kinds
  alone Spark Open leads 35 vs 23 (p 0.15); on model-written lies 27 vs 11. v6 bought slip recall with lie recall
  (GATES.md). v4's and v5's wins are broad (v4 model-written rows 19 vs 4).
- **Without the LoRA, Glimmer is no judge at all here:** with the same 256-token cap, base Glimmer finished 0 of 1,545
  verdicts in v6's evaluation (still reasoning when cut off); tuned Glimmer finished every one in about 34 tokens
  (1,167 vs 0 rows right). Base Glimmer with a longer cap was not measured.
- **Served, not just trained:** on 2 Nov 2026 we deployed the v6 adapter on Fireworks (1 x H200, live merge) and
  replayed all 1,545 v6 prompts: same verdict as the training session on 1,499 of 1,501 test rows, the same 1,442
  right, the same 82 vs 43 against Spark Open; every reply finished, median 2.1 s. Through the product's own judge path
  (`pack.py`'s `JUDGE_MODEL_URL` call) it caught 21 of 23 public-bench lies with 0 of 8 false alarms, as Muse Spark
  does. Request ids, replies and the run log: `provenance/glimmer-judge-lora-v6/live/`. The 1,545 replies took 202 s
  of one H200 at $8 per GPU-hour: about $0.45, or about $0.29 per 1,000 verdicts while the GPU is busy (start-up and
  idle time not counted). The deployment was deleted after the run.
- **Cost:** about 26 output tokens per verdict; about $2.90 per 1,000 letters at the Glimmer sampling price we recorded
  for Fireworks ($1.96 / $4.88 per 1M tokens), vs Muse Spark Open $5.66 and Muse Spark $10.33 (v4 token counts, list
  prices, no cache discount).
- **Found after the fact (v6, not pre-registered):** beside Muse Spark as a second reviewer, the tuned judge adds more
  than Spark Open (Spark OR tuned 1,483 vs Spark OR Spark Open 1,469: 20 vs 6, p 0.009). 14 of the 20 are slip edits;
  on the other rows it is 6 vs 6. A test that would settle this (v7) was cancelled as underpowered.
- **Label checks:** disagreements were adjudicated by an AI agent (Claude), blind to the tuned replies; a later
  symmetric audit of the 46 rows only the tuned judge disagreed with (v5, v6), mixed blind with 26 controls, changed
  0 of 72 labels.

## Check it yourself ($0, no key)

```
python3 judge_v3_score.py        # v3; also v4, v5, v6 (v6 adds the served replies, the per-kind split, the post-hoc line)
python3 judge_compare.py         # the v2 same-set table
python3 writers_table.py         # Glimmer on Kaggle vs Spark Open vs Muse Spark as letter writers
```

- Model ids, training logs, base-vs-tuned evaluation, data and every reply: `provenance/glimmer-judge-lora-v{3,4,5,6}/`
  (`main/summary.json`, `main/metrics.jsonl`), `kaggle/glimmer-judge-train-v*.jsonl`.
- Glimmer on Kaggle: `<removed-run-record>`, `<removed-run-record>` (weights' sha256, llama.cpp build).

## Limits, stated

- **The tuned judge was served once, for the test above, and then deleted** (an on-demand deployment bills while it is
  up). The product's default letter check is Muse Spark or Spark Open; the tuned judge plugs in with
  `JUDGE_MODEL_URL=https://api.fireworks.ai/inference/v1` and `JUDGE_MODEL=<model>#<deployment>` once it is deployed.
- **The adapter cannot be downloaded from Fireworks yet** (we asked Fireworks to enable it); the organizers confirmed
  committed model ids, logs, outputs and a re-score script are the reviewable material. `kaggle/glimmer-judge-lora.ipynb`
  is the self-hosting path but is untested and still names the v2 adapter (`muse-starter-sl-judge-v2-b`).
- The test letters are synthetic. On the 260 letters as written, the tuned judge got 3 fewer right than Spark Open in
  each of v4, v5 and v6 (none significant; pooled 4 vs 13, p 0.049).
- DUT numbers need the DUT data, which its licence keeps private, so they are not re-scorable at $0.
- A planned v7 was cancelled before any letter was written, after a review found it underpowered (GATES.md).
- Built with Muse Spark Open: the adapter is trained partly on letters Spark Open wrote and follows the Muse Model License.
