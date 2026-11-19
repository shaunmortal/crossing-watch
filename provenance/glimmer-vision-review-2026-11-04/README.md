# Muse Glimmer 30B as the crop reviewer (Wed 4 Nov 2026)

**Question:** can our open model do Muse Spark's job as the crop reviewer? The reviewer (`review.py`) looks at one
zoomed crop with a thin cyan box and decides whether the boxed figure is a pedestrian on foot, or a rider / not a
person. We ran Muse Glimmer 30B (open weights, with its vision encoder) in Spark's place, using the product's own
prompt, the product's own call and the exact crops Spark saw. The scoring rule and the win bars went into
[RULE.md](RULE.md) at 01:28 IST, before any model call, and were not changed afterwards.

## Result

| Set | Muse Glimmer 30B | Muse Spark | Muse Spark Open |
|---|---|---|---|
| **A. Our gate, 32 reviewed people:** same keep/remove call as Spark | **32 of 32** | (reference) | 32 of 32 |
| A: right on the reference labels (Spark's calls plus the GATES.md by-eye rulings) | 31 of 32 | 31 of 32 | 31 of 32 |
| A: the 3 people seen walking by eye are kept | 3 of 3 | 3 of 3 | 3 of 3 |
| **B. DUT drone ground truth, crowd mode:** near-misses found of 52 | **50** | 47 | 49 |
| B, crowd mode: extra (false alarms) | 4 | 3 | 3 |
| B, crowd mode: real near-misses removed by the reviewer | **0** | 3 | 1 |
| B, vehicle crowd mode (secondary): found of 52 / extra | 49 / 4 | 48 / 4 | 48 / 3 |
| Replies the product could not read | 0 of 137 | | 0 of 32 (A) |

- **A, our gate: Glimmer meets RULE.md's bar.** It gives Spark's keep/remove call on 32 of 32 people, and keeps
  c169/0, c483/0 and c589/0, the three people GATES.md saw walking. Muse Spark Open, asked the same 32 crops today,
  also scores 32 of 32, so on A the two open models tie. All three models keep c116/0, which GATES.md rules out by
  eye. In the one crop the models saw, that person looks like someone standing, so the reference-label score is 31 for
  each model.
- **B, DUT: Glimmer finds the most near-misses, with one more false alarm.** With no reviewer at all, the geometry
  finds 50 of 52 with 5 extra. Glimmer kept every real near-miss (50) and removed 1 of the 5 false alarms. Spark and
  Spark Open each removed 2 false alarms, but Spark also removed 3 real near-misses and Spark Open removed 1. In crowd
  mode Glimmer's one extra false alarm beyond theirs is a serious event at 4.6 s in clip 09; in vehicle crowd mode
  Spark keeps that same event.
- **By the rule fixed in advance, "Glimmer can replace Spark's eyes" is not claimed.** "Level with Spark" on B needs
  at least 47 found with at most 3 extra. Glimmer has 50 found but 4 extra, so it misses the extra-alarm bar by one.
  Against Muse Spark Open, B is a trade under the rule, not a win: one more near-miss found, one more false alarm.

## What ran, where, when

- **Model:** `accounts/fireworks/models/muse-glimmer-30b`, the base model with no LoRA (weights:
  `meta-models/Muse-Glimmer-30B`). Fireworks shows no revision hash for its hosted base, so we pinned what it does
  show: the model record's update time, 2026-09-29T02:07:33Z, and the serving shape version below. The model record
  says `supportsImageInput: true` and `supportsServerless: false`.
- **Serve route:** Fireworks has no serverless route for this model, so it ran on an on-demand deployment, the
  cheapest shape that serves it. That is the same route the repo used for the LoRA judge: shape "Muse Glimmer 30B BF16
  1x H200" (`accounts/fireworks/deploymentShapes/dkuwotf7`, version `vtcy28lv`), 1 replica, BF16. Fireworks lists
  H100 and H200 at the same $8 per GPU-hour, billed per second, with start-up not billed (fireworks.ai/pricing, read
  4 Nov 2026).
- **When (UTC, 3 Nov; IST is +5:30, so 4 Nov 01:31 to 01:42):**
  - create requested 20:01:06; ready 20:04:47;
  - smoke call 20:04:50; set A 20:04:50; set B 20:06:32; done 20:11:27;
  - delete requested 20:11:27; state DELETED by 20:12:00.
  - Full log: [run-log.txt](run-log.txt) and [deployment.json](deployment.json).
- **Request:** the product's own `review.ask_open` (the `REVIEW_MODEL_URL` path): `review.PROMPT`, the crop as a JPEG
  data URL, `response_format: json_object`, `reasoning_effort: low`, plus `temperature: 0`. Replies were read by
  `review.read_verdict`. A smoke call on a blank grey synthetic image checked image input first ("uniform gray image
  with no discernible object"). It needed no parameter change and is not scored.
- **Set A:** the 32 people Spark reviewed among the gate run's 75 near-miss candidates, each on the very crop Spark
  saw. Each crop was checked against the `inputs_sha256` in Spark's saved reply (crop bytes, model, prompt, view): all
  32 match.
- **Set B:** the repo's own scorer, `validate_offline.py DUT_REPO dut-15s dut-vcrowd --reviewer open`. It ran on
  private copies of the cached runs, so Spark's and Spark Open's saved replies stayed untouched. That gave 105
  Glimmer calls (53 crowd, 52 vehicle crowd). Before any call, the baselines were re-scored at $0 on the same copies,
  and they reproduce the published numbers (Spark 47/3 and 48/4; Spark Open 49/3 and 48/3).
- **Muse Spark Open on A:** Fireworks serverless, with the product's settings (effort low, no temperature), 32 calls.
  This gives set A an open-model baseline; Spark Open's numbers on B are its 31 Oct run, re-scored today.
- Glimmer: 137 replies (32 + 105) plus the smoke call. Every reply finished with "stop", none was unreadable, and the
  median call took 2.2-2.8 s. Spark Open on the same 32 gate crops took a median 7.3 s.

## Cost

| Item | Basis | USD |
|---|---|---|
| Glimmer deployment, 1 x H200 | ready 20:04:47 to delete 20:11:28.6 = 402 s at $8/h (start-up free) | 0.89 |
| Muse Spark Open, set A | 14,496 in x $1.25/M + 7,659 out x $4.25/M | 0.05 |
| Baselines, model metadata, scoring | no model calls | 0 |
| **Total** | | **about $0.94** (at most $1.43 if the 3.7 min start-up were billed) |

## Deletion

- Deployment `cw-glimmer-vision` was deleted by the script's exit trap.
  - DELETE answered at 20:11:29Z, state DELETING.
  - At 20:12:00Z the state was DELETED and the deployments list was empty.
- Checked again independently at 20:13:47Z:
  - GET deployment: state DELETED, replicaCount 0, deleteTime 2026-11-03T20:11:28.55Z;
  - deployments list: `[]`.
- [deployment.json](deployment.json) holds that record, with the account id removed.

## Limits

- **On A, the reference is mostly Spark itself.** On 28 of 32 rows the label is Spark's call, so A measures whether
  Glimmer can stand in for Spark, not whether either one is right. Only 4 rows carry a by-eye ruling.
- **Glimmer is lenient on drone crops.**
  - It answered "unclear" on 36 of the 105 DUT crops; Spark Open, on the same crops, answered "unclear" 13 times.
  - The product keeps an "unclear" person, so Glimmer removed only 4 of 105 pieces (Spark Open removed 13).
  - DUT's crossers are pedestrians, so leniency costs little there. Our gate is full of riders, and there Glimmer
    removed 28 of 32, exactly as Spark did. But that is 32 people on one camera.
- **Some rows are scored on the call alone.** On 3 gate rows (c107/0, c180/0, c629/0), Glimmer answered road user
  "adult" but "not a pedestrian", where Spark said "rider". The decision is "remove" either way. In the product,
  though, such a call goes through the walking-pace rule rather than the rider gate. Neither rule needs the model, and
  set A does not apply them (on Spark's 32 calls they changed nothing). Set B applies both.
- **Small samples, one run.**
  - n is 32 and 52, so there is no significance test; RULE.md said so in advance.
  - Glimmer ran once, at temperature 0. Spark Open's B numbers come from its 31 Oct run with Fireworks' default
    temperature.
- **Not public:** the crops (real people) and the DUT data. Both stay out of the repo.
  - The reply logs carry verdicts, response ids, token counts and the model's one-line reason. The reason is blanked
    when it holds a digit, as the product does before showing a reason.
  - The B scores re-run only with the DUT data and our cached runs. The A scores re-run at $0 from the logs here
    (`python3 score.py`).

## Files

| File | What |
|---|---|
| [RULE.md](RULE.md) | scoring rule and win bars, written before any call |
| [results.json](results.json) | every score above (`score.py` output; B totals per model and mode) |
| `replies-A-glimmer.jsonl`, `replies-A-spark-open.jsonl` | one row per gate crop: response id, verdict, Spark's call, tokens |
| `replies-B-glimmer.jsonl` | one row per DUT crop: response id, verdict, tokens |
| `smoke.jsonl` | the blank-image smoke call |
| [run-log.txt](run-log.txt), [deployment.json](deployment.json) | serve log and the deployment record after deletion |
| `serve.sh`, `run_review.py`, `score.py` | create, run, always delete; the product call with logging; the scorer |
