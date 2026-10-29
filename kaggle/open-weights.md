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
