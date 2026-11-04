# Open weights in Crossing Watch: what runs, what we measured, how to check it

One page for the Open Weights review. Every open-weights call runs on our own (Kaggle) hardware or on partner inference
(Fireworks), never on Meta's hosted API. Every judge number below re-scores at $0 from committed files.

**Lead result (4 Nov 2026): our real gate case, every reasoning step on open weights.** Muse Spark Open (Fireworks) reviewed the people, ran the case agent and wrote the letter; our LoRA-tuned Muse Glimmer reviewer, served on a Fireworks deployment for 4 minutes, read the letter. No Meta API key was set and every host except api.fireworks.ai went to a dead proxy. Same 5 near-misses and the same 51 people as the hosted run; the letter passed the code check and the tuned reviewer on the first try; about $0.62. SAM 3.1 tracking and Muse Wonder were re-read from the hosted run's cache, and Muse Image was skipped. Run log, request and response ids: [provenance/open-gate-2026-11-04](provenance/open-gate-2026-11-04/README.md).

**Our tuned judge runs free (4 Nov 2026).** The v6 adapter, downloaded from Fireworks and converted to GGUF, ran over Meta's 4-bit Glimmer on Kaggle's free 2 x T4 and beat Muse Spark Open again on v6's 1,501 test rows: 1,435 right, **81 vs 49, p 0.006**, with the pass bar written before the run. It gave the same verdict as the Fireworks deployment on 1,492 rows. [score](provenance/glimmer-judge-lora-v6/kaggle/score.json), [notebook](kaggle/glimmer-judge-lora.ipynb), [run record](provenance/glimmer-judge-lora-v6/kaggle/glimmer-judge-lora-provenance.json).

**How "beats Muse Spark Open" is scored:** on each pre-registered blind test on planted errors, every new row (planted lies, slips
and clean letters alike) is scored right or wrong against labels frozen before any tuned reply was read; the two models
are compared on the rows where exactly one is right (exact two-sided sign test). Tuned Glimmer wins v4, v5 and v6 this
way (p 0.005, 0.029, 0.0006); Muse Spark (closed) stays ahead overall.

## What the open-weights models do here

Each open model: where it runs, what it does in Crossing Watch, what we measured, and where its run logs and request
ids are.

| Open-weights model | Where it runs | What it does here | Measured result | Run logs and request ids |
|---|---|---|---|---|
| Muse Glimmer 30B (sha256-checked GGUF) | Kaggle, free 2 x T4, llama.cpp, our own account | Writes the letter to the road authority | **a letter for our real gate in 276 s, first try**, every number passed the code check ([letter](kaggle/glimmer-gate-letter.txt), [notebook](kaggle/glimmer-gate.ipynb)) | [Kaggle run log](kaggle/glimmer-gate-run-log.json), screenshots of the [notebook](kaggle/glimmer-gate-kaggle-notebook.jpg) and [run](kaggle/glimmer-gate-kaggle-log.jpg) (nvidia-smi, llama.cpp build, `server ready`, `pack.py`'s return); [run record](kaggle/glimmer-gate-provenance.json) (weights' sha256, timings, tokens); a self-hosted llama-server gives no request id |
| **Muse Glimmer 30B + our LoRA** (training $0, promotional) | Fireworks Serverless Training; Fireworks on-demand deployment, 1 x H200 (served 2 and 3 Nov 2026); Kaggle, free 2 x T4, llama.cpp over Meta's 4-bit base (4 Nov 2026) | Checks the letter for unsupported claims | beats Muse Spark Open in every pre-registered blind test on planted errors (below; Muse Spark, closed, stays ahead overall); served, it gives the same verdict on 1,499 of 1,501 v6 rows and read our real gate letter 6 of 6 times with no unsupported claim; **on Kaggle's free T4s: 1,435 of 1,501 right, beats Spark Open 81 vs 49 (p 0.006)**, and on today's measurements it flagged, in 6 of 6 reads, that our certified letter's 80 counts tracked crossings where today's measurements count 51 people on foot (the certified letter stays as signed) | training sessions and step logs: `provenance/glimmer-judge-lora-v{3,4,5,6}/main/` (`summary.json`, `metrics.jsonl`); served: [deployment log](provenance/glimmer-judge-lora-v6/live/run.json), 1,545 response ids in [`predictions_served.jsonl`](provenance/glimmer-judge-lora-v6/live/predictions_served.jsonl), 6 on the gate letter in [`gate-letter-judge.json`](provenance/glimmer-judge-lora-v6/live/gate-letter-judge.json); Kaggle: [score](provenance/glimmer-judge-lora-v6/kaggle/score.json), 1,545 replies in [`predictions_kaggle.jsonl`](provenance/glimmer-judge-lora-v6/kaggle/predictions_kaggle.jsonl), [run record](provenance/glimmer-judge-lora-v6/kaggle/glimmer-judge-lora-provenance.json) (sha256 of adapter, GGUF and base), [Kaggle run log](provenance/glimmer-judge-lora-v6/kaggle/kaggle-run.log) |
| Muse Spark Open | Fireworks serverless | Writes the letter, fast path | sample letter in 55.5 s, $0.012 ([writers table](kaggle/open-weights.md#writers-table)) | [run record](provenance/spark-open-fireworks-sample.json), request id `chatcmpl-9e68cb0170d84c348eb29b1687354a4f` |
| Muse Spark Open | Fireworks serverless | Second AI reviewer of our real gate letter | 6 of 6 reads, no unsupported claim | [record](provenance/spark-open-fireworks-gate.json), 6 response ids |
| Muse Spark Open | Fireworks serverless | Comparison judge in the blind tests | the table below | a request id on every row: `provenance/glimmer-judge-lora-v{3,4,5,6}/labels/spark-open.jsonl` |
| Muse Spark Open | Fireworks serverless, tool calling | Takes the case agent's turns (`AGENT_MODEL_URL`) | 30 Oct 2026, on a copy of the synthetic `sample/`: 29 turns, about $0.19, stopped for a person twice as designed | [record](provenance/spark-open-agent-sample.json) (turns, tools called, tokens) |
| Muse Spark Open | Fireworks serverless | Decides whether a tracked person is a pedestrian | drone ground truth (DUT): crowd 49 of 52 near-misses kept vs Muse Spark's 47; vehicle crowd 48 vs 48 ([table](kaggle/open-weights.md#spark-free-mode)) | replies stay with the DUT outputs, which we do not redistribute |
| Muse Glimmer 30B (base, vision) | Fireworks on-demand, 1 x H200, 10 minutes, then deleted (4 Nov 2026) | Decides whether a tracked person is a pedestrian, in Muse Spark's place | our gate: **the same keep/remove call as Muse Spark on all 32 people**; drone ground truth (DUT, crowd mode): kept all 50 near-misses the geometry found and removed 1 of 5 false alarms, where Muse Spark and Spark Open removed 2; the win bar written before any call was not met (4 false alarms vs at most 3) | [review, rule and every reply](provenance/glimmer-vision-review-2026-11-04/README.md) |
| **Muse Spark Open + tuned Glimmer judge: every reasoning step of our gate case** | Fireworks serverless; judge on a Fireworks on-demand 1 x H200 for 4 minutes, then deleted (4 Nov 2026) | Person review, case agent and letter on Spark Open; the letter's judge is our v6 LoRA; no Meta key, every other host blocked | **the same 5 near-misses and the same 51 people as Muse Spark** (same keep-or-reject on all 32 people reviewed); letter on the first try, code check clean, tuned judge: no unsupported claim (4 of 4 reads); about $0.62. SAM 3.1 and Muse Wonder replies reused from the hosted run's cache, Muse Image not called | [README](provenance/open-gate-2026-11-04/README.md), [run record](provenance/open-gate-2026-11-04/run.json), letter request `chatcmpl-45c5ea24b9654c75bdbc9b1617c586c2`, 3 judge response ids in [judge.json](provenance/open-gate-2026-11-04/judge.json) |

## The fine-tuned judge: four pre-registered blind tests on planted errors

Each test was written down in [GATES.md](GATES.md) before any letter, label or run; labels were frozen and committed
before any tuned reply was read (git order: pre-registration, frozen labels, then tuned replies). Rows are synthetic
letters written by Muse Spark and Muse Spark Open, with lies and slips planted by templates, by code and by the models.

| Test (new rows) | Tuned Glimmer | Muse Spark Open | Muse Spark | Tuned vs Spark Open | Tuned vs Spark |
|---|---|---|---|---|---|
| v3 (417) | 410 | 402 | 396 | 11 vs 3, p 0.057 | ahead only through a prompt ambiguity, since fixed |
| v4 (1,016) | 998 | 980 | 959 | **28 vs 10, p 0.005** | same ambiguity; 16 vs 18 with it set aside |
| v5 (1,278), prompt fixed | 1,260 | 1,247 | 1,271 | **22 vs 9, p 0.029** | Spark ahead, p 0.043 |
| v6 (1,501), tuned alone | 1,442 | 1,403 | 1,467 | **82 vs 43, p 0.0006** | Spark ahead, p 0.011 |
| v6 again, on Kaggle's free 2 x T4 (4-bit base; a replication) | 1,435 | 1,403 | 1,467 | **81 vs 49, p 0.006** | Spark ahead, p 0.0014 |

- **Ahead of Muse Spark Open in all four tests; significant in the last three.** Holm-corrected for three tests, all
  three still hold (0.0006 < 0.017, 0.005 < 0.025, 0.029 < 0.05).
- **Muse Spark (closed) stays ahead overall.** It catches more lies a model words in its own way and more slips the
  letter writers make themselves. We report this as measured; no test is left out.
- **v6's pre-registered primary was the system, tuned + code check:** 1,445 right; vs Spark Open 84 vs 42, p 0.00023;
  Spark ahead, p 0.023 (GATES.md "v6"; tuned replies OR `pack.slips`).
- **Where v6's margin comes from:** model-written slip edits, 55 vs 8, a row kind v6 trained on. On v4's row kinds
  alone Spark Open leads 35 vs 23 (p 0.15); on model-written lies 27 vs 11. v6 bought slip recall with lie recall
  (GATES.md). v4's and v5's wins are broad (v4 model-written rows 19 vs 4).
- **Without the LoRA, Glimmer is no judge at all here:** with the same 256-token cap, base Glimmer finished 0 of 1,545
  verdicts in v6's evaluation (still reasoning when cut off); tuned Glimmer finished every one in about 34 tokens
  (1,167 vs 0 replies matching the label exactly). Base Glimmer with a longer cap was not measured.
- **Served, not just trained:** on 2 Nov 2026 we deployed the v6 adapter on Fireworks (1 x H200, live merge) and
  replayed all 1,545 v6 prompts: same verdict as the training session on 1,499 of 1,501 test rows, the same 1,442
  right, the same 82 vs 43 against Spark Open; every reply finished, median 2.1 s. Through the product's own judge path
  (`pack.py`'s `JUDGE_MODEL_URL` call) it caught 21 of 23 public-bench lies with 0 of 8 false alarms, as Muse Spark
  does. Request ids, replies and the run log: `provenance/glimmer-judge-lora-v6/live/`. The 1,545 replies took 202 s
  of one H200 at $8 per GPU-hour: about $0.45, or about $0.29 per 1,000 verdicts while the GPU is busy (start-up and
  idle time not counted). The deployment was deleted after the run.
- **On our real gate letter (3 Nov 2026):** served once more, the tuned judge read our real gate letter, on the product's own judge prompt and measurements, six times (three plain, three with the product's JSON schema): no unsupported claim in any reply, as Muse Spark and Muse Spark Open also found. Replies and response ids: [`provenance/glimmer-judge-lora-v6/live/gate-letter-judge.json`](provenance/glimmer-judge-lora-v6/live/gate-letter-judge.json).
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
- Glimmer on Kaggle: `kaggle/glimmer-gate.ipynb`, `kaggle/glimmer-gate-provenance.json` (weights' sha256, llama.cpp build),
  `kaggle/glimmer-gate-run-log.json` (Kaggle's own log of the run).
- Tuned judge on Kaggle: `kaggle/glimmer-judge-lora.ipynb`, `provenance/glimmer-judge-lora-v6/kaggle/` (every reply, score, run record, Kaggle's log);
  re-score: `python3 provenance/glimmer-judge-lora-v6/kaggle/score_kaggle.py provenance/glimmer-judge-lora-v6/kaggle/predictions_kaggle.jsonl`.
- Each letter's sha256 in its run record is of the text without the file's final newline:
  `python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1]).read().rstrip(chr(10)).encode()).hexdigest())" kaggle/glimmer-gate-letter.txt`.
- For verification on Fireworks: training sessions `ts-aeb58db486cb4952a49bb9855fca40ed` (v3),
  `ts-b74ec0f3fc214bbd8eee34f89ffe35ff` (v4), `ts-13675bf5ae7840e8b90fa4fa70a249ee` (v5),
  `ts-17bf2de281bb4cbe8424de262befb01b` (v6); deployments `cw-judge-v6` (2 Nov 2026, 08:04-08:16 IST) and
  `cw-judge-gate` (3 Nov); Spark Open request `chatcmpl-9e68cb0170d84c348eb29b1687354a4f`; every response id is in
  `provenance/`. Account id on request.

## Limits, stated

- **The tuned judge was served twice (2 and 3 Nov) and deleted after each run** (an on-demand deployment bills while it is
  up). The product's default letter check is Muse Spark or Spark Open; the tuned judge plugs in with
  `JUDGE_MODEL_URL=https://api.fireworks.ai/inference/v1` and `JUDGE_MODEL=<model>#<deployment>` once it is deployed.
- **Self-hosted, the judge is slightly behind its Fireworks deployment:** over Meta's 4-bit base on Kaggle it got
  1,435 of 1,501 right against 1,442; of the 9 rows where the two differ, the deployment is right on 8.
- The test letters are synthetic. On the 260 letters as written, the tuned judge got 3 fewer right than Spark Open in
  each of v4, v5 and v6 (none significant; pooled 4 vs 13, p 0.049).
- DUT numbers need the DUT data, which we do not redistribute (it has no licence file), so they are not re-scorable at $0.
- A planned v7 was cancelled before any letter was written, after a review found it underpowered (GATES.md).
- Built with Muse Spark Open: the adapter is trained partly on letters Spark Open wrote and follows the Muse Model License.
