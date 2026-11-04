# Base Muse Glimmer 30B against the tuned judge (4 Nov 2026)

The pre-registration and the result are in GATES.md ("Base Glimmer against the tuned judge"). Base Muse Glimmer 30B
(no LoRA) served once on a Fireworks on-demand deployment (1 x H200, BF16; created 20:13 IST, ready 20:16, deleted
21:27; about 71 GPU-minutes at $8 per GPU-hour), given the v6 holdout prompts with temperature 0, an 8,192-token
reply cap, JSON mode and its default reasoning, in a seeded shuffle for 70 minutes.

| File | What it is |
|---|---|
| `predictions_base.jsonl` | 1,246 replies, each with its Fireworks response id, finish reason, usage and wall time |
| `score.json` | the score by the pre-registered rule, and the finished-rows sensitivity |
| `score_base.py` | the scorer (v6's frozen labels and head-to-head sign test, as `kaggle/score_kaggle.py`) |
| `replay_base.py`, `base_v6.sh` | the run as it was done (account id masked) |
| `run.log` | the deployment's create, ready, replay and delete lines |

Result in one line: on the same 1,210 blind rows, base 781 right (773 verdicts still reasoning at the cap), the
tuned judge 1,163; where base finished (437 rows, 389 of them planted) it was right on 429 against the tuned judge's
418. Re-score at $0: `python3 provenance/glimmer-judge-lora-v6/base/score_base.py provenance/glimmer-judge-lora-v6/base/predictions_base.jsonl`.
