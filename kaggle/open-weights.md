# Open weights: two paths, the writers table and the public judge bench

Both Muse open-weights models wrote a letter with a run record in this repo: Muse Glimmer 30B for our real gate,
Muse Spark Open for the synthetic `sample/` (made-up tracks, no video).

## Two open-weights paths

**Muse Glimmer 30B, self-hosted on Kaggle 2 x T4** (`kaggle/glimmer-gate.ipynb`, on the author's own Kaggle account;
record `kaggle/glimmer-gate-provenance.json`, letter `kaggle/glimmer-gate-letter.txt`). It proves the weights ran on
hardware we control with no Meta API key: llama.cpp `b11976` built in the run, Meta's 4-bit GGUF at a pinned Hugging
Face revision with both files checked against their published sha256, nvidia-smi's table, the git commit and
`pack.py`'s sha256 all in the record. Glimmer wrote a letter for our real gate in 276 s on the first try, every number
passed the code check, and no judge read it (no `MODEL_API_KEY` in that run). Kaggle's own log of the run (nvidia-smi,
the llama.cpp build, `server ready`, `pack.py`'s return, the record as printed) is `kaggle/glimmer-gate-run-log.json`.
The record and the log are kept exactly as the run wrote them; their `notebook` field names the notebook by its earlier
file name. Screenshots of the Kaggle notebook (cw-glimmer-gate, the author's own account, "Successfully ran in 2254.7s",
GPU T4 x2) and of these log lines: [notebook](glimmer-gate-kaggle-notebook.jpg), [run](glimmer-gate-kaggle-log.jpg),
[log lines](glimmer-gate-kaggle-log-lines.jpg).

**Muse Spark Open on Fireworks**, a hackathon infra partner (record `provenance/spark-open-fireworks-sample.json`,
letter `provenance/spark-open-sample-letter.txt`, its sha256 in the record, taken without the file's final newline).
It proves the open model writes a letter that passes every check on the first try, through a partner's serverless API:
request id
`chatcmpl-9e68cb0170d84c348eb29b1687354a4f`, 55.5 s, about one cent. The record (pack.py's `letter-provenance.json`)
kept the tries but not the checks when it ran; its `judged_by` was added afterwards from the run's `plan.json` (about
`sample/`, kept outside the repo, same letter sha256), which says `"judged_by": "Muse Spark (a separate reviewer)"`
with no number left unmeasured, and a letter kept on try 1 of 3 is one no check objected to (`pack.ask_plan` returns
early only then). pack.py's records now keep the judge, and on a letter kept after the last try what the checks left.

## Writers table

`python3 writers_table.py [RECORD.json ...]` (offline) prints it from the run records; as produced now from the
committed records (Glimmer's row is its letter for our real gate, the other two the sample's):

| Writer | Open weights | Where it ran | Wall s | Prompt tokens (cached) | Completion tokens | Reasoning tokens | Tries | Number check | Passed by judge | Cost per letter |
|---|---|---|---|---|---|---|---|---|---|---|
| Muse Glimmer 30B | yes | Kaggle, 2 x Tesla T4, self-hosted | 276 | 1,572 (0) | 3,672 | not reported | 1 | passed | none ran | $0 (free Kaggle GPU quota) |
| Muse Spark Open | yes | Fireworks (serverless) | 55.5 | 1,019 (960) | 2,732 | 2,140 | 1 | passed | Muse Spark (a separate reviewer) | $0.0118 |
| Muse Spark | no | Meta API | 17.0 | 899 (0) | 3,961 | 3,472 | 1 | passed | Muse Spark (a separate reviewer) | $0.0180 |

Prices, USD per 1M tokens input / cached input / output, read 29 Oct 2026: Muse Spark Open 1.25 / 0.15 / 4.25 (https://fireworks.ai/models/fireworks/muse-spark-open); Muse Spark 1.25 / 0.15 / 4.25 (https://dev.meta.ai/docs/pricing-rate-limits.md). Tokens are the kept reply's; wall seconds are the whole pack.py run where the record has it (Kaggle), else the reply's.

- Prices were read on 29 Oct 2026. Fireworks' model page gives Muse Spark Open's serverless price as
  "$1.25 / $0.15 / $4.25, Per 1M Tokens (input/cached input/output)". Its pricing page lists Muse Spark Open only
  under the Serverless Training API ($6.19 per 1M prefill tokens), which is fine-tuning, not this. The Meta API price
  for `muse-spark-1.3` is Standard mode, from the same page the README's agent cap quotes.
- Neither page says how reasoning tokens are billed. The API's completion tokens (2,732) already include the 2,140
  reasoning tokens, so the cost bills them at the output price: (59 x $1.25 + 960 x $0.15 + 2,732 x $4.25) / 1M =
  $0.0118.
- Glimmer's 276 s is the whole `pack.py` run; llama-server's own timing for its reply is 271.1 s. Its prompt is our
  gate's, longer than the sample's, and the times come from different hardware, so they say nothing about the
  models' speed on equal footing.

## Public judge bench

`kaggle/judge-bench-public.json` is the judge bench built only from letters about the synthetic `sample/` (made-up
tracks, no video), so it can go in the repo, a Kaggle dataset or a public release. No base letter comes from DUT,
SinD, a YouTube clip or kids' footage; `test_cw.py` checks that, and every item names its base's source.

Build it (offline, scores the code check only): `python3 judge_bench.py --public`

| Base | Writer | Where the text is | Source |
|---|---|---|---|
| `glimmer` | Muse Glimmer 30B, open weights, written during development | `kaggle/glimmer-sample-letter.txt` | `sample/` |
| `spark-open` | Muse Spark Open, open weights, on Fireworks (1 try, 55.5 s, 1,019 prompt + 2,732 completion tokens) | `provenance/spark-open-sample-letter.txt`, its sha256 checked against `provenance/spark-open-fireworks-sample.json` | `sample/` |

Each base gets the same planted lies as the private bench (one per copy) and the same 4 clean controls. Spark
Open's letter names its two near-misses' speeds in separate sentences, so it has no "near-misses swapped" copy:
23 planted letters and 8 clean controls in all.

Code check, scored offline (`judge_bench.py --public`):

| | Code |
|---|---|
| All planted lies | 4/23 (7-37%) |
| Named kinds | 2/12 (5-45%) |
| Kinds not named | 2/11 (5-48%) |
| Clean controls: false alarms | 0/8 (0-32%) |

The code check catches the two kinds with a number in them: a count in words and km/h written as mph. Muse Spark's column is
filled from its cached replies (21/23, 0/8); tuned Glimmer v6 scored 21/23 and 0/8 (OPEN_WEIGHTS.md), and the Muse Glimmer column fills from a run (`--glimmer N` with
the same file).

Note on the clean controls: both base letters offer to share "the video", and the measurements say the sample has no
video. A judge that flags a control for that is arguably right, so read the false-alarm row with that in mind.

## Two votes for an open-weights judge (`JUDGE_VOTES=2`)

`JUDGE_VOTES=2` is opt-in and applies only to the `JUDGE_MODEL_URL` judge: it is asked twice per letter, and a problem
counts only when both replies list one (`pack.vote`). In `pack.py` that is the open judge's verdict on each try at the letter; in `judge_bench.py` it is the
Glimmer column's verdict per run, with both raw replies and the vote kept under `glimmer_votes` in the bench file and
a line under the table saying how many runs were votes. A reply that cannot be read makes the vote unreadable: counted
apart in the bench, and one problem to check in `pack.py`, never a pass. Muse Spark is always asked once.

Why two: Glimmer samples at temperature 1.0 (the model card's setting), so a reply can list a problem that is not
there; a planted lie should be listed both times, while a stray flag on a clean letter has to come up twice to count.
It costs one more reply per letter, and a lie that one of the two replies misses is missed. It is off unless
`JUDGE_VOTES=2` is set.

The case agent (`agent.py`) can also take its turns on Muse Spark Open on Fireworks (`AGENT_MODEL_URL`, see the
README's case agent section); first run 30 Oct 2026 on a copy of the synthetic `sample/`: 29 turns across resumes,
about $0.19 (`provenance/spark-open-agent-sample.json`).

## Fine-tuned Glimmer judge

Sat 31 Oct 2026: a LoRA (rank 8, 1 epoch, 35 steps) on Muse Glimmer 30B through Fireworks' Serverless Training API
(`fw-ai/cookbook` 57968a2, `muse_glimmer_starter`; training $0 under Fireworks' promotion, evaluation sampling about
$2.00; no deployment). Data: `finetune_judge.py` wrote 50 letters for made-up packs with Muse Spark Open ($0.83),
planted lies with `judge_bench.py`'s own functions in new wording, and kept clean letters (42% of rows); no row shares
a 12-word span with the public bench. The file trained on is `glimmer-judge-train.jsonl`; its holdout (`.split.json`)
is 4 whole synthetic letters plus all 31 public-bench prompts, none trained on. Scored with `pack.read_problems`
(record: `provenance/glimmer-judge-lora.json`, replies in `provenance/glimmer-judge-lora/`):

| Judge | Public bench: lies flagged | Clean letters flagged | Reply |
|---|---|---|---|
| **Glimmer + our LoRA**, 1 vote | 18/23 (21/23 with the code checks) | **0/8** | about 90 characters |
| Muse Spark Open, effort low, 1 vote | 22/23 | 0/8 | about 740 tokens |

Synthetic holdout: 24/28 lies, 0/20 clean letters flagged. Misses on the public bench: two "number in words" and one
"km/h written as mph" (the code checks catch all three), "near-misses swapped" (2 training rows: Spark Open rarely
puts two near-misses in one sentence) and one "every school day". The in-session base column is not quoted: 78 of 79
base replies ran out of the 4,096-token cap while reasoning, so the starter's base-vs-tuned delta is not a fair test.
The v6 adapter was served for $0 on Kaggle (`--lora` on the same Q4_K_M base) on 4 Nov 2026 (GATES.md, 'Tuned judge v6 on a free Kaggle GPU').

### v2: a pre-registered sweep

Sat 31 Oct 2026. 150 training letters from two writers (Muse Spark Open, and Muse Spark through the Meta API), 62
"near-misses swapped" rows (v1 had 2), split by whole letters into train (1,620 rows) and dev (180 rows from 15
letters); the 31 public-bench prompts were held out of every run. Four configs, the winner rule and the order were
written in GATES.md before any run; the winner was named there from dev alone before any public reply was read.
Record: `provenance/glimmer-judge-lora-v2.json`, every reply in `provenance/glimmer-judge-lora-v2/`, data
`glimmer-judge-train-v2.jsonl`. Training $0; evaluation sampling about $5.6 for the four runs.

| Config | Dev: lies / clean flagged | Public bench: lies / clean flagged |
|---|---|---|
| A rank 8, 1 epoch | 101/105, 0/75 | 21/23, 0/8 (not chosen) |
| **B rank 32, 1 epoch (chosen)** | **104/105, 0/75** | **23/23, 0/8** |
| C rank 8, 2 epochs | 104/105, 0/75 | 20/23, 0/8 (not chosen) |
| D rank 32, 2 epochs, 5e-5 | 104/105, 0/75 | 21/23, 0/8 (not chosen) |

On the same public bench Muse Spark flags 21/23 lies (22/23 in a second run) and 0/8 clean letters, Muse Spark Open (effort low) 22/23 and
0/8. One vote, temperature 0, 31 prompts: 23/23 is 86-100% and
0/8 is 0-32% (Wilson 95%). The configs that were not chosen show the spread a different pick would have given.

Paired on the same 211 holdout prompts (180 dev, 31 public; one vote each; `judge_compare.py`, GATES.md "Same-set
comparison on 211 judge prompts"): on the 128 planted rows B flags 127, Muse Spark 126, Spark Open 126, a tie. The
clean dev letters cannot score false alarms: their synthetic measurements say "no video" and the letters mention
video, which Spark rightly flagged (32 of its 37 flags), so the earlier 38-vs-0 claim is withdrawn (see GATES.md). B
answers in about 26 output tokens against Spark's 2,153 and Spark Open's 877.

### v3: a blind, pre-registered test against Muse Spark

Sat 31 Oct 2026. v2's "clean" dev letters were not clean (their synthetic measurements said "no video"; see GATES.md),
so v3 fixed the synthetic packs, kept v2's config B with no sweep, and tested on 30 new letters plus 57 lies and clean
edits written by Muse Spark and Spark Open themselves (not our templates). Before any tuned reply was read, Spark and
Spark Open judged every row, a reviewer blind to the tuned replies settled each disagreement (5 labels changed), and the
labels were frozen (`provenance/glimmer-judge-lora-v3/labels-frozen.json`). Protocol and result: GATES.md "v3".

| 417 blind rows (test + model-written) | Correct | Lies flagged | Clean letters flagged |
|---|---|---|---|
| **Glimmer + our LoRA (v3)** | **410** | 237/244 | **0/173** |
| Muse Spark (Meta API) | 396 | 238/244 | 15/173 |
| Muse Spark Open (Fireworks) | 402 | 230/244 | 1/173 |

Exact McNemar on the pre-registered primary endpoint: against Muse Spark 19 vs 5, p 0.0066 (8 vs 5, p 0.58 with its
ordinal flags set aside; see v4); against Spark Open
11 vs 3, p 0.057 (not significant). On the 57 model-written rows: 56, 50 and 53 right. All three get 30/31 on the
public bench. Built with Muse Spark Open: the training letters were written by Muse Spark Open and Muse Spark, so the
adapter follows the Muse Model License. A second run trained without two lie kinds still caught all 30 rows of them (an easy pair: every judge
did) and got 411/417. Training $0; every reply is committed.

### v4: 1,016 blind rows, pre-registered, against both Muse judges

The v3 recipe retrained once and tested on 1,016 rows from 260 new synthetic letters (four rows each: as written, a
template lie, a lie and a clean edit written by Muse Spark or Spark Open), labels frozen before any tuned reply was read
(GATES.md "v4"). Disagreements were adjudicated by an AI agent (Claude, Anthropic), blind to the tuned replies, under
written standards; it only moved labels from clean to planted (12) or excluded a row (1).

| 1,016 rows | Correct | Lies flagged | Clean letters flagged |
|---|---|---|---|
| **Glimmer + our LoRA (v4)** | **998** | 512/525 | **5/491** |
| Muse Spark | 959 | 517/525 | 49/491 |
| Muse Spark Open | 980 | 493/525 | 4/491 |

Exact McNemar against Muse Spark Open: 28 vs 10, **p 0.0051**; 24 of the 28 are lies Spark Open missed (18
model-written, 6 template), and it flags 5/491 clean rows to Spark Open's 4/491. On synthetic, in-distribution letters.

Against Muse Spark the pre-registered result stands as recorded (57 vs 18, p 7.2e-06), but most of Spark's false
alarms come from an ambiguity in our judge prompt: "a number above one written in words" invites flagging ordinals,
and the tuned judge learned to read it our way from the training labels. 41 of Spark's 49 clean-row flags are only
about ordinals ("second", "third", ...) or the method sentence (SAM tracking, road-plane geometry); set those aside
and the comparison with Spark is 16 vs 18, p 0.86 (no significant difference). Rule and rows: GATES.md, v4 note of Sun 1 Nov.

Writer slips: v4 caught none of the six real slips the letter writers made themselves (Spark caught six, Spark Open three),
and on the 260 letters as written it is not ahead of Spark Open (251 vs 254 right, p 0.51), so the code checks and a second
judge stay. Re-score at $0: `python3 judge_v3_score.py v4`.

What one verdict costs, from the v4 replies' own token counts (1,048 rows each):

| Judge | Tokens in / out per verdict | Per 1,000 letters checked |
|---|---|---|
| **Glimmer + our LoRA (v4)** | 1,414 / **26** | **about $2.90** at Fireworks' Glimmer sampling price ($1.96 / $4.88 per 1M); $0 on Kaggle's free T4s, where the v6 adapter ran (4 Nov 2026) |
| Muse Spark Open | 1,502 / 891 | about $5.66 ($1.25 / $4.25 per 1M) |
| Muse Spark | 1,366 / 2,030 | about $10.33 ($1.25 / $4.25 per 1M) |

### v5: the prompt fixed for every judge, a fresh blind test

Sun 1 Nov 2026. The judge prompt now says ordinals and method descriptions are not problems, for all three judges and
in every training row; training added 534 code-planted writer-slip lies and model-written edits; 2 epochs; a fresh
test of 260 new letters, 1,278 rows (GATES.md "v5"). **Muse Spark wins the pre-registered comparison** (1,271 vs 1,260
right, 7 vs 18, p 0.043); **v5 beats Muse Spark Open** (1,247; 22 vs 9, p 0.029). v5 is level with or ahead of Spark on
template lies (259 vs 258 of 260), model-written lies (249 vs 248 of 249) and code-planted slips (260 vs 260), and
behind on the 20 real slips the writers made themselves (8 vs 20). Re-score: `python3 judge_v3_score.py v5`.

### v6: the open system (tuned Glimmer + code checks), the last run

Training added model-written slip edits and 32 real writer slips; `pack.slips` widened (a270d6d) and frozen; fresh
test of 260 letters, 1,501 rows (GATES.md "v6"). **Beats Muse Spark Open** (1,445 vs 1,403 right, p 0.00023) and
catches more model-written slips than Muse Spark (225 vs 214 of 230, p 0.027); **Muse Spark is ahead overall** (1,467, p 0.023),
mainly on model-written lies (243 vs 214 of 245). Pre-registered as the last judge run before submission.

On 4 Nov 2026 the v6 adapter ran over Meta's 4-bit Glimmer on Kaggle's free 2 x T4 (`kaggle/glimmer-judge-lora.ipynb`,
pass bar written before the run): judge alone, 1,435 right (the Fireworks deployment 1,442), **beats Muse Spark Open
81 vs 49 (p 0.006)**. Record: `provenance/glimmer-judge-lora-v6/kaggle/`.

## Spark-free mode

Each closed-model step and its open-weights substitute, measured against the closed one (DUT: numbers only, crops stay
private; crop reviewer run Sat 31 Oct 2026, 175 Spark Open calls, 80,500 in / 77,668 out tokens, about $0.43, then
the last 6 vehicle-crowd pieces for about $0.02).

| Component | Closed | Open substitute | Measured result |
|---|---|---|---|
| Letter writer | Muse Spark (1 try) | Spark Open on Fireworks; Glimmer 30B on Kaggle | number check passed on try 1, Glimmer's too (writers table) |
| Letter judge | Muse Spark: public bench 21/23 lies, 0/8 false alarms | Spark Open, effort low; Glimmer + our LoRA | tuned Glimmer v4 on 1,016 blind rows from 260 letters: **998 right, 5/491 false alarms** vs Spark Open 980 and 4/491 (p 0.0051); vs Spark 959 and 49/491 (p 7.2e-06 as pre-registered; 16 vs 18, p 0.86, with its ordinal and method-sentence flags set aside) |
| Crop reviewer | Muse Spark: crowd 47/52, 3 extra; vehicle crowd 48/52, 4 extra | Spark Open (`REVIEW_MODEL_URL`, `validate_offline.py --reviewer open`) | crowd 49/52, 3 extra; vehicle crowd 48/52, 3 extra (none unreviewed); same keep/remove call as Spark on 51 of 53 and 45 of 46 pieces both judged |

## Next runs

1. **Glimmer shown the blurred street photo** (Kaggle step). The 2 Nov gate run sent none; the same notebook with
   `street.jpg` added to the private cw-gate input:
   `LETTER_MODEL_URL=http://127.0.0.1:8080/v1 LETTER_MODEL_HOST="Kaggle 2 x T4" python3 pack.py out/GATE_VIDEO
   out/GATE_VIDEO/site.json`. `writers_table.py` can print its row locally.
2. **Spark Open judging Glimmer's real letter** (paid, Fireworks). In the run above, with `FIREWORKS_API_KEY` as a
   Kaggle secret exported to the environment, add the Fireworks judge:
   `JUDGE_MODEL_URL=https://api.fireworks.ai/inference/v1 JUDGE_MODEL=accounts/fireworks/models/muse-spark-open`.
   Then both models are open weights, one writing and one judging, and the record's `judged_by` names Spark Open.
