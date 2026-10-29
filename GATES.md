# Crossing Watch: pre-registered gates

Written Wed 28 Oct 2026, before running the full pipeline on real footage. These conditions do not change after results come in.

| Gate | Pass condition | Test footage | Due (IST) |
|---|---|---|---|
| G1 Tracks | SAM 3.1 keeps one ID on each crossing pedestrian for at least 80% of the time they are visible | news CCTV `sites/kids-cctv.json` | passed 28 Oct (2 of 2 crossers, 150/150 frames) |
| G2 Metres | A road distance NOT used for calibration (a second lane width, or crossing-line length) comes out within ±15% of its assumed value | same | Wed 28 Oct 22:00 |
| G3 Conflicts | Checked by eye, at least 2 of the top 3 events are real close passes, and no event involves a parked or queued vehicle | same | Thu 29 Oct 22:00 |
| G4 Own footage | Footage filmed from height at the user's college gate runs end to end, with calibration from measured points | user's video | Sun 1 Nov 22:00 |
| G5 Blind check | A transport or civil engineering lecturer, not told which clips the pipeline flagged, agrees with it on danger vs none with Cohen's kappa of 0.6 or more (rules below, written before any gate-pack clip is made) | the gate pack | Tue 3 Nov 22:00 |
| G6 Speed | Against vehicles hand-timed between two lines taped 15 m apart, at least 80% of matched vehicles read within ±15% or ±2 km/h (whichever is larger), and the median error is within ±10%; at least 20 matched vehicles, or G6 is "not tested". Added Thu 29 Oct, before the taped lines are filmed; details below | user's video, with the lines taped | Sun 1 Nov 22:00 |

**Scope cut if G3 fails:** report the closest approach in metres plus vehicle speed (no PET). The evidence pack and letter still ship.

**Known limits (stated, not hidden):** a vehicle's lower box edge stands in for its footprint; up to 16 objects per SAM video request (found later: in all, not per frame); one concept per SAM request; calibration lengths on the news clip are assumed.

## G6 pre-registration (written Thu 29 Oct 2026, before the taped lines are filmed)

- **Lines.** Four tape marks, two on each kerb, make two lines across the road 15 m apart, centred on the crossing.
  They are separate from the calibration rectangle (never its corners, or the check is not independent). Everything
  is done from the footpath, and there are no staged rides. The marks are clicked in the calibration frame and saved
  in the site file as `"trap"` (see the first lines of `validate_gate.py`).
- **Truth.** For each vehicle, the moments its front wheel touches line A and line B, read frame by frame on the exact
  video file given to analyze.py (the 30 fps original, never the 10 fps clip.mp4). Trap speed is the taped distance
  divided by the time between them.
- **Which vehicles.** From the start of that video, every vehicle of any kind that crosses both lines, in order, until
  30 are logged (or all of them, if fewer cross). A vehicle is skipped only when its front wheel is hidden at either
  line or it stops between the lines, and each skip is noted with why. The log is made without looking at the
  pipeline's speeds.
- **Ours.** `python3 validate_gate.py SITE.json OUT_DIR TRAP.csv` rebuilds the run's tracks from its cached SAM replies
  at $0. It matches each logged vehicle to the one track within 1.5 m of line A and of line B at the logged moments,
  and takes that track's median measured speed between them. A vehicle with no such track, with two or more, or with
  fewer than 3 measured speeds is listed with the reason and left out of the error figures.
- **Pass:** at least 20 matched vehicles; at least 80% of them within ±15% or ±2 km/h of their trap speed, whichever is
  larger; and the median signed error within ±10%. **Fail:** fewer than 80% within the band, or a median error beyond
  ±10%. **Not tested:** fewer than 20 matched vehicles. A failed or untested G6 is never reported as passed.
- **If G6 fails or is not tested,** the README, the video and the X post give the trap's measured error (or say that
  no own-camera speed check was possible) as the speed accuracy on our camera, not the DUT or SinD numbers.
- **Why these bands.** In a synthetic rooftop-camera simulation (re-run offline on Thu 29 Oct), hand timing a 15 m
  trap on a 30 fps original is good to 0.67-1.14 km/h at 25 km/h (95th percentile, half to one frame of picking
  error); calibration from an 8 m rectangle adds 2.0-5.4% (95th percentile, 1-2 px clicks, two camera positions); and
  up to 4 px of box jitter adds under 0.5 km/h (95th percentile) to today's speed estimator. The band leaves room for
  all three; the ±10% bound on the median catches a scale error that the band alone would let through. The simulation
  leaves out SAM's box drift on a real camera at an angle, so G6 can fail.
- **Side check.** The script also prints how far apart the calibration puts the two lines. That is a road distance not
  used for calibration, so it can also serve G2.
- These conditions and the constants in `validate_gate.py` (`BAND_PCT`, `BAND_KMH`, `PASS_SHARE`, `MAX_LEAN_PCT`,
  `MIN_VEHICLES`, `MATCH_M`, `MIN_SPEEDS`) do not change after the trap footage arrives.

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
  - *Re-scored after the speed fix (last section): 0.24 km/h, 53 of 66 within 0.5 s, same tier on 57 of 66, the
    same 9 pairs.*
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
  *Corrected 29 Oct: stale. Clip 15's events.json was rewritten after this validation.json; scored as stored, the run gives 26 of 36.*
- Vehicle crowd mode: DUT 35 of 36 (4 real false alarms); dense Indian clip coverage 6 -> 20 vehicles a frame. Found and
  fixed on the way: one-frame pedestrian fragments (543 -> 83 events) and riders accepted as pedestrians by Spark
  (83 -> 18 after review). Speed on that clip is untestable (guessed calibration); G2 on real footage still pending.
- Fifth review (2 reviewers, findings checked): crowd-mode vehicles over ~36 km/h were lost at 5 samples a second (now
  10); synonym concepts shared one cache (now refused); letter check missed non-English facts and comma numbers, and
  flagged "SAM 3.1" from the prompt (fixed). DUT with vehicles at 10 a second: 12 of 36, speed bias +0.2 km/h, 1 real
  false alarm. *Corrected 29 Oct: the misses were not at the 10 km/h bar. 20 of the 24 were Spark's review (17 of them
  "rider" or "cyclist" calls on walking students) and 4 were at a threshold.*

## Status update (Thu 29 Oct): DUT re-scored after the speed fix and the rider gate

- **Truth pass.** Every DUT number in the README was recomputed once, at $0, with the code as it now stands, from
  the cached SAM replies and Spark's stored verdicts: `python3 validate_offline.py DUT_REPO out/dut-15s
  out/dut-vcrowd` (it writes nothing; a cache miss stops it). The two lines above marked *Corrected 29 Oct* were
  wrong, and so was the README's "neither changed any DUT result": Spark's rider calls had cost 17 conflicts.
- **Why the numbers moved:**
  1. **Speed fix (a9ef24b).** DUT's source runs at 23.976 fps. Resampled to 10 fps it steps 2,2,3,2,3 source
     frames, and the old median of steps read 0.83 x the true speed: our tracks and the dataset's own tracks (resampled
     the same way for scoring) were both read slow. With a least-squares slope, cars at about 10 km/h now count as
     moving, so the truth set grows from 36 to 52 conflicts (24 to 34 serious). This is the "moving" bar being read
     right, not better detection. The same commit's phantom-speed guard leaves the Indian clip with no event above
     57 km/h (88 before).
  2. **Rider gate (b54d1ab).** Spark called walking students "rider" or "cyclist". DUT tracks no bikes, so no bike box
     is ever under them and every such call is now overruled.
  3. **New events.** Today's code finds conflicts in track pieces Spark never saw: 8 events in crowd mode, 17 in
     vehicle crowd mode. They stay in, as unreviewed events do on the page. The low end of each range below assumes
     Spark would reject all of them; a Spark re-run settles it (SAM is cached).
- **Old and new side by side.** Old = as published before today. Crowd mode = people in crowd mode, cars by SAM video
  in 15 s parts.

| Number | Old | New (29 Oct) |
|---|---|---|
| True conflicts in the dataset's own tracks | 36 (24 serious) | 52 (34 serious) |
| Crowd mode, found after Spark's review | 29 of 36 | 44 of 52 (37 to 44) |
| ... crowded / held-out clips | 21 of 25 / 8 of 11 | 29 of 37 / 15 of 15 |
| ... with 15 s parts | "29 of 36" (stale: 26 as stored) | the same run: 44 of 52 |
| Crowd mode, found by the geometry alone | not published | 49 of 52, every miss at a threshold |
| Crowd mode, real false alarms | 2 (3 with 15 s parts) | 3 |
| Vehicle crowd mode, found after review | 12 of 36 | 45 of 52 (30 to 45; 28 without the rider gate) |
| Vehicle crowd mode, misses | 24, "every miss at the 10 km/h bar" (in fact 20 by Spark's review, 4 at a threshold) | 7: 4 at a threshold, 3 that Spark called "unclear" |
| Vehicle crowd mode, real false alarms | 1 | 4 |
| Whole frame / 2 x 2 tiles | 14 / 19 of 36, after review | 22 / 34 of 52, by the geometry (their verdicts were not kept) |
| Speed against the dataset's native-rate positions, vehicle crowd mode (mean / 95th percentile error) | 0.52 / 1.89 km/h | 0.16 / 0.55 km/h |
| Frames with the car at 7-13 km/h put on the wrong side of the 10 km/h bar | 28% | 7.5% |
| Matched events, speed | usually within 1 km/h, 2 at worst | 41 of 44 within 1 km/h, 2.0 at worst |
| Matched events, PET | within about 1 s | 38 of 44 within 1 s, 2.5 s at worst |
| Gaps of 6 s or more where people crossed | right on 7 of 8 clips | right on 8 of 8 |
| Dataset pedestrians followed by our tracks | 297 of 301, at most 5 tracks each | 296 of 301, at most 4 |
| Indian crowd clip (no ground truth), after review | 18 events (6 serious), up to 88 km/h | 10 events (5 serious, 2 not yet reviewed), up to 57 km/h |

*Corrected later on 29 Oct: the Indian row's new column is from the truth-pass commit 93d94ac. On the merged code it
is 6 events (4 serious, 1 not yet reviewed), up to 36.4 km/h; see the last section.*

- Unchanged: moving vehicles counted right on 8 of 8 clips, longest gap within 0.5 s on 6 of 8, pedestrian crossings
  374 against the dataset's 280.
- How the old column was checked: the stored events re-scored with the code from before the speed fix give the
  same 12 of 36 (24 misses: 20 by Spark's review, 4 at a threshold) and 26 of 36 for the 15 s run; the same speed
  check on that code gives 0.52 / 1.89 km/h and 28%.
- 58 self-checks pass.

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
  - SinD ground truth, 20 min: 37 of 63 crossings (1 in 1.7) within 3 s, 25 of 63 within 1.5 s. Old tile: 103.2
    (104.8 on the merged code: 66 conflicts / 63 crossings; the 37 and 25 do not change).
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
    The $33.75 is not adopted: `vehicle_test.py` (about $0.15) has not been run to show "vehicle" finds 95% of what
    the three concepts find.
- The share folder's `SHA256SUMS` passes the system `shasum -a 256 -c` in the self-check; `--verify` reports a changed
  page as CHANGED and a deleted file as MISSING.
- No cached events.json has the crosser list yet (all predate it), so the pyramid has not been drawn from a real
  pack. The first gate pack will be the first. With SinD's 63 crossings, 0 collisions would still allow up to 5.7%.

## G5 Blind check, pre-registered (Thu 29 Oct, before any gate-pack clip is made or labelled)

These rules do not change after anyone labels.

- **Clips** (`blind_set.py OUT_DIR SITE.json --review-decoys`, on the gate pack after G4):
  - the near-misses Spark did not reject, as the page counts them, most dangerous first, at most 12;
  - as many decoys: a pedestrian and a moving vehicle on the same spot 5 to 8 s apart, closest first, each
    pedestrian one Muse Spark says is a person, so a pole is never a decoy, and one who passes no other vehicle
    under 3 s apart inside the clip, so the rater never sees real danger the key calls none;
  - every clip 12 s long (121 frames) from 2 s before the first of the two reached the spot (from the video's start
    when that is sooner; earlier when 12 s would run past the video's end), the pedestrian boxed cyan and the
    vehicle red, every tracked person's head blurred, no sound, shuffled with a fixed seed as clip01, clip02...;
    a clip of any other length stops the run before the key is written;
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
- Not part of this gate, and not built: Muse Spark as a fourth rater on the same clips, and a recall list from the
  filmer's spoken "close" calls through Muse Voice Transcribe.
- Added the same day, before any clip was made: `blind_set.py` refuses a pack whose people were tracked by a full
  SAM video request (16 objects), since people who came later have no track to blur. The clips blur the faces SAM
  found, so each clip is watched before it is handed out.

Tooling dry runs (offline, not the gate): on a copy of the cached dense Indian clip (390 frames), with the vehicle
sampling rate its cache was made at and no `--review-decoys` (so decoys are limited to pedestrians Spark had
already looked at), `blind_set.py` rebuilt the tracks from cache with no SAM request.

- The first version wrote 12 near-misses and 8 decoys, but 6 near-miss clips, with events at 30.0-30.8 s, were cut
  short by the video's end: 102, 102, 102, 106, 110 and 110 frames (frame counts from ffprobe). And every decoy's
  pedestrian passed another vehicle under 3 s apart inside its clip. Both are fixed in the rules above, before
  anyone labelled.
- The re-run wrote 12 near-misses, all 121 frames, and 0 decoys: of 30 pairs 5 to 8 s apart, 29 had the pedestrian
  under 3 s from another vehicle inside the clip, and the one left was a pedestrian Spark had not looked at. A set
  from a crossing this busy would be not decidable; the gate pack needs `--review-decoys` and calm crossings too.
- Near-misses in the video's first 2 s start with less lead (four here, at 0.2-1.7 s), and the six at 30.0-30.8 s
  with more; the rules above allow both.

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
  Totals and their Wilson bounds count letters (one flagged if any of its readable runs flagged it), never runs:
  two runs on one letter are not independent.

## Review fixes, re-scored on the merged code (Thu 29 Oct, evening)

A review of the merged lanes found README numbers from older code. Each was recomputed once, at $0, on the merged
code (no API calls: SAM and Spark were stubbed to fail on a cache miss).

- **SinD** (`python3 validate_sind.py data/sind`, three runs, the same each time). The SinD lines were written before
  the speed fix (a9ef24b) and were not re-scored with DUT.

| Number | Old (as published) | New |
|---|---|---|
| Moving vehicles | 556 | 554 |
| Speed error against SinD's own velocity, mean / 95th percentile | 0.26 / 0.96 km/h | 0.24 / 0.91 km/h |
| Conflicts under 3 s (serious) | 65 (42) | 66 (42) |
| Textbook PET within 0.5 s of ours | 51 of 65 | 53 of 66 |
| Same tier | 56 of 65 | 57 of 66 |
| Pairs only the textbook calls serious | 9 | the same 9 |
| Search time for 20 minutes | under a second | 1.0 s on this laptop |
| Old "per 100 crossings" tile | 103.2 | 104.8 |
| One number | 37 of 63 within 3 s, 25 of 63 within 1.5 s | unchanged |

  The new conflict is P15 with motorcycle#108, a close pass (PET 2.7 s) at 10.1 km/h: the old median of steps read
  that motorcycle at 9.6 km/h there, under the 10 km/h "moving" bar. No conflict was lost and no tier changed.
- **Dense Indian clip** (crowd cache; tracks rebuilt as `validate_dut.our_tracks` does from exactly the cached frames,
  vehicles at the 5 a second the cache was made at; Spark's stored verdicts through the rider gate; a scratch script,
  not in the repo). The README had kept the figure from the truth-pass commit 93d94ac; later lane commits changed the
  tracks on this angled view.

| Number | At 93d94ac | Merged code |
|---|---|---|
| Conflicts before Spark's review (serious) | 25 (11) | 22 (14) |
| After review | 10 events (5 serious, 2 not yet reviewed) | 6 events (4 serious, 1 not yet reviewed) |
| Fastest vehicle after review / before | 57.0 / 57.0 km/h | 36.4 / 45.9 km/h |
| One number (crossers left after Spark's rejections) | 5 of 5 within 3 s, 2 of 5 within 1.5 s (as published above) | 3 of 8 within 3 s, 3 of 8 within 1.5 s (95% range 8.5-75.5%) |

- **Rank 35, tracker tweak after OC-SORT: tried, not shipped.** Velocity from 3 samples back and a second greedy
  round against each unmatched track's last seen box, scored with `validate_offline.py` on `out/dut-15s` and
  `out/dut-vcrowd` (the change patched in from a scratch script):

| | Today's tracker | Tweak |
|---|---|---|
| Found after review (crowd / vehicle crowd mode) | 44 / 45 of 52 | 44 / 45 of 52 |
| Found by the geometry | 49 / 48 | 49 / 48 |
| False alarms (of them at a threshold) | 5 (2) / 6 (2) | 5 (2) / 6 (2) |
| Pedestrian crossings, against 280 true | 374 | 357 |
| Tracks for the 296 pedestrians followed (split ones) | 325 (23) | 316 (18) |
| Events on pieces Spark never saw | 8 / 17 | 19 / 26 |

  Recall and false alarms hold, so by the plan's rule it could ship. It is not shipped before the gate run: it finds
  nothing more, and it moves 20 events onto track pieces with no stored Spark verdict, so the README's after-review
  DUT numbers could no longer be checked at $0 without a paid Spark re-review.
- **Single concept "vehicle" (rank 4b):** `vehicle_test.py` now holds the test (60 cached crowd frames of the Indian
  clip sent with "vehicle", about $0.15, capped at $0.20; boxes matched at IoU 0.5 against car, motorcycle and auto
  rickshaw; adopt at 95% recall). It has not been run, so "vehicle" is not adopted and $34 for 15 minutes is a
  condition, not a plan.
- **Waiting for the gate footage, no code yet:** the horn fused with a speed profile (rank 24), the 20 km/h ghost car
  (25), parked vehicles (30) and the SAM video re-check (36). Each is built only if its go/no-go check on the first
  gate events.json passes; none has been run.
- **Privacy:** a clip with no near-misses but a full people reply now gets frame 0 searched (one image), so its street
  photo is not refused; `blind_set.py` refuses a full people video request (G5 above); in `docs/` git ignores every
  video except `eventN.mp4` and `eventN-hero.mp4`, and the person crops and blind clips; the filming notice now says
  the video and sound go to Meta's AI services and the raw video is kept until the study ends, and `FILMING.md` gives
  the command that deletes the unblurred files.
- **School-year line:** a tier seen 0 times read "about 0 crossings a school year". It now gives Poisson's upper
  bound scaled the same way: "up to 1,100" for 20 minutes of 40 crossers, 30-minute dismissals, 200 days.
- **Kaggle judge pass:** `out/` is not in the repo zip, so the notebook rebuilt the bench from Glimmer's letter alone
  (12 lies and 4 controls, not 24 and 8). It now copies an attached `judge-bench.json` and its record says which.
