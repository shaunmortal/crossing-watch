# Can Muse Glimmer 30B replace Muse Spark's eyes? Scoring rule, fixed before any model call

Written Wed 4 Nov 2026, 01:28 IST (2026-11-03T19:58Z), before any Glimmer or Spark Open call in this test. It is not
changed after results are seen; anything added later goes in README.md, marked as added after the results.

## The job

The crop reviewer (`review.py`) looks at one zoomed crop with the person in a thin cyan box and answers whether it is
a pedestrian on foot, or a rider / not a person. Today Muse Spark does this. The test puts Muse Glimmer 30B (open
weights, `accounts/fireworks/models/muse-glimmer-30b`) in Spark's place with the same prompt and the same crops.

## What Glimmer is sent

- The product's own call, `review.ask_open` (the `REVIEW_MODEL_URL` path): `review.PROMPT` with the same view text
  Spark was given, the crop as a JPEG data URL, `response_format: json_object`, `reasoning_effort: low`. Added:
  `temperature: 0`. No `max_tokens` (the product sends none).
- One smoke call on a blank, synthetic image (no person, not in either set) checks that the deployment takes images
  and these parameters. If the server rejects a parameter there, that parameter is dropped for the whole run and
  the README says so. The smoke reply is not scored.
- Each crop is asked once. A transport failure (no HTTP 200: timeout, 429, 5xx) is retried, at most 3 tries; any reply
  that arrives is final.
- A reply is read by the product's own `review.read_verdict`. A reply it cannot read counts as **wrong** (below).

## Set A: our gate (`out/gate`, 75 near-miss candidates, 32 people reviewed)

- Rows: the 32 pieces Muse Spark reviewed in the gate run's `events.json`, each with the exact crop Spark saw. Before
  any call, each crop was checked: SHA-256 of (crop bytes, Spark's model id, `review.PROMPT`, view text) equals the
  `inputs_sha256` Spark's saved reply carries. All 32 match, view = traffic camera (not top-down).
- Decision per row: **keep** if `read_verdict` says `is_person`, or its `road_user` is `"unclear"` (`review.gated`
  keeps an unclear call); otherwise **remove**. The rider gate and the walking-pace rule need SAM geometry and are not
  applied here (on these 32 they changed none of Spark's calls). Unreadable = the opposite of Spark's decision.
- **Primary (A):** agreement with Muse Spark's keep/remove decision, x of 32. Spark's decisions: 4 keep (c116/0,
  c169/0, c483/0, c589/0), 28 remove.
- **Secondary (A):** right against the reference labels: Spark's decision, except where GATES.md records a ruling by
  eye ("The gate run: one track ruled out by eye", 2 Nov): c116/0 is **not** a pedestrian; c483/0, c169/0 and c589/0
  walk across on foot (keep). Reference: 3 keep, 29 remove. Muse Spark scores 31 of 32 on it.
- **Context (A):** Muse Spark Open (Fireworks serverless, product settings: effort low, no temperature) is asked the same
  32 crops once in this test, so A has an open-model baseline too. Same scoring.
- Also reported, not scored: exact `road_user` match with Spark.

## Set B: DUT drone ground truth (52 conflicts)

- Scorer: the repo's own, `validate_offline.py DUT_REPO RUNS --reviewer open` (rebuilds the cached runs at $0, re-asks
  the reviewer about every reviewed piece, applies `review.gated`, scores with `validate_dut.compare`). It is run on
  private copies of the cached runs so the saved Spark and Spark Open replies stay untouched.
- Baselines, re-scored at $0 on those copies before any call (they reproduce the published numbers):
  - **Primary, crowd mode (`dut-15s`):** Muse Spark 47 of 52 found, 3 extra; Muse Spark Open 49 of 52, 3 extra.
  - **Secondary, vehicle crowd mode (`dut-vcrowd`):** Muse Spark 48 of 52, 4 extra; Muse Spark Open 48 of 52, 3 extra.
- Glimmer's numbers: `matched` (found of 52) and `extra` from that scorer.
- Unreadable or failed reply = wrong: the scorer leaves such a piece unreviewed (kept). If any piece is unreviewed,
  the headline "found" is re-scored at $0 with every such piece removed (its true conflicts lost) and the headline
  "extra" keeps them (the as-scored count). Both are reported.

## What counts as a win

- **A, Glimmer can stand in for Spark on our gate:** agreement with Spark at least 30 of 32, **and** all 3 by-eye
  walkers (c169/0, c483/0, c589/0) kept.
- **B, level with Spark:** found at least 47 of 52 with at most 3 extra (crowd mode). **Beats Spark:** found more than
  47 with at most 3 extra, or 47 with fewer than 3 extra.
- **B, beats Muse Spark Open:** found more than 49 with at most 3 extra, or 49 with fewer than 3 extra. Found 49 with
  3 extra is a **tie**. Anything else is a loss to Spark Open.
- **Beats Spark Open on A:** more agreement with Spark than Spark Open's (secondary: more right on the reference
  labels). Equal is a tie.
- **"Glimmer can replace Spark's eyes"** is claimed only if the A win and "B level with Spark" both hold.
- Counts only, no significance test: n is small (32 and 52), and the README says so. Every result is reported,
  including a loss.
