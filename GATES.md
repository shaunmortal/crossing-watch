# Crossing Watch: pre-registered gates

Written Wed 28 Oct 2026, before running the full pipeline on real footage. These conditions do not change after results come in.

| Gate | Pass condition | Test footage | Due (IST) |
|---|---|---|---|
| G1 Tracks | SAM 3.1 keeps one ID on each crossing pedestrian for at least 80% of the time they are visible | news CCTV `sites/kids-cctv.json` | passed 28 Oct (2 of 2 crossers, 150/150 frames) |
| G2 Metres | A road distance NOT used for calibration (a second lane width, or crossing-line length) comes out within ±15% of its assumed value | same | Wed 28 Oct 22:00 |
| G3 Conflicts | Checked by eye, at least 2 of the top 3 events are real close passes, and no event involves a parked or queued vehicle | same | Thu 29 Oct 22:00 |
| G4 Own footage | Footage filmed from height at the user's college gate runs end to end, with calibration from measured points | user's video | Sun 1 Nov 22:00 |
| G5 Blind check | A transport or civil engineering lecturer, not told which clips the pipeline flagged, agrees with it on danger vs none with Cohen's kappa of 0.6 or more (rules below, written before any clip is made) | the gate pack | Tue 3 Nov 22:00 |

**Scope cut if G3 fails:** report the closest approach in metres plus vehicle speed (no PET). The evidence pack and letter still ship.

**Known limits (stated, not hidden):** a vehicle's lower box edge stands in for its footprint; up to 16 objects per SAM video request (found later: in all, not per frame); one concept per SAM request; calibration lengths on the news clip are assumed.

## Status (Wed 28 Oct, evening, written by the agent)

- **G1** passed (see table).
- **G2 not yet tested.** Both test clips were calibrated from assumed lengths, so no independent measured distance exists. This waits for the user's footage with measured points.
- **G3 partial.**
  - On the schoolchildren CCTV clip, the pipeline reports 1 event. It is a pole tracked as a person, and Muse Spark rejects it, so the evidence pack shows 0 near-misses. Checked by eye: no real close pass happened there (the children were 1.4 m or more from slow, turning cars). So: no false alarm in the final output, but no true positive tested yet either.
  - The Indian intersection clip (rough calibration) gives 0 events after the review fixes.
  - A true positive needs footage with a real near-miss.
- A 13-agent review found 14 confirmed defects, all fixed:
  - speed teleports from ID switches;
  - a person who waits and then crosses was dropped as static;
  - people waiting on the pavement counted as conflicts (optional `roadway_m` polygon added);
  - sort by danger, not by PET alone;
  - boxes cut off at the frame edge;
  - out-of-order calibration points;
  - cache reuse across videos;
  - atomic clip preparation;
  - site validation;
  - events saved before the evidence step;
  - empty SAM boxes;
  - unsafe cache names;
  - prep_filter whitelist;
  - snapshot frame choice.

## Status update (Wed 28 Oct, late night)

- A second 11-agent review found 13 confirmed defects, all fixed:
  - a rejected pole came back through unreviewed events;
  - an odd Muse Image or Spark reply stopped the page from being written;
  - the static test was all-or-nothing (now long still stretches are dropped per window, so waiting then crossing keeps the crossing);
  - split_at_jumps missed jumps across tracking gaps;
  - a teleport frame got a speed;
  - evidence used the whole SAM id instead of the event's track piece;
  - pedestrians in front of buses were removed as riders;
  - person boxes cut off at the frame bottom;
  - calibration frame-size mismatch (now checked);
  - letters with raw newlines;
  - contradictory Spark verdicts;
  - "less than 1.5 s" is now strict;
  - the cache stamp now includes chunk size.
- Both test clips now report 0 near-misses from geometry alone. The pole's long still stretch is dropped before Spark sees it.
- New:
  - head blur in evidence clips and the street photo;
  - long videos in SAM parts with a cost guard (5 minutes then; 15 s since the 16-object finding);
  - Muse Wonder ear-witness (`listen.py`). On the user's college clip it heard brakes at 14.5–15.4 s on two separate calls, and a spectrogram shows tonal squeal energy at 1.75–3.75 s into that window. Corroborated, not ground truth.
- 25 self-checks pass.
- Added after the judge-side critique (JUDGE_REPORT.md):
  - a close-pass tier (PET 1.5–3 s);
  - exposure on every report: crossings watched, moving vehicles, minutes, 85th-percentile speed, conflicts per 100 crossings;
  - the page never implies "safe";
  - `test-videos/` is gitignored.
  - On the CCTV clip: 8 crossings, 5 moving vehicles, 85th-percentile speed 25 km/h, 0 serious, 0 close passes.
- 26 self-checks pass.

## Status update (Thu 29 Oct, early)

- **Measurement layer validated on SinD ground truth.** See the README section "Validation on ground-truth trajectories".
  - Speed error: mean 0.26 km/h.
  - PET agrees with an independent conflict-area PET within 0.5 s on 51 of 65.
  - Same tier on 56 of 65.
  - All 9 pairs only the textbook flagged are explained.
  - This is a partial answer to "no true positive yet". G3 still needs a true positive through SAM and phone calibration.
- PET search now uses a grid index (equal to brute force on 30 random cases, see the test), and vehicles can be full footprint polygons.
- 28 self-checks pass.
- **End-to-end ground-truth test (DUT drone clips 15, 01, 03).**
  - 6 of 10 true conflicts found.
  - 0 false alarms.
  - Speed ±0.8 km/h; PET mean error 0.7 s.
  - Misses: 2 at clip start (not yet tracked); 2 at 9.5 vs 10.5 km/h under the pre-set 10 km/h threshold (not retuned).
  - Spark review now uses a zoomed crop of each person's clearest frame. The full-frame snapshot rejected 4 real
    students; the crop keeps rejecting empty road, a pole and part of a car.
  - G3 is passed on drone footage with ground truth (top 3 events are real, none involves a parked vehicle).
    The phone-angle version still needs the user's footage.
- A third review (8 agents) confirmed 4 real defects plus 6 smaller ones. All fixed except two stated limits (long-video ID boundaries, box jitter):
  - the street photo could go out unblurred for long videos or a custom person concept (now no photo rather than faces);
  - calibration with prep_filter could silently misplace points (now `marked_on` is checked);
  - the stillness filter ran after track splitting, so a glitching pole escaped;
  - one near-miss was counted twice across track pieces;
  - the "as driven" row disagreed with the limit replay for close passes;
  - top-down boxes cut at the top edge;
  - the fix text is now shown even if the image fails;
  - a missing API key now gives a measurements-only page.
  - 31 self-checks pass; DUT result unchanged (6 of 10, 0 false alarms).
- **DUT, 8 clips, judged by identity, with threshold cases split out:**
  - Whole frame: 14 of 36 found, 0 false alarms.
  - 2 x 2 person tiles: 19 of 36 found; 12 extra, of which 8 are threshold cases (e.g. car 8.6 vs 10.1 km/h).
  - Excluding threshold cases, tiles give 61% recall and 83% precision.
  - Crowds (50+ in view) remain the weak spot.
- Parts now overlap by 2 s and IDs are joined across cuts; crowded frames can be tiled (`person_grid`). Tests cover both.
- **Crowd mode** (`person_mode: crowd`, SAM image detection plus our tracker):
  - Crowded DUT clips: 21 of 25 found (100% of non-threshold conflicts), 2 real false alarms.
  - Held-out clips: 8 of 11 found, 0 real false alarms.
  - The tracker rule (constant velocity, match within one body size) was set from physics before the held-out run.
- Crowd-mode audit (cached data, no new API calls):
  - The 2 real false alarms: a walker the dataset stops tracking after 1.8 s, and an unlabelled person standing at the road edge.
  - Not filtering standing people: that would also remove a true conflict in clip 12.
  - 297 of 301 dataset pedestrians followed; median 1 of our tracks per pedestrian, at most 5.
- Engineering numbers (PV², gaps where people crossed), checked against DUT ground truth with the same definitions:
  vehicles right on 8 of 8 clips, 6 s gap count right on 7 of 8, pedestrian count 1.3x too high (stated on the page).
  The first version measured gaps in the calibration rectangle; on the kids clip that is one lane, so no car ever
  entered it. Gaps are now timed where pedestrians actually crossed.
- SAM 3.1's 16-object limit is per video request, not per frame (54 cached replies: none above 16, no new ID after
  16). Parts cut from 5 min to 15 s; on the kids clip 2 of 8 requests still fill, on the dense Indian clip all 12.
  Full requests are counted and the page says counts are a minimum.
- Fourth review (3 reviewers, each finding checked by a skeptic), 10 confirmed and fixed: crowd-mode clips left heads
  unblurred on every other frame (boxes now filled between samples); PV² and rates used minutes rounded to 0.1;
  gap rate per minute read backwards for empty roads (now share of time); crowd-mode street photo missing; image
  cost called a Meta price; child and non-car events showed the adult car-front risk without a caveat; pedestrian
  count includes pavement walkers when no carriageway is marked (stated).
- DUT re-run after both changes (`validate_dut.py ... --mode crowd --out out/dut-15s`): 29 of 36 found, 3 real false alarms (was 2).
- Vehicle crowd mode: DUT 35 of 36 (4 real false alarms); dense Indian clip coverage 6 -> 20 vehicles a frame. Found and
  fixed on the way: one-frame pedestrian fragments (543 -> 83 events) and riders accepted as pedestrians by Spark
  (83 -> 18 after review). Speed on that clip is untestable (guessed calibration); G2 on real footage still pending.
- Fifth review (2 reviewers, findings checked): crowd-mode vehicles over ~36 km/h were lost at 5 samples a second (now
  10); synonym concepts shared one cache (now refused); letter check missed non-English facts and comma numbers, and
  flagged "SAM 3.1" from the prompt (fixed). DUT with vehicles at 10 a second: 12 of 36, every miss at the 10 km/h
  bar, speed bias +0.2 km/h; all non-threshold conflicts found, 1 real false alarm.

## Letter check made stricter (Thu 29 Oct)

- The fifth review's fix for "SAM 3.1" counted the prompt's numbers as measured, which also let any 3.1 through. The
  check now reads the measurements only, and the letter prompt no longer names the SAM version.
- Also sent back now: numbers in words (two to ninety, hundred, thousand, dozen; "one" is too common to flag, and a
  two-wheeler is a vehicle), speeds in mph, and a sentence with one near-miss's speed and another near-miss's time gap.
- On the two cached letters (`out/dut/15`, `out/dut-15s/15`; offline, no API calls): the word check catches "The four
  worst were all serious" in dut-15s; both letters say "SAM 3.1", and 3.1 is not in their measurements, so both
  would now go back; neither mixes two near-misses. Against today's events.json, 3 and 6 of their numbers become
  clip links.

## One number replaces "conflicts per 100 crossings" (Thu 29 Oct)

- The tile divided conflicts (person-vehicle pairs) by crossings (people), so one person passed by several vehicles
  counted several times, and it could pass 100. `road.exposure()` now also returns who crossed, and the page's first
  line (and the letter's first fact) counts each person once: "k of n crossings (1 in N)" within 3 s and within
  1.5 s, with exact 95% ranges (Clopper-Pearson for the share, Garwood's Poisson range for the count).
- Offline recomputes (cached tracks or ground truth, no API calls; SAM requests were stubbed to fail on a cache miss):
  - SinD ground truth, 20 min: 37 of 63 crossings (1 in 1.7) within 3 s, 25 of 63 within 1.5 s. Old tile: 103.2.
  - Dense Indian clip, crowd cache (the recompute matches the stored 83 events pair for pair and its 15 crossings;
    Spark's stored verdicts leave 18 events): Spark rejected 10 of the 15 tracked crossers as not people (8 riders,
    2 "not a person"), so the clip has only 5 real crossers and the ranges are wide: 5 of 5 (1 in 1) within 3 s,
    2 of 5 (1 in 2.5) within 1.5 s; 95% ranges 47.8-100.0% and 5.3-85.3%. Old tile: 120.0 (18 events over all 15
    crossers).
  - Review fix: the first version kept Spark's rejected crossers in n but not in k, which printed 5 of 15 here, 3x
    too low. `pack.real_crossers` now drops them from n by person (one with any piece still confirmed stays).
  - Kids 15-second parts: 0 of 7, 95% range 0.0-41.0%, up to 3.7 people in a recording this long.
- Pages built from an events.json written before this change show no headline, rather than a count that could hold
  someone twice.

## Receipt, hashes and safety pyramid (Thu 29 Oct)

- **Scale table numbers** (README "Scale"), recomputed offline from the cached SAM replies, no API calls, at Meta's
  list prices ($0.20 per 1,000 video frames billed, at least 50 a request; $2.50 per 1,000 images):
  - kids school CCTV, 2 concepts: 8 requests, 1,088 frames billed, $0.22 for 48.4 s ($4.05 per 15 minutes);
  - dense Indian clip, 4 concepts: 12 requests, 1,720 frames billed, $0.34 for 39.0 s ($7.94 per 15 minutes);
  - frame by frame for 15 minutes: 13,500 images, $33.75, with the one concept "vehicle"; 31,500, $78.75, with three.
- The share folder's `SHA256SUMS` passes the system `shasum -a 256 -c` in the self-check; `--verify` reports a changed
  page as CHANGED and a deleted file as MISSING.
- No cached events.json has the crosser list yet (all predate it), so the pyramid has not been drawn from a real
  pack. The first gate pack will be the first. With SinD's 63 crossings, 0 collisions would still allow up to 5.7%.

## G5 Blind check, pre-registered (Thu 29 Oct, before any clip is made or labelled)

These rules do not change after anyone labels.

- **Clips** (`blind_set.py OUT_DIR SITE.json --review-decoys`, on the gate pack after G4):
  - the near-misses Spark did not reject, as the page counts them, most dangerous first, at most 12;
  - as many decoys: a pedestrian and a moving vehicle on the same spot 5 to 8 s apart, closest first, each
    pedestrian one Muse Spark says is a person, so a pole is never a decoy;
  - every clip 12 s long from 2 s before the first of the two reached the spot, the pedestrian boxed cyan and the
    vehicle red, every tracked person's head blurred, no sound, shuffled with a fixed seed as clip01, clip02...;
  - the key (`blind-key.json`) stays with us; the rater gets only the `blind/` folder.
- **Rater:** one transport or civil engineering lecturer decides the gate. Classmates, if any, are reported
  separately as non-experts.
- **Scoring** (`score_humans.py`): the rater's serious or close is "danger", none is "none"; can't tell and unanswered
  clips are left out and counted. Reported for each rater: agreement k of n with its Wilson 95% interval, Cohen's
  kappa, the pipeline's near-misses called danger and the decoys called none (each with Wilson 95%), and positive
  and negative agreement.
- **Pass:** the lecturer's kappa is 0.6 or more (substantial, Landis & Koch 1977). Fail below it, reported the same way.
- **Not decidable:** fewer than 6 near-misses or 6 decoys in the set, or more than a quarter of the clips can't tell
  or unanswered. The answers are then reported as descriptive only.
- `score_humans.py` prints this verdict itself, so the rule is applied as written.

Tooling dry run (offline, not the gate): on the cached dense Indian clip, with the vehicle sampling rate its cache
was made at and no `--review-decoys`, `blind_set.py` rebuilt the tracks from cache with no SAM request and wrote
20 clips of 121 frames: 12 near-misses and 8 decoys (decoys limited to pedestrians Spark had already looked at).

## Judge bench, Spark side (Thu 29 Oct)

`judge_bench.py` plants one lie at a time in two real letters and scores each letter check on them.

- Bases: Glimmer's v1 letter (`<removed-run-record>`, facts rebuilt from `sample/`) and the Muse Spark letter
  cached in `out/dut-15s/15`, written before the stricter check: the bench writes its "SAM 3.1" as "SAM" and "four"
  as "4", after which every number passes the code check against facts rebuilt from that folder's events.json.
- 12 kinds of lie on each base, 24 copies: the four kinds JUDGE_PROMPT names (a standard said to be met, a death
  risk for a child, a named person blamed, a number in words) and two plain invented facts (injuries, a cause); and
  six kinds it does not name (every school day, deaths prevented, a near-miss called a collision, children claimed,
  km/h written as mph, two near-misses' speeds swapped). The 18 inserted sentences have no digit.
- 8 clean controls: each base as written, and with one fact-free or true sentence added (a site visit asked for, the
  serious count restated, "near-misses, not recorded accidents").
- **Code check, offline, run today:** 4 of 24 lies caught (Wilson 95% 7-36%): the 2 numbers in words and the 2 mph
  speeds. It missed every inserted sentence and both swaps, as built: those need a judge. 0 of 8 controls flagged
  (Wilson 95% 0-32%).
- Not run yet (paid): Muse Spark twice per letter, and Muse Glimmer once on Kaggle. Both are Muse models, so neither
  is an independent judge of Muse letters. A reply that cannot be read is counted on its own, not as a catch.
