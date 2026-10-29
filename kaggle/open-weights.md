# Open weights: the public judge bench

`kaggle/judge-bench-public.json` is the judge bench built only from letters about the synthetic `sample/` (made-up
tracks, no video), so it can go in the repo, a Kaggle dataset or a public release. No base letter comes from DUT,
SinD, a YouTube clip or kids' footage; `test_cw.py` checks that, and every item names its base's source.

Build it (offline, scores the code check only): `python3 judge_bench.py --public`

| Base | Writer | Where the text is | Source |
|---|---|---|---|
| `glimmer` | Muse Glimmer 30B, open weights, self-hosted on Kaggle 2 x T4 | quoted in `<removed-run-record>` | `sample/` |
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

It catches only the two kinds with a number in them: a count in words and km/h written as mph. The Muse Spark and
Muse Glimmer columns are empty until a paid run fills them (`--spark N`, `--glimmer N` with the same file).

Note on the clean controls: both base letters offer to share "the video", and the measurements say the sample has no
video. A judge that flags a control for that is arguably right, so read the false-alarm row with that in mind.

## Two votes for an open-weights judge (`JUDGE_VOTES=2`)

Asked once, Muse Glimmer as judge flagged 24 of 24 planted lies but also 6 of 8 clean letters (Muse Spark: 24/24 and
1/8; `<removed-run-record>`, the v2 run). `JUDGE_VOTES=2` is opt-in and applies only to the
`JUDGE_MODEL_URL` judge: it is asked twice per letter, and a problem counts only when both replies list one
(`pack.vote`). In `pack.py` that is the open judge's verdict on each try at the letter; in `judge_bench.py` it is the
Glimmer column's verdict per run, with both raw replies and the vote kept under `glimmer_votes` in the bench file and
a line under the table saying how many runs were votes. A reply that cannot be read makes the vote unreadable: counted
apart in the bench, and one problem to check in `pack.py`, never a pass. Muse Spark is always asked once.

Notebook Version 3 (`<removed-run-record>`) keeps every Version 2 pin (llama.cpp `b11976`, the model's
revision and sha256 checks, `-c 32768`, medium reasoning, the card's sampling), saves `plan.json` and
`glimmer-letter.txt` (the sample letter) as outputs, and judges this public bench with `JUDGE_VOTES=2`, saving
`judge-bench-public.json` (every letter, both raw replies, the vote) next to `<removed-run-record>`. Glimmer's
2-vote numbers are not measured yet: they come from that run.
