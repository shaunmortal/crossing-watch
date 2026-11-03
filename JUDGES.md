# For judges: where each claim is proved

Solo Indie entry: one phone video of a dangerous crossing becomes near-miss evidence and a code-checked letter to the road authority.

**Try it in a browser, no key:** [App](https://crossingwatch.xyz/app/) (press *Try it with our gate*) · [Explorer](https://crossingwatch.xyz/explorer/) · [Manual](https://crossingwatch.xyz/manual/) · [Evidence dashboard](https://crossingwatch.xyz/evidence/). Every page has a हिंदी / English switch.
Each claim links to its proof.

## Only in Crossing Watch
- **The whole loop, on our real gate:** a phone video becomes measured near-misses and a code-checked
  letter to the road authority (Principal and HOD signed the project application on 31 Oct; 19 teachers
  signed in support). On 3 Nov 2026 the college certified in writing that the footage was filmed at its gate with permission and that the report is genuine.
- **Measured against ground truth:** drone-tracked DUT clips, 47 of 52 near-misses found after Muse Spark's review
  (50 of 52 by geometry alone); SinD, speed error 0.24 km/h mean, 37 of 63 crossings within 3 s.
- **Our open-weights judge beats Muse Spark Open in three blind tests:** a LoRA on Muse Glimmer, protocols written
  down first: p 0.005 (1,016 rows), 0.029 (1,278), 0.0006 (1,501), at a quarter of Spark's cost. Muse Spark is still
  ahead overall (v6: 1,467 vs 1,445 right).
- **Built for India:** a Hindi copy of the letter, the HOD's spoken notes, Supreme Court and IRC references.

## 5-minute path

1. `python3 test_cw.py` (Python 3.11+ and ffmpeg; about 30 s, no key, no video) and `python3 pack.py sample
   sample/site.json`, then open `sample/index.html`: the measurements page built offline from a synthetic sample.
   Without a key it has no letter ("letter failed" is expected); the sample's letters are in
   `provenance/spark-open-sample-letter.txt` and `<removed-run-record>`.
2. Read [kaggle/open-weights.md, v4](kaggle/open-weights.md#v4-1016-blind-rows-pre-registered-against-both-muse-judges):
   our fine-tuned open-weights judge against both Muse judges on 1,016 blind rows.
3. Read [GATES.md, Verdict now](GATES.md#verdict-now): what was pre-registered, what passed, what has not run.
4. Read [README, Limits, stated](README.md#limits-stated) and the known limits below.
5. Watch the demo: [PLACEHOLDER: demo video link]. Our gate's evidence page: [PLACEHOLDER: GitHub Pages link].

## Impact

- A real institution is behind it: on 31 Oct 2026 the Principal and the HOD (CSE-DS) of LNCT Excellence, Bhopal
  signed and sealed the application (filming on Mon 2 Nov approved; on 3 Nov the college certified the report genuine), and
  19 teachers signed a support sheet (18 agreed to be named publicly). The signed paper stays off the repo.
- The output is something an authority can act on: a letter where code checks every number, plus legal quotes added
  by code, never a model (2025 INSC 1189). [README, How it works](README.md#how-it-works), `gazette.py`.
- **Our gate (Mon 2 Nov):** In 8.6 minutes of our gate's dismissal, 80 pedestrian crossings among 55 moving vehicles: 2 serious near-misses (one person and motorcycle on the same spot at the same instant) and 3 close passes; the video's 15.0 m matched the tape's 15 m. [README](README.md), [GATES](GATES.md#verdict-now).
  On 3 Nov 2026 the college certified in writing that the footage was filmed at its gate with permission and that the report is genuine.

## Demo

- Today, at $0: `python3 pack.py sample sample/site.json` builds the page offline (no key, no video).
- **Pending:** [PLACEHOLDER: 3-minute demo video], [PLACEHOLDER: evidence page and release zip], from Monday's footage.

## Depth

- Near-miss maths on drone ground truth (SinD, public sample): 37 of 63 crossings within 3 s, speed error 0.24 km/h
  mean, 0.91 km/h at the 95th percentile ([README, SinD](README.md#validation-on-ground-truth-trajectories)). At $0
  after downloading SinD: `python3 validate_sind.py data/sind`.
- SAM 3.1 end to end against DUT drone ground truth: 47 of 52 conflicts after Muse Spark's review (50 of 52 by
  geometry alone; crowd mode), 48 of 52 (vehicle crowd mode).
  [README, DUT](README.md#end-to-end-against-ground-truth-dut),
  [GATES.md, 30 Oct re-score](GATES.md#accuracy-fixes-merged-re-scored-at-0-fri-30-oct-2026). Not re-runnable by a
  judge: DUT has no licence, so its footage and our cache stay private; read the record.
- Gates written before results ([GATES.md](GATES.md)): G1 passed; G2 (our gate: 15.0 m vs 15 m taped) and G4 (our footage, end to end) passed; G3 passed on DUT.

## Use of Meta models

- Six models, each with a job: SAM 3.1 (tracking), Muse Spark (review, letter, judge), Muse Image (the fix on the
  real street), Muse Wonder (sound), Muse Glimmer 30B and Muse Spark Open (open weights): [README](README.md) top.
- Letter checks scored on planted lies: [README, Checking the checks](README.md#checking-the-checks). Public bench
  at $0 (code column and Muse Spark's cached replies): `python3 judge_bench.py --public`.

## Open Weights bonus

- One page for the review, with $0 checks: [OPEN_WEIGHTS.md](OPEN_WEIGHTS.md).

- Fine-tuned Muse Glimmer judge (LoRA, training $0), pre-registered blind tests, labels frozen before any tuned reply
  was read. **v4, 1,016 rows from 260 synthetic letters: 998 right vs Muse Spark Open 980 (28 vs 10, p 0.0051)**,
  mostly lies Spark Open missed; clean rows flagged 5/491 vs Spark Open 4/491. In-distribution letters only.
- Against Muse Spark: ahead in v4 only through a prompt ambiguity; with the prompt fixed, Muse Spark wins v5 (p 0.043)
  and v6 (p 0.023), though v6 beats it on model-written slips. Full record: [open-weights.md](kaggle/open-weights.md). Labels were
  adjudicated by an AI agent, blind to the tuned replies. [GATES.md v3 and v4 results](GATES.md); replies and frozen labels: `provenance/glimmer-judge-lora-v3/` and `-v4/`;
  re-score: `python3 judge_v3_score.py v4`.
- Muse Glimmer 30B self-hosted on Kaggle's free 2 x T4 from sha256-checked weights wrote the sample letter
  ([<removed-run-record>](<removed-run-record>)); writers table at $0: `python3 writers_table.py`.
- Each closed-model step's open substitute, measured: [Spark-free mode](kaggle/open-weights.md#spark-free-mode).

## Agentic bonus

- `agent.py`: Muse Spark (or Spark Open via `openagent.py`) works the case through 5 tools and stops to ask a person
  to tape-measure a distance; the letter is refused until video and tape agree within 15% ([README, Case
  agent](README.md#case-agent-it-stops-to-ask-for-a-tape-measure)).
- One run, Spark Open on a copy of the sample: `provenance/spark-open-agent-sample.json`; a scripted-model test is in
  `test_cw.py`. On our gate: "Video 15.0 m, tape 15 m, 0% off: proven", then it stopped at needs_review.

## Creative bonus

- Muse Image draws the fix only inside the strip where people were measured crossing; every other pixel stays the
  real, blurred street. Muse Wonder listens around each near-miss for horns, brakes and shouts. `fixband.py`,
  `ailabel.py`, `listen.py`. On our gate: [the fix](docs/story/09-fix.jpg), a painted zebra crossing and College Zone 20 km/h signs.

## Known limits

- Our gate was filmed hand-held from the highway and stabilized before analysis; counts cover the taped 15 m stretch
  (GATES.md). G5, G6 and G8 have not run; G7 has no verdict before submission.
- All ground truth (DUT, SinD) is top-down drone footage: no one is hidden. Phone-angle numbers are simulations.
- The open-weights judge is tested on synthetic letters; on the 260 letters as written it is level with Spark Open.
- A Muse judge reading Muse letters is not independent. The tuned judge missed all six real slips the letter writers
  made themselves in v4 (Spark caught six); a code check added afterwards (`pack.slips`, GATES.md) now catches 11 of
  the 12 slip rows with no false alarm, but it was built from those rows, so that is not a blind result.
- The Kaggle notebook is not public yet. Muse Image measures nothing, and
  Muse Wonder's sound check is not ground truth.
