# Open weights in Crossing Watch: what runs, what we measured, how to check it

One page for the Open Weights review. Every number links to committed files and re-scores at $0.

## What the open-weights models do here

| Job | Open-weights model | Where it runs | Measured result |
|---|---|---|---|
| Write the letter to the road authority | Muse Glimmer 30B (sha256-checked GGUF) | Kaggle, free 2 x T4, llama.cpp | sample letter in 313 s, every number passed the code check ([record](<removed-run-record>)) |
| Write the letter, fast path | Muse Spark Open | Fireworks | sample letter in 55.5 s, $0.012 ([writers table](kaggle/open-weights.md#writers-table)) |
| Check the letter for unsupported claims | **Muse Glimmer 30B + our LoRA** (fine-tuned, training $0) | Fireworks Serverless Training | beats Muse Spark Open in three blind tests (below) |
| Decide whether a tracked person is a pedestrian | Muse Spark Open | Fireworks | on drone ground truth (DUT): 49 of 52 near-misses kept vs Muse Spark's 47 ([table](kaggle/open-weights.md#spark-free-mode)) |

## The fine-tuned judge: three pre-registered blind tests

Each test was written down in [GATES.md](GATES.md) before any letter, label or run; labels were frozen and committed
before any tuned reply was read. Rows are synthetic letters written by Muse Spark and Muse Spark Open, with lies and
slips planted by templates, by code and by the models themselves.

| Test (new rows) | Tuned Glimmer | Muse Spark Open | Muse Spark | Tuned vs Spark Open | Tuned vs Spark |
|---|---|---|---|---|---|
| v4 (1,016) | 998 | 980 | 959 | **28 vs 10, p 0.005** | ahead only through a prompt ambiguity, since fixed |
| v5 (1,278), prompt fixed | 1,260 | 1,247 | 1,271 | **22 vs 9, p 0.029** | Spark ahead, p 0.043 |
| v6 (1,501) | 1,442 | 1,403 | 1,467 | **82 vs 43, p 0.0006** | Spark ahead, p 0.011 |

- **What holds every time:** the tuned open model beats Muse Spark Open, the open-weights baseline.
- **Muse Spark (closed) stays ahead overall.** It catches more lies a model words in its own way and more slips the
  letter writers make themselves. We report this as measured; no test is left out.
- **Cost:** about 26 output tokens per verdict; about $2.90 per 1,000 letters at Fireworks' Glimmer sampling price, vs
  Muse Spark Open $5.66 and Muse Spark $10.33 (v4 token counts).
- **Found after the fact (v6, not pre-registered):** as a second reviewer beside Muse Spark, the tuned judge adds
  more than Muse Spark Open does (Spark OR tuned vs Spark OR Spark Open: 20 vs 6 discordant, p 0.009).
- **Label checks:** disagreements were adjudicated by an AI agent (Claude), blind to the tuned replies; a later
  symmetric audit of the rows only the tuned judge disagreed with changed 0 of 72 labels.

## Check it yourself ($0, no key)

```
python3 judge_v3_score.py v4     # also v5, v6; reads the frozen labels and every committed reply
python3 judge_compare.py         # the v2 same-set table
python3 writers_table.py         # Glimmer on Kaggle vs Spark Open vs Muse Spark as letter writers
```

- Model ids, training logs, data and every reply: `provenance/glimmer-judge-lora-v{3,4,5,6}/`, `kaggle/glimmer-judge-train-v*.jsonl`.
- Glimmer on Kaggle: `<removed-run-record>`, `<removed-run-record>` (weights' sha256, llama.cpp build).

## Limits, stated

- The test letters are synthetic; on the 260 letters as written the tuned judge is level with Muse Spark Open.
- The LoRA adapter cannot be downloaded from Fireworks yet (we asked Fireworks to enable it); the organizers confirmed
  committed model ids, logs, outputs and a re-score script are the reviewable material. Self-hosting it on Kaggle is
  ready (`kaggle/glimmer-judge-lora.ipynb`) once the files are released.
- A planned v7 was cancelled before any letter was written, after a review found it underpowered (GATES.md).
- Built with Muse Spark Open: the adapter is trained partly on letters Spark Open wrote and follows the Muse Model License.
