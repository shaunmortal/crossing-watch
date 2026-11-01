# For judges: where each claim is proved

Solo Indie entry: one phone video of a dangerous crossing becomes near-miss evidence and a letter the school signs.
Each claim links to its proof. **Pending** = not done yet; what needs the gate recording (Mon 2 Nov) is `[PLACEHOLDER]`.

## Only in Crossing Watch
- **The loop up to filing; filing pending Tue 3 Nov:** a phone video becomes measured near-misses and a code-checked
  letter for the college to sign and seal (Principal and HOD signed the project application on 31 Oct; 19 teachers
  signed in support); the filing with the road authority is **pending** (Tue 3 Nov).
- **Measured against ground truth:** drone-tracked DUT clips, 47 of 52 near-misses found after Muse Spark's review
  (50 of 52 by geometry alone); SinD, speed error 0.24 km/h mean, 37 of 63 crossings within 3 s.
- **Our open-weights judge beats Muse Spark Open on 1,016 blind rows** (from 260 synthetic letters, protocol written
  down first): a LoRA on Muse Glimmer, 998 right vs Spark Open 980 (p 0.0051), at about half its cost per letter.
  Against Muse Spark (959) the pre-registered win stands as recorded, but it rests on our prompt's wording (below).
- **Checked by people, not only models:** teachers rate the clips blind against the measurements (**pending**, Tue).
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
  signed and sealed the application (filming on Mon 2 Nov approved; the HOD may sign the letter for the college), and
  19 teachers signed a support sheet (18 agreed to be named publicly). The signed paper stays off the repo.
- The output is something an authority can act on: a letter where code checks every number, plus legal quotes added
  by code, never a model (2025 INSC 1189). [README, How it works](README.md#how-it-works), `gazette.py`.
- **Pending:** our gate's headline [PLACEHOLDER: k of n crossings, from Monday's run]; letter signed by the HOD
  (Tue 3 Nov); filing (Tue 3 Nov). Only "filed, reference X" will ever be written as filed.

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
- Gates written before results ([GATES.md](GATES.md)): G1 passed; G3 passed on DUT only; the rest are pending.

## Use of Meta models

- Six models, each with a job: SAM 3.1 (tracking), Muse Spark (review, letter, judge), Muse Image (the fix on the
  real street), Muse Wonder (sound), Muse Glimmer 30B and Muse Spark Open (open weights): [README](README.md) top.
- Letter checks scored on planted lies: [README, Checking the checks](README.md#checking-the-checks). Public bench
  at $0 (code column and Muse Spark's cached replies): `python3 judge_bench.py --public`.

## Open Weights bonus

- Fine-tuned Muse Glimmer judge (LoRA, training $0), pre-registered blind tests, labels frozen before any tuned reply
  was read. **v4, 1,016 rows from 260 synthetic letters: 998 right vs Muse Spark Open 980 (28 vs 10, p 0.0051)**,
  mostly lies Spark Open missed; clean rows flagged 5/491 vs Spark Open 4/491. In-distribution letters only.
- Against Muse Spark (959 right, 49/491 clean rows flagged) the pre-registered result stands as recorded (57 vs 18,
  p 7.2e-06), but 41 of Spark's 49 false alarms are only about ordinals ("second", "third") or the method sentence
  (SAM tracking, road-plane geometry). Our judge prompt's "a number above one written in words" invites flagging
  ordinals, and the tuned judge learned our reading from its training labels. Set those 41 aside and it is 16 vs 18,
  p 0.86: not a win. v3 (417 rows, 410 vs 396, p 0.0066) has the same catch: 11 of Spark's 15 false alarms;
  set aside, 8 vs 5, p 0.58.
- Disagreements with the generator's labels were adjudicated by an AI agent (Claude, Anthropic), blind to the tuned
  replies, under written standards; it only ever moved labels from clean to planted (v4 12, v3 5) or excluded a row
  (v4 1).
  [GATES.md v3 and v4 results](GATES.md); replies and frozen labels: `provenance/glimmer-judge-lora-v3/` and `-v4/`;
  re-score: `python3 judge_v3_score.py v4`.
- Muse Glimmer 30B self-hosted on Kaggle's free 2 x T4 from sha256-checked weights wrote the sample letter
  ([<removed-run-record>](<removed-run-record>)); writers table at $0: `python3 writers_table.py`.
- Each closed-model step's open substitute, measured: [Spark-free mode](kaggle/open-weights.md#spark-free-mode).

## Agentic bonus

- `agent.py`: Muse Spark (or Spark Open via `openagent.py`) works the case through 5 tools and stops to ask a person
  to tape-measure a distance; the letter is refused until video and tape agree within 15% ([README, Case
  agent](README.md#case-agent-it-stops-to-ask-for-a-tape-measure)).
- One run, Spark Open on a copy of the sample: `provenance/spark-open-agent-sample.json`; a scripted-model test is in
  `test_cw.py`. **Pending:** a run on the gate footage.

## Creative bonus

- Muse Image draws the fix only inside the strip where people were measured crossing; every other pixel stays the
  real, blurred street. Muse Wonder listens around each near-miss for horns, brakes and shouts. `fixband.py`,
  `ailabel.py`, `listen.py`. **Pending:** [PLACEHOLDER: the Muse Image fix for our gate].

## Known limits

- The gate is not filmed yet (Mon 2 Nov). G2, G4, G5, G6 and G8 have not run; G7 has no verdict before submission.
- All ground truth (DUT, SinD) is top-down drone footage: no one is hidden. Phone-angle numbers are simulations.
- The open-weights judge's win over Muse Spark rests on a prompt ambiguity (above); its win over Spark Open holds,
  on synthetic, in-distribution letters only, and on the 260 letters as written it is level with Spark Open (251 vs
  254, p 0.51).
- A Muse judge reading Muse letters is not independent. The tuned judge missed all six real slips the letter writers
  made themselves in v4 (Spark caught six); a code check added afterwards (`pack.slips`, GATES.md) now catches 11 of
  the 12 slip rows with no false alarm, but it was built from those rows, so that is not a blind result.
- No agent run against the Meta API yet; the Kaggle notebook is not public yet. Muse Image measures nothing, and
  Muse Wonder's sound check is not ground truth.
