# Crossing Watch: pre-registered gates

Written Wed 28 Oct 2026, before running the full pipeline on real footage. These conditions do not change after results come in.

| Gate | Pass condition | Test footage | Due (IST) |
|---|---|---|---|
| G1 Tracks | SAM 3.1 keeps one ID on each crossing pedestrian for at least 80% of the time they are visible | news CCTV `sites/kids-cctv.json` | passed 28 Oct (2 of 2 crossers, 150/150 frames) |
| G2 Metres | A road distance NOT used for calibration (a second lane width, or crossing-line length) comes out within ±15% of its assumed value | same | Wed 28 Oct 22:00 |
| G3 Conflicts | Checked by eye, at least 2 of the top 3 events are real close passes, and no event involves a parked or queued vehicle | same | Thu 29 Oct 22:00 |
| G4 Own footage | Footage filmed from height at our college gate runs end to end, with calibration from measured points | our video | Sun 1 Nov 22:00 |
| G5 Blind check | A transport or civil engineering lecturer, not told which clips the pipeline flagged, agrees with it on danger vs none with Cohen's kappa of 0.6 or more (rules below, written before any gate-pack clip is made) | the gate pack | Tue 3 Nov 22:00 |
| G6 Speed | Against vehicles hand-timed between two lines taped 15 m apart, at least 80% of matched vehicles read within ±15% or ±2 km/h (whichever is larger), and the median error is within ±10%; at least 20 matched vehicles, or G6 is "not tested". Added Thu 29 Oct, before the taped lines are filmed; details below | our video, with the lines taped | Sun 1 Nov 22:00 |
| G7 After the fix | A film of the same dismissal after the fix shows a drop only if a one-sided Fisher exact test at 5% finds both fewer crossings with a moving vehicle through the same spot within 3 s and fewer distinct such vehicles. Added Thu 29 Oct, before the rehearsal or the main recording is filmed; details below | our video, then a film after the fix | the mark Mon 2 Nov night; the verdict only once a fix is built and filmed |
| G8 Second operator | Someone who has never seen the code clicks the calibration on our frame: both site files put the two speed lines within ±5% of 15 m and of each other, and give the same G6 verdict with median errors within 5 points. Added Thu 29 Oct, before the rehearsal or the main recording is filmed; details below | our video, with the lines taped | Tue 3 Nov 22:00 |

**Scope cut if G3 fails:** report the closest approach in metres plus vehicle speed (no PET). The evidence pack and letter still ship.

**Known limits (stated, not hidden):** a vehicle's lower box edge stands in for its footprint; up to 16 objects per SAM video request (found later: in all, not per frame); one concept per SAM request; calibration lengths on the news clip are assumed.

## Verdict now

The table above does not change; this one is updated as gates run. Last updated Mon 2 Nov 2026, 18:57 IST, after the gate run.

| Gate | Verdict now | Evidence |
|---|---|---|
| G1 Tracks | passed 28 Oct (news CCTV) | the table above; 'Status (Wed 28 Oct, evening)' below |
| G2 Metres | **passed Mon 2 Nov (our gate):** line A to line B, not used for calibration, read 15.0 m; the tape says 15 m (0% off; band 12.75-17.25) | the case agent's tape check, [`provenance/gate-agent-2026-11-02/agent_log.jsonl`](provenance/gate-agent-2026-11-02/agent_log.jsonl); 'The gate recording' notes below |
| G3 Conflicts | not tested on its own footage; passed on DUT drone ground truth (29 Oct); phone angle pending | 'Status update, third pass' below |
| G4 Own footage | **passed Mon 2 Nov:** filmed from the highway 8.3 m above our gate, calibrated on a taped 8 m x 7 m rectangle, run end to end (hand-held, stabilized first) | `sites/gate.json`; 'The gate recording' notes below |
| G5 Blind check | not run | no rater has labelled; rules in 'G5 Blind check, pre-registered' below |
| G6 Speed | not run | lines A and B, 15 m apart, filmed 2 Nov; the hand-timed log is not made yet; rules in 'G6 pre-registration' below |
| G7 After the fix | no verdict before submission; **mark written Mon 2 Nov:** baseline 3 of 51 crossings with a moving vehicle through the same spot within 3 s (3 distinct vehicles), so one after-film this long cannot show a drop; film 2 dismissals after the fix | the evidence page's step 9; rules in 'G7 After-fix pass mark' below |
| G8 Second operator | not run | after G6's log and Monday's run; rules in 'G8 Second operator' below |

**Due dates passed without a run (note added Sun 1 Nov 2026, 11:05 IST; the pre-registered table is unchanged).**
G2's due date (Wed 28 Oct 22:00) passed without a run, and G4's and G6's (Sun 1 Nov 22:00) will too. All three move to
Mon 2 Nov, because the gate recording moved to Mon 2 Nov: the college asked for Monday. Their pass conditions do not
change. G5 and G8 keep Tue 3 Nov 22:00; G7's mark is still written on Mon 2 Nov night.

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

## Status, first pass (written before the first commit, 28 Oct 19:19 IST)

- **G1** passed (see table).
- **G2 not yet tested.** Both test clips were calibrated from assumed lengths, so no independent measured distance exists. This waits for our footage with measured points.
- **G3 partial.**
  - On the schoolchildren CCTV clip, the pipeline reports 1 event. It is a pole tracked as a person, and Muse Spark rejects it, so the evidence pack shows 0 near-misses. Checked by eye: no real close pass happened there (the children were 1.4 m or more from slow, turning cars). So: no false alarm in the final output, but no true positive tested yet either.
  - The Indian intersection clip's event count is *withdrawn 29 Oct: the clip is a time-lapse; see 'The Indian clip is a time-lapse' below*.
  - A true positive needs footage with a real near-miss.
- An AI-assisted code review found 14 confirmed defects, all fixed:
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

## Status update, second pass (written before the first commit, 28 Oct 19:19 IST)

- A second AI-assisted code review found 13 confirmed defects, all fixed:
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
  - Muse Wonder ear-witness (`listen.py`). On our college clip it heard brakes at 14.5–15.4 s on two separate calls, and a spectrogram shows tonal squeal energy at 1.75–3.75 s into that window. Corroborated, not ground truth.
- 25 self-checks pass.
- Added after an internal judge-side critique (not published):
  - a close-pass tier (PET 1.5–3 s);
  - exposure on every report: crossings watched, moving vehicles, minutes, 85th-percentile speed, conflicts per 100 crossings;
  - the page never implies "safe";
  - `test-videos/` is gitignored.
  - On the CCTV clip: 8 crossings, 5 moving vehicles, 85th-percentile speed 25 km/h, 0 serious, 0 close passes.
- 26 self-checks pass.

## Status update, third pass (written before the first commit, 28 Oct 19:19 IST)

- **Measurement layer validated on SinD ground truth.** See the README section "Validation on ground-truth trajectories".
  - Speed error: mean 0.26 km/h.
  - PET agrees with an independent conflict-area PET within 0.5 s on 51 of 65.
  - Same tier on 56 of 65.
  - All 9 pairs only the textbook flagged are explained.
  - *Re-scored after the speed fix (see 'Review fixes, re-scored on the merged code' below): 0.24 km/h, 53 of 66 within 0.5 s, same tier on 57 of 66, the
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
    The phone-angle version still needs our footage.
- A third AI-assisted code review confirmed 4 real defects plus 6 smaller ones. All fixed except two stated limits (long-video ID boundaries, box jitter):
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
- Fourth AI-assisted code review (each finding checked again), 10 confirmed and fixed: crowd-mode clips left heads
  unblurred on every other frame (boxes now filled between samples); PV² and rates used minutes rounded to 0.1;
  gap rate per minute read backwards for empty roads (now share of time); crowd-mode street photo missing; image
  cost called a Meta price; child and non-car events showed the adult car-front risk without a caveat; pedestrian
  count includes pavement walkers when no carriageway is marked (stated).
- DUT re-run after both changes (`validate_dut.py ... --mode crowd --out out/dut-15s`): 29 of 36 found, 3 real false alarms (was 2).
  *Corrected 29 Oct: stale. Clip 15's events.json was rewritten after this validation.json; scored as stored, the run gives 26 of 36.*
- Vehicle crowd mode: DUT 35 of 36 (4 real false alarms); dense Indian clip coverage 6 -> 20 vehicles a frame. Found and
  fixed on the way: one-frame pedestrian fragments and riders accepted as pedestrians by Spark (that clip's event
  counts are *withdrawn 29 Oct: the clip is a time-lapse; see 'The Indian clip is a time-lapse' below*). G2 on real footage still pending.
- Fifth AI-assisted code review (findings checked): crowd-mode vehicles over ~36 km/h were lost at 5 samples a second (now
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
     right, not better detection. The same commit added the phantom-speed guard (its Indian-clip speeds are
     *withdrawn 29 Oct: the clip is a time-lapse; see 'The Indian clip is a time-lapse' below*).
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
| Indian crowd clip (no ground truth), after review | withdrawn | withdrawn |

*Corrected later on 29 Oct: the Indian row is withdrawn. The clip is a time-lapse, so its events and speeds were never
measurements; see 'The Indian clip is a time-lapse' below.*

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
  - Dense Indian clip, crowd cache: its one number is *withdrawn 29 Oct: the clip is a time-lapse; see 'The Indian clip is a time-lapse' below*. It did show that Spark rejected 10 of the 15 tracked crossers as not people (8 riders, 2 "not a
    person").
  - Review fix: the first version kept Spark's rejected crossers in n but not in k, so the share read too low.
    `pack.real_crossers` now drops them from n by person (one with any piece still confirmed stays).
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
already looked at), `blind_set.py` rebuilt the tracks from cache with no SAM request. *Added 29 Oct: that clip is a
time-lapse (see 'The Indian clip is a time-lapse' below), so the near-misses and gaps below test the tool only; they say nothing about the
street.*

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

- Bases: Glimmer's sample letter (now `kaggle/glimmer-sample-letter.txt`, facts rebuilt from `sample/`) and the Muse Spark letter
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
  *Both ran later the same day; see 'Judge bench results' below.*

## Review fixes, re-scored on the merged code (Thu 29 Oct, evening)

A review of the merged branches found README numbers from older code. Each was recomputed once, at $0, on the merged
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
- **Dense Indian clip:** re-scored here on the merged code, then withdrawn the same day: the clip is a time-lapse,
  so its conflicts, speeds and one number were never measurements (see 'The Indian clip is a time-lapse' below).

- **Tracker tweak after OC-SORT: tried, not shipped.** Velocity from 3 samples back and a second greedy
  round against each unmatched track's last seen box, scored with `validate_offline.py` on `out/dut-15s` and
  `out/dut-vcrowd` (the change patched in for that run only, never committed):

| | Today's tracker | Tweak |
|---|---|---|
| Found after review (crowd / vehicle crowd mode) | 44 / 45 of 52 | 44 / 45 of 52 |
| Found by the geometry | 49 / 48 | 49 / 48 |
| False alarms (of them at a threshold) | 5 (2) / 6 (2) | 5 (2) / 6 (2) |
| Pedestrian crossings, against 280 true | 374 | 357 |
| Tracks for the 296 pedestrians followed (split ones) | 325 (23) | 316 (18) |
| Events on pieces Spark never saw | 8 / 17 | 19 / 26 |

  Recall and false alarms hold, so by our ship rule (recall and false alarms must not get worse) it could ship. It is not shipped before the gate run: it finds
  nothing more, and it moves 20 events onto track pieces with no stored Spark verdict, so the README's after-review
  DUT numbers could no longer be checked at $0 without a paid Spark re-review.
- **Single concept "vehicle":** `vehicle_test.py` now holds the test (60 cached crowd frames of the Indian
  clip sent with "vehicle", about $0.15, capped at $0.20; boxes matched at IoU 0.5 against car, motorcycle and auto
  rickshaw; adopt at 95% recall). It has not been run, so "vehicle" is not adopted and $34 for 15 minutes is a
  condition, not a plan.
- **Waiting for the gate footage, no code yet:** the horn fused with a speed profile, the 20 km/h ghost car,
  parked vehicles and the SAM video re-check. Each is built only if its go/no-go check on the first
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

## The Indian clip is a time-lapse; people are the clock (Thu 29 Oct 2026)

- **Finding.** `test-videos/indian-intersection.mp4`, the YouTube stock clip behind `out/indian-crowd`,
  `out/indian-15s` and `out/indian-intersection`, is a time-lapse. It is 39 s at 30 fps; in 16 consecutive source
  frames (0.53 s; frames 300-315 checked by eye) people cross half the road and the whole traffic state changes.
  Its worst cached near-miss (`out/indian-crowd/event1.mp4`, 87.9 km/h, PET 1.2 s) is the pedestrian's box sliding
  over empty road while the car's box jumps between cars: crowd mode's tracker joined different road users across
  the skipped time. That is where the stored events' "phantom" speeds came from: up to 87.9 km/h in `out/indian-crowd`
  and 100.5 km/h in `out/indian-15s`.
- **Withdrawn:** every speed, PET, near-miss count, one number and gap from that clip. Rewritten in place above: the
  28 Oct status's event count, vehicle crowd mode's event counts, the speed fix's 88 and 57 km/h, the re-score
  table's Indian row and its note, the one-number recompute, the merged-code re-score and its table, and a note on
  the blind-set dry run. In the README: the DUT section's Indian paragraph (543 near-misses, 22 and 6 events, 36 and
  46 km/h) and the Limits section's 12 of 22 inferred positions.
- **Still meaningful:** only its detection coverage, objects found per frame (SAM video 1.6 people and 6 vehicles a
  frame, crowd mode 14.9 people and 20), and what follows from it: all 12 SAM video requests filled, people's within
  1.0-1.6 s of each part. The SAM bill per video second ($0.34 for 39 s) and the `vehicle_test.py` design (boxes
  matched per frame) are not about time on the street, so they stand.
- **Guard, `pace.py` (commit 30bdc87).** People walk at about 1.2-1.5 m/s. analyze.py writes the median walking speed
  of the pedestrian pieces that crossed (each piece's median speed over its moving frames, the crossing count's own
  pieces) to events.json as `"walking"`. With 10 or more walking pieces, a median over 2.4 m/s (sped up, or a
  calibration rectangle marked too big) or under 0.5 m/s (slowed down, or marked too small) flags the video: the
  page shows a warning in place of the headline, near-miss and speed tiles, pyramid, engineering numbers and gap
  barcode, heads the cards "not measurements", and neither pack.py nor the case agent asks any model for a letter.
  An unflagged run's numbers and page are unchanged (self-checked).
- **Medians measured to set the thresholds**, at $0: each run's tracks rebuilt from its cached SAM replies (crowd
  caches from exactly the frames cached), Spark and SAM stubbed to fail on a cache miss, nothing written under
  `out/`; SinD and DUT ground truth cut into pieces the way analyze.py cuts ours. The tracks were rebuilt with
  analyze.py's own track code; the caches and the DUT and SinD data are not public.

| Video | Walking pieces | Median walking speed | Guard |
|---|---|---|---|
| DUT, our tracks, crowd mode (8 clips; `out/dut`, `out/dut-15s` and `out/dut-vcrowd` share these caches) | 13-129 per clip | 1.08-1.47 m/s | not flagged |
| DUT, our tracks, SAM video, whole frame / 2 x 2 tiles (8 clips each) | 11-16 / 12-48 | 1.11-1.44 / 1.05-1.48 m/s | not flagged |
| DUT, the dataset's own tracks (8 clips) | 280 | 1.22 m/s | not flagged |
| SinD, the dataset's own tracks (20 min) | 63 | 1.13 m/s | not flagged |
| Schoolchildren CCTV, assumed calibration: one request / 15 s parts | 13 / 14 | 0.80 / 1.66 m/s | not flagged |
| Indian time-lapse, crowd mode | 13 | 2.71 m/s | flagged: sped up |
| Indian time-lapse, SAM video: 15 s parts / one request | 0 / 0 | none | not judged |

- **Why these thresholds.** Every real video here reads 0.80-1.66 m/s. 2.4 m/s is 1.45x the fastest of them; 0.5 m/s
  is 0.6x the slowest. 10 pieces: the fewest on a real run here is 11.
- **Limits.** The guard sees only the people the tracker keeps. On the time-lapse the fastest were cut at the 10 m/s
  jump rule or lost, so crowd mode reads 2.1x normal walking, not the true speed-up, and SAM video mode kept no
  walking piece at all: those runs are not judged, and their numbers are withdrawn by this entry, not by the code. A
  video sped up less than about 2x would pass. The kids clip's two runs differ by 2x (waiting children and running
  ones), so a crossing where most people run could be flagged.
- 137 self-checks pass.

## Judge bench results (Thu 29 Oct 2026)

Both judges have now run on the bench above: 24 letters with one planted lie each and 8 clean controls.

- **Muse Spark** (Meta API, two runs per letter, run on this laptop): flagged 24 of 24 letters with a planted lie
  (Wilson 95% 86-100%) and 1 of 8 clean controls (2-47%): Glimmer's letter with "near-misses, not recorded accidents"
  added, in one of its two runs. 0 of 64 replies were unreadable. Re-scored at $0 on 29 Oct from a copy of the bench
  file, with no judge asked (`judge_bench.py --out COPY`).
- **Muse Glimmer 30B** (one run per letter): its result is withdrawn from this repository.
- **Code check alone**, unchanged: 4 of 24 (7-36%), 0 of 8 (0-32%).
- "Flagged", not "caught": the bench keeps only whether a judge listed a problem, not which one, so whether it named
  the planted lie is not checked. A judge that objects to almost everything flags every lie too, so the clean
  controls matter: Spark's 1 of 8 is from only 8 of them.
- Both are Muse models, so neither is an independent judge of Muse letters, and the two base letters were written
  by Glimmer and by Spark.

| Planted lie | Named in JUDGE_PROMPT | Code | Muse Spark |
|---|---|---|---|
| standard said to be met | yes | 0/2 | 4/4 |
| death risk for a child | yes | 0/2 | 4/4 |
| named person blamed | yes | 0/2 | 4/4 |
| injuries invented | yes | 0/2 | 4/4 |
| cause invented | yes | 0/2 | 4/4 |
| every school day | no | 0/2 | 4/4 |
| deaths prevented | no | 0/2 | 4/4 |
| near-miss called a collision | no | 0/2 | 4/4 |
| children claimed | no | 0/2 | 4/4 |
| number in words | yes | 2/2 | 4/4 |
| km/h written as mph | no | 2/2 | 4/4 |
| near-misses swapped | no | 0/2 | 4/4 |
| **All planted lies** |  | 4/24 (7-36%) | 24/24 (86-100%) |
| Named kinds | yes | 2/12 (5-45%) | 12/12 (76-100%) |
| Kinds not named | no | 2/12 (5-45%) | 12/12 (76-100%) |
| **Clean controls: false alarms** |  | 0/8 (0-32%) | 1/8 (2-47%) |

In the rows per kind a cell counts runs; every other cell counts letters, one flagged if any of its readable runs
flagged it. Muse Glimmer's column, and the Any column built on it, are withdrawn from this repository.

## Wording: the at-a-threshold bands are not our error (Thu 29 Oct 2026)

- README called the bands that define "at a threshold" (PET +0.3 s, gap +0.3 m, speed ±1.5 km/h) "about our
  measured error". They are `validate_dut.py`'s bands, and PET +0.3 s is only about our median PET error. Re-scored
  at $0 on 29 Oct from the cached DUT runs and Spark's stored verdicts, on the events matched after review: median
  absolute PET error 0.2 s in vehicle crowd mode (45 matched) and 0.25 s in crowd mode (44); 90th percentile 1.0 and
  1.1 s; within 0.3 s on 29 of 45 and 26 of 44; mean signed error -0.16 and -0.24 s (ours a little short).
- `PET_BAND_S` stays 0.3, so no "at a threshold" count moves; only the README's words changed. Its SinD line
  "errs on the side of not overstating" now says "on SinD": on DUT our PET reads a little short.

## Window rule, pre-registered (Thu 29 Oct 2026, before the rehearsal or the main recording is filmed)

Which seconds of a gate recording are analysed (the site file's `window_s`) is fixed by this rule, so the window
cannot be picked after seeing the near-misses. It holds for Saturday's rehearsal and Monday's recording alike.

- **The bell, B.** The second of the recording at which the dismissal bell is heard on it. If it cannot be heard: the
  bell's clock time noted on the day (else the bell time spoken at the start of the recording), minus the
  recording's start (`creation_time` from ffprobe, in UTC: add 5 h 30 min for IST).
- **The window.** `window_s` is [S, S + 900], with S = B - 120: 15 minutes from 2 minutes before the bell. If the
  recording started less than 2 minutes before the bell, S is 0.
- **Shorter only when** the recording ends before S + 900, or the camera moved inside the window (`filmcheck.py`, or
  by eye): the window then ends at the last whole second before the end or the move. A move before S leaves no
  window, and that recording is not analysed. A window under 900 s is analysed as it is; the page then gives no
  hourly rates, PV² or school-year line.
- **Never changed** after anything made from that recording's analysis (events, the page, a clip) has been seen, and
  never for cost: the free estimate (`--budget 0`) chooses the modes, never the window.
- With FILMING.md's hand-cut fallback, the cut starts at S and lasts the window's length, and both SHA-256s are noted.
- B, how B was found, S and the end are written in this file with the run's result.

## G7 After-fix pass mark, pre-registered (Thu 29 Oct 2026, before the rehearsal or the main recording is filmed)

How anyone would know a fix worked. This rule is fixed now. The mark itself is worked out from Monday's counts on
Mon 2 Nov at night and written here before any fix exists. No film after a fix can exist before submission, so G7
has no verdict before then, and the page never shows an "after" result.

- **Counts, from a pack's events.json.** n: the people who crossed, each once (the page's one number). k: those of
  them with a moving vehicle through the same spot within 3 s. V: the distinct vehicles among the first such vehicle
  for each of the k people. People cross in groups and one vehicle can pass several of them (on DUT's ground truth,
  run at $0 on 29 Oct: 44 people within 1.5 s of a vehicle, from only 11 vehicles), so a drop must show in V too.
- **Test.** A one-sided Fisher exact test, before against after: the chance, if nothing changed and with both films'
  totals fixed, that the after-film's count is as low as it is or lower. "Drop shown" means p ≤ 0.05 for k (the
  after-film's k of its n against Monday's k of n) and p ≤ 0.05 for V (its V of its n against Monday's V of n).
  Both must pass. p ≤ 0.05 is the one comparator, everywhere.
- **3 s is the deciding tier; 1.5 s is printed beside it.** With 4 or fewer people within 1.5 s on Monday, no
  after-film of the same length could show a drop at 5%. On SinD's two 10-minute halves (nothing changed between
  them; run at $0 on 29 Oct), the 3 s test would show a halved share with 74% chance against 39% for 1.5 s, and
  neither half shows a drop against the other (p 0.55-0.64).
- **The mark, written here on Mon 2 Nov night:** the largest after-film k and V that pass for an after-film of n
  crossings; the chance of passing if the true share halved, with one and with two after-films; and when no count
  can pass, the fewest same-length films after the fix that would give a mark. Then never changed.
- **The after-film.** The same spot, stand, tape marks and calibration (the same `world_points`), the same minutes by
  the window rule above, the same site settings (modes, vehicles, `person_grid`). G7 is not tested if either film
  is flagged by the walking-pace guard, has no crossers list, or was calibrated differently.
- **Reading it.** A drop shown is a drop between two dismissals at that crossing, not proof that the fix caused it:
  traffic differs from day to day. No drop shown does not show the fix failed; one after-film can be too short to
  show a real drop. A "no drop shown" goes in the README, never in the video or the X post.

## G8 Second operator, pre-registered (Thu 29 Oct 2026, before the rehearsal or the main recording is filmed)

After SAM, the calibration clicks are the main human judgement left. G8 asks whether someone who has never seen the
code gets our numbers from the same frame and the same tape.

- **Scope.** The clicks only, on our tape marks and our calibration frame. Not the taping, the measuring or where the
  camera stands. G8 does not show that any school can run Crossing Watch.
- **Site B.** A classmate who has never seen the code gets only `calibrate.html`, our calibration frame and the
  taped rectangle's lengths, on our laptop (the raw video stays with us), and clicks the four rectangle corners.
  Site A's `trap` (its four image points and distance) is copied into site B, so both runs measure the same tape
  marks. G8 is not run if site B's `world_points`, `frame_size` or `marked_on` differ from site A's, and site B's
  corners are checked by eye to be in site A's order (a different first corner turns the road frame).
- **Run, at $0 from the same cached SAM replies:** `python3 validate_gate.py SITE_A.json OUT TRAP.csv`, then the same
  with `SITE_B.json`.
- **Pass:** (a) each run puts the speed lines within ±5% of 15 m (its line "the calibration puts the lines X m
  apart"), and the two runs within ±5% of each other; and (b) G6 gives the same verdict (pass, fail or not tested)
  under both site files, with its two median signed errors within 5 percentage points. When G6 is not tested it
  prints no median, and (b) is the verdict alone. **Fail:** anything else. **Not tested:** no `TRAP.csv` or no site B.
- **No bar on the headline count:** a bar on k would either fail on calibration noise or pass by design.
- **When:** after G6's log and Monday's run, so Monday night or Tuesday. A fail is reported here and in the README as
  it is. In the video only a pass, as a caption next to G6's result.

## Feet-hidden rule, people side only (Thu 29 Oct 2026, commit d53f9f1)

- **Rule.** From a phone at an angle, a person's frame is dropped when the bottom of its box, at its centre, sits on
  a vehicle's box (from 2 px above its top to 2 px above its bottom): a scooter rider whose box only sits on the
  bike's, which the rider filter misses, or feet hidden by a nearer vehicle. People only, never vehicles against
  vehicles. Top-down views are untouched, and the site key `"feet_hidden": false` switches it off.
- **Both ways, at $0**, each run rebuilt from its cached SAM replies with the rule off and on; re-run on the merged
  build on 29 Oct with the same figures. The share is reported here as "feet hidden", not on the cards.

| Run | Person box-frames dropped (after the rider filter) | What changes |
|---|---|---|
| Schoolchildren CCTV, one request | 0 of 2,293 (0%) | nothing (1,440 frames, 7 crossings, 0 events, 13 walking pieces at 0.80 m/s) |
| Schoolchildren CCTV, 15 s parts | 4 of 1,829 (0.2%) | frames 1,017 to 1,013, nothing else (14 walking pieces, 1.66 m/s) |
| Indian time-lapse, crowd mode | 2,122 of 6,204 (34.2%) | pieces 17 to 10, crossings 13 to 7, events 22 (14 serious) to 10 (7 serious), moving vehicles 28 to 28, walking pieces 13 to 7 at 2.71 m/s |
| Indian time-lapse, SAM video: 15 s parts / one request | 74 of 599 (12.4%) / 5 of 235 (2.1%) | nothing |

- **The Indian clip.** Its changes are relative, with no ground truth, and the clip is withdrawn as a measurement (see
  'The Indian clip is a time-lapse' above). With 7 walking pieces the pace guard no longer judges it; the site
  file's `not_measurements` still marks it.
- **DUT** is top-down, so the rule is off there: validate_offline's totals at d53f9f1 were byte-identical to before
  it, 44 and 45 of 52 after review (crowd and vehicle crowd mode; the next entry moves the second).
- **SinD:** no gain is claimed.
- **Risk.** A true near-miss with a bike between the camera and the person loses frames, so its PET can grow by the
  hidden time.

## Spark's "unclear" keeps the person (Thu 29 Oct 2026, commit 45bfd46)

- **Rule.** Only a sure "no" from Muse Spark removes a person: "unclear" with the cyan box called not a pedestrian now
  keeps them (`review.gated`, marked `review_unclear`; the card says "pedestrian (Spark unsure; kept)"), and a
  blind-set decoy is never someone Spark was unsure of. The rule was set after seeing 3 DUT cases, post hoc, with no
  held-out check.
- **Re-scored at $0** with `validate_offline.py` on the cached DUT runs and Spark's stored verdicts, on the merged
  build on 29 Oct:

| Mode | Found by the geometry | Found after review, before / after the rule | False alarms after review (at a threshold) |
|---|---|---|---|
| Vehicle crowd mode (`out/dut-vcrowd`) | 48 of 52 | 45 / 48 of 52 | 6 (2) / 6 (2) |
| Crowd mode (`out/dut-15s`) | 49 of 52 | 44 / 44 of 52 | 5 (2) / 5 (2) |

- So in vehicle crowd mode Spark's review now makes no net difference (48 with or without it), and in crowd mode it
  costs 5 real conflicts while removing one false alarm (the geometry alone: 6 false alarms, 2 at a threshold). With
  every unreviewed piece rejected the worst case is 33 of 52 in vehicle crowd mode (30 before the rule) and 37 in
  crowd mode.
- The new crop (the cyan box drawn after upscaling, outside the person) has new bytes, so Spark is asked again on the
  next paid run; until then these are its stored verdicts on the old crops.

## G6's log with a window, and the tape marks in calibrate.html (Thu 29 Oct 2026, before the rehearsal or the main recording is filmed)

- With `window_s`, analyze.py tracks only seconds S to E, and `validate_gate.py` reads TRAP.csv's times on the whole
  original but counts only the vehicles that cross both lines inside the window (commit 08b28be). So G6's "from the
  start of that video" is read as from second S: the log starts with the first vehicle that crosses both lines at or
  after S, and goes on in order until 30 are logged. A log started at second 0 would spend its vehicles before S.
- `calibrate.html` writes `"trap"` from four optional speed-line clicks after the rectangle's corners (A near, B near,
  B far, A far, and the taped distance between the lines, 15 m by default; commit 26defae), and the case agent's
  `"check"` from A near and B near: a road distance along the near kerb that calibration does not use, as G2 asks.
  Checked under a DOM stub only; not yet clicked through in a real browser.
- The G6 and window rule text above is unchanged.

## The README's first-screen numbers, re-checked at $0 (Thu 29 Oct 2026)

On the merged build (commit 5083592), with no key in the environment and no API call:

- `python3 validate_offline.py DUT_REPO out/dut-vcrowd out/dut-15s`: 48 and 44 of 52 found after Spark's review, 48
  and 49 by the geometry (vehicle crowd mode and crowd mode); speed against the dataset's native-rate positions
  0.16 / 0.55 km/h (mean / 95th percentile, vehicle crowd mode, 2,079 frames). The same as the entries above.
- `judge_bench.py --out COPY` on a copy of the bench file, no judge asked: code 4 of 24 and 0 of 8, Muse Spark 24 of
  24 and 1 of 8, 0 of 64 replies unreadable. Glimmer's column is withdrawn from this repository.
- The quick start on a `git archive` copy, which holds no `.env`: `python3 test_cw.py` passed 173 self-checks in 19 s,
  and `python3 pack.py sample sample/site.json` wrote a measurements-only page ("2 serious, 0 close passes, fix:
  none"), saying the letter needs `MODEL_API_KEY` or `LETTER_MODEL_URL`.

## Spark's rider call needs the feet no lower than the bike (Thu 29 Oct 2026, commit 5d8d222)

- **Rule.** Muse Spark calling someone a rider removes them only when their feet are no lower than a bike's box
  (`review.gated` now uses road.py's rider rule, `road.RIDER_FEET_PX`), so a walker passing in front of a parked bike
  stays a pedestrian, marked `rider_unconfirmed`.
- **Re-scored at $0** with `validate_offline.py` on the cached DUT runs and Spark's stored verdicts, before and after
  the rule: no number changed. Vehicle crowd mode (`out/dut-vcrowd`): 48 of 52 by the geometry and after review, 6
  false alarms, speed 0.16 / 0.55 km/h. Crowd mode (`out/dut-15s`): 49 of 52 by the geometry, 44 of 52 after review, 5
  false alarms, speed 0.15 / 0.43 km/h. The README's numbers stand.
- **What this re-score cannot show.** DUT is top-down and its runs track no bikes, so no bike box exists there and
  the re-score never exercises the feet condition. The rule is covered by a unit test only
  (`test_spark_rider_call_needs_the_feet_no_lower_than_the_bike`) and is unchecked on real footage.

## Accuracy fixes merged, re-scored at $0 (Fri 30 Oct 2026)

Three fixes merged into `build` (merge commits f9f2cf6, c7131a4, d5d9a1b), each re-scored alone and together with
`python3 validate_offline.py DUT_REPO out/dut-15s out/dut-vcrowd` on the cached SAM replies and Spark's stored
verdicts, no key and no API call. "Real" false alarms are those not at a threshold.

| Mode (DUT, 52 true conflicts) | Before (07b0777) | After (d5d9a1b) |
|---|---|---|
| Crowd: geometry / after review | 49 / 44 found; 5 false alarms (3 real) | 50 / 47 found; 3 false alarms (1 real) |
| Vehicle crowd: geometry / after review | 48 / 48 found; 6 false alarms (4 real) | 49 / 49 found; 4 false alarms (2 real) |
| Unreviewed events (crowd / vehicle crowd) | 8 / 17 | 22 / 27 |
| If Spark rejected every unreviewed event | 37 / 33 of 52 | 26 / 23 of 52 |
| Speed vs native rate (vehicle crowd) | 0.16 / 0.55 km/h | 0.16 / 0.55 km/h |
| SinD (`validate_sind.py data/sind`) | 66 conflicts; speed 0.24 / 0.91 km/h | unchanged |
| `test_cw.py` | 209 checks pass | 212 pass |

- **Crowd tracker keeps a hidden walker** (`crowd.py`): a lost ID is kept for 2 s (was 1 s) and its match gate widens
  by half a box size per missed sample, so a walker hidden behind a car keeps one track. Alone: geometry 49 to 50
  (crowd) and 48 to 49 (vehicle crowd); after review 44 to 45 and 48 to 49; false alarms unchanged. The pieces are
  rebuilt, so Spark's stored verdicts no longer cover 14 and 10 more events: they stay in, as on the page, and the
  worst case above falls. A real run sends those pieces to Spark (paid; done the same day, below).
- **A piece that never moves is dropped** (`road.py`, `stays_put`): 90% of its points within 0.75 m of its median
  spot over its whole life, however short (the 15 s still-run rule missed short clips). Alone: removes the person
  standing still at the road edge in clip 09 (one real false alarm in each mode); no conflict found or lost.
- **Walking motion overrules Spark** (`review.gated`, `analyze.motion`): a "not a person" piece walking 1.5-8 km/h
  over at least 2 m with no other piece within 1.5 m on most frames is kept, marked `review_disputed` and named on the
  page, never a blind-set decoy; a rider call over 8 km/h stands without a bike box. Alone: crowd after review 44 to
  45, and the clip 10 close pass (a fast "rider") is removed. Set after seeing the DUT cases; its first held-out test
  is new footage.
- Matched-event accuracy (crowd mode): speed within 1 km/h on 44 of 47 (was 42 of 44, which the README had as 41);
  PET within 1 s on 41 of 47 (was 38 of 44). The video-mode rows: whole frame unchanged; 2 x 2 tiles lose one real
  false alarm (7 to 6). No FPS, width, chunk, overlap or sampling constant changed, so every cached reply still holds.
- **Paid Spark re-review of the unreviewed pieces** (same day, after 1a6a919): `validate_offline.py --spark N` sends
  Spark only the crops with no stored verdict and no saved reply, and saves each reply beside its crop
  (`review.review`), so later $0 runs read it; SAM is never called (a cache miss stops the run). 45 pieces (20 crowd,
  25 vehicle crowd) needed a look; 19 vehicle-crowd crops were byte-identical to crowd ones and reuse their reply, so
  Spark was called 26 times: 8,476 input and 7,912 output tokens, about $0.04 at the muse-spark-1.3 list price
  ($1.25 / $4.25 per 1M). Verdicts on the 45: 1 "not a person" stands (a clip 09 walker in vehicle crowd mode), 16
  rider calls are overruled for want of a bike box, the rest kept. Printed by `validate_offline.py` before and after:

  | Run | Before | After |
  |---|---|---|
  | Crowd (`out/dut-15s`) | matched 47, missed 5 (3 by review), extra 3 (2 at threshold), unreviewed 22 | matched 47, missed 5 (3 by review), extra 3 (2 at threshold), unreviewed 0 |
  | Vehicle crowd (`out/dut-vcrowd`) | matched 49, missed 3 (0 by review), extra 4 (2 at threshold), unreviewed 27 | matched 48, missed 4 (1 by review), extra 4 (2 at threshold), unreviewed 0 |

  The one loss is the clip 09 conflict at 7.9 s that crowd mode already lost to review. Speed vs native rate and
  SinD (`validate_sind.py data/sind`, output byte-identical) unchanged.

## Spark Open judge effort (Sat 31 Oct 2026)

Fireworks' workshop found Muse Spark Open scores best at `reasoning_effort=low` on short-answer tasks. Our Spark Open
calls sent no effort, so Fireworks' default ran. We ran Spark Open as the `JUDGE_MODEL_URL` judge (`JUDGE_VOTES=1`,
one run a letter) on a copy of `kaggle/judge-bench-public.json` (the 31 synthetic sample-only letters; the public file
is unchanged), once at each effort. Wilson 95% bounds:

| Effort | Lies caught | False alarms | Mean completion tokens | Cost (31 calls) |
|---|---|---|---|---|
| `low` | 22/23 (79-99%) | 0/8 (0-32%) | 739 | $0.14 |
| Fireworks default (none sent) | 22/23 (79-99%) | 0/8 (0-32%) | 1,480 | $0.24 |

Both missed the same letter (km/h written as mph, in Spark Open's own letter), with no unreadable reply and no
truncation. Equal on this bench at about 60% of the cost, so the judge now sends `pack.JUDGE_EFFORT = "low"`, to
Fireworks only (`openweights.reply`; llama-server is sent no effort). The letter writer still runs at Fireworks'
default: its effort was not measured. Total spend $0.40, two one-call probes included.

## Fine-tuned Glimmer judge v2: the sweep and how its winner is chosen (pre-registered Sat 31 Oct 2026, before any v2 run)

v1 (rank 8, 1 epoch, learning rate 1e-4) is recorded in `kaggle/open-weights.md`. v2 adds training letters (Muse
Spark via the Meta API as well as Spark Open) and "near-misses swapped" rows. Every v2 run uses the same file and
split: train rows; a dev set of whole synthetic letters; all 31 public-bench prompts. Dev and public rows are held out
of training in every run (checked by replaying the starter's shuffle).

- **Configs, in this order:** A rank 8, 1 epoch, 1e-4. B rank 32, 1 epoch, 1e-4. C rank 8, 2 epochs, 1e-4.
  D rank 32, 2 epochs, 5e-5. Seed 0, max sequence length 3,072, the starter's other defaults.
- **Chosen on dev only:** the highest of (dev lies flagged) minus 2 x (dev clean letters flagged), replies read by
  `pack.read_problems` (an unreadable reply counts as not flagged). A tie goes to the config earlier in the list.
- **Public bench:** the public rows' replies are not read until the winner is named here. Then the winner's public
  score is the reported result, and the other configs' public scores are listed after it, labelled as not chosen.
- If no v2 config beats v1 on dev by this score, v1 stays the reported model.
- **Dev result and winner (Sat 31 Oct 2026, 05:10 IST, written before any public reply was read):** A 101/105 lies,
  0/75 clean flagged (score 101); B 104/105, 0/75 (104); C 104/105, 0/75 (104); D 104/105, 0/75 (104). B, C and D
  tie; the rule gives **B** (rank 32, 1 epoch, 1e-4). No reply was unreadable. A's and D's promotions to the account
  failed (A: an upper-case run id; D: Fireworks HTTP 500), after their evaluation; B's model was promoted.

## Same-set comparison on 211 judge prompts (Sat 31 Oct 2026)

Written after the v2 winner was named above; not pre-registered. `judge_compare.py` (commit dfb983e) asked Muse Spark
(Meta API) and Muse Spark Open (Fireworks, effort low) the 211 v2 holdout prompts the four configs answered (180 dev,
31 public), one vote each, no unreadable reply ($3.08; replies in `provenance/glimmer-judge-lora-v2/bench211/`). An
independent recount from the raw replies matched every count, Wilson 95% bound and p. Correct = flagged iff planted.

| Set | Judge | Lies flagged | Clean letters flagged | Correct |
|---|---|---|---|---|
| public 31 | Glimmer+LoRA B (chosen) | 23/23 (86-100%) | 0/8 (0-32%) | 31 |
| public 31 | Muse Spark | 22/23 (79-99%) | 0/8 (0-32%) | 30 |
| public 31 | Muse Spark Open | 22/23 (79-99%) | 0/8 (0-32%) | 30 |
| all 211 | Glimmer+LoRA B (chosen) | 127/128 (96-100%) | 0/83 (0-4%) | 210 |
| all 211 | Muse Spark | 126/128 (94-100%) | 37/83 (34-55%) | 172 |
| all 211 | Muse Spark Open | 126/128 (94-100%) | 5/83 (3-13%) | 204 |

Paired exact McNemar, all 211 (rows only B gets right vs only the Muse judge): B vs Spark 38 vs 0, p 7.3e-12; B vs
Spark Open 7 vs 1, p 0.07, not significant. 180 rows are the dev set B was chosen on; on the 31 public rows alone B
vs either is 1 vs 0, p 1. Configs A, C, D and the dev rows: `python3 judge_compare.py`.

**Correction, same day, after reading Spark's flags:** all 75 dev letters labelled clean mention video, while their
measurements say "made-up tracks, no video" (the synthetic packs). 32 of Spark's 37 flags on them name only that
contradiction, and under the judge prompt ("MEASUREMENTS are the only facts") they are right; so are all 5 of Spark
Open's. The clean-letter column on these rows measures a flaw in our synthetic labels, not false alarms, so the
"38 vs 0, p 7.3e-12" above is **withdrawn**. What stands: on the 128 planted rows B flags 127, Spark 126, Spark Open
126 (level); on the 31 public rows B 31, Spark 30, Spark Open 30 (1 vs 0, p 1); a reply from B averages 26 output
tokens against Spark's 2,153 and Spark Open's 877. Spark flagged 21/23 public lies in the earlier run and 22/23 here
(one vote each). B was trained on the same labels, so it learned not to flag a video claim against "no video"; real
packs come from video, but B's behaviour on that contradiction is untested. A v3 would drop "no video" from the
synthetic packs' measurements.

## Fine-tuned Glimmer judge v3 (pre-registered Sat 31 Oct 2026, before any v3 run)

**Flaw and fix.** v2's packs said "no video", so its clean labels were wrong (the Correction above), and its held-out
lies reused the training wordings, which a judge could recognise. v3 names the site "ROAD crossing" (7c5d1c2), trains
on v2's 150 letters (1,800 rows), tests on 30 fresh letters and model-written lies (`natural_edits.py`). Config fixed,
no sweep: v2's B (rank 32, 1 epoch, 1e-4, seed 0, max_seq_len 3,072, max_eval_tokens 256). Two runs: **main**, and an
**unseen-kind ablation** whose 1,612 train rows hold no "deaths prevented" or "near-miss called a collision" row. Both
hold out the same 448 prompts (starter shuffle replayed): 360 test, 57 natural, 31 public. Longest row 2,189 tokens.
- **Test letters:** 15 by Spark Open, 15 by Muse Spark (seeds 20000+, 30000+), RISKY words read by the existing policy;
  none shares a 12-word span with the public bench, each under 15% of its 12-word spans with any train letter (max
  13.9%). No shared span at all was tried first and is infeasible: 1 of the 150 train letters passes it against the
  other 149 (145 pass 15%, median 6.4%).
- **Natural lies:** Muse Spark (Meta API) and Spark Open (Fireworks) each edit 15 test letters, alternating, with one
  fixed prompt (`EDIT_PROMPT`, effort low): add one plausible sentence the measurements do not support, any kind, with
  why; separately, one restating only what they support. Code keeps an edit only if it adds exactly one sentence, a
  clean one only if every number is measured: 57 of 60 kept (Spark 28, Spark Open 29), 29 planted, 28 clean.
- **Labels:** before any tuned reply is read, Muse Spark and Spark Open (effort low, one vote) judge all 448 prompts; a
  row where either disagrees with its label is adjudicated, blind to tuned replies, under the judge prompt's rules, and
  changes only if the flag is a real problem there. Adjudicated labels are committed before tuned replies are read.
- **Primary:** correct per row (`pack.read_problems`; unreadable = not flagged) on the 417 test + natural rows, exact
  McNemar of main vs Muse Spark and vs Spark Open. **Secondary:** natural rows alone; clean rows flagged; public bench;
  ablation vs main on the 30 rows of the two unseen kinds (26 test, 4 public); tokens per verdict. All reported.
- **Row 402, decided before any tuned reply was read (Sat 31 Oct 2026):** spark/30007's natural clean row carries the
  same false "closest serious event was 1.0 s" sentence that adjudication found in rows 259-263, but neither judge
  flagged it, so under the protocol it was not adjudicated and stays clean. The primary result is reported that way,
  and once more with row 402 counted as planted.

## Fine-tuned Glimmer judge v3: result (Sat 31 Oct 2026, read after the labels were frozen in e21a283 and 91e81f6)

Main run (v2's config B, model `muse-starter-sl-judge-v3-main`), one vote, scored against
`provenance/glimmer-judge-lora-v3/labels-frozen.json`; replies in `provenance/glimmer-judge-lora-v3/main/`.

| Rows | Judge | Lies flagged | Clean letters flagged | Correct |
|---|---|---|---|---|
| test + natural (primary) | **Glimmer + LoRA v3** | 237/244 (94-99%) | **0/173 (0-2%)** | **410/417** |
| test + natural | Muse Spark | 238/244 (95-99%) | 15/173 (5-14%) | 396/417 |
| test + natural | Muse Spark Open | 230/244 (91-97%) | 1/173 (0-3%) | 402/417 |
| natural (model-written) | Glimmer + LoRA v3 / Spark / Spark Open | 28/29, 26/29, 26/29 | 0/28, 4/28, 1/28 | 56, 50, 53 of 57 |
| public 31 | all three | 22/23 each | 0/8 each | 30 each |

**Primary endpoint, exact McNemar on correct per row (test + natural):** v3 vs Muse Spark 19 vs 5, **p 0.0066**;
v3 vs Muse Spark Open 11 vs 3, p 0.057 (not significant at 0.05). With row 402 counted as planted: the same
discordant counts and p values (all three judges passed it). Replies average 94 characters. The unseen-kind ablation
run was stopped at step 10 (the laptop had to close) and has not been run yet.

**Unseen-kind ablation (run again from scratch as `judge-v3-unseen2`, same day):** trained without a single "deaths
prevented" or "near-miss called a collision" row, it flagged all 30 held-out rows of those two kinds (30/30, as did
the main run, Muse Spark and Spark Open, so these two kinds are easy for every judge) and got 411/417 test + natural
rows right with 0/173 clean letters flagged. So the main result does not rest on having seen those kinds; a harder
unseen-kind test would need kinds that the untuned judges miss. Replies: `provenance/glimmer-judge-lora-v3/unseen/`.

## Fine-tuned Glimmer judge v4: a large replication (pre-registered Sat 31 Oct 2026, 21:25 IST, before any v4 letter is written)

**One confirmatory test, reported whatever it shows.** v3 won on 417 rows; v4 asks whether that holds on about twice
as many rows that no earlier step has touched. v3's result above stays as recorded.
- **Recipe unchanged:** v3's training rows (the 1,800 TRAIN rows of `judge_v3.jsonl`, same "ROAD crossing" site fix)
  and v2's config B (rank 32, 1 epoch, 1e-4, seed 0, max_seq_len 3,072, max_eval_tokens 256), retrained once with the
  v4 holdout. No sweep, no second try.
- **Test:** 200 new letters (100 by Muse Spark Open, 100 by Muse Spark via the Meta API), seeds disjoint from every
  earlier seed, same rejection rules (0 shared 12-word spans with the public bench, under 15% of a letter's 12-word
  spans in any train letter, the code check, RISKY words read by the existing policy). Four rows per letter: the letter
  as written (clean); one template lie (kind drawn evenly across the planted kinds); one model-written lie and one
  model-written clean edit (`natural_edits.py`, editor alternating Muse Spark / Spark Open). About 800 rows, plus the
  31 public prompts.
- **Labels:** as in v3. Muse Spark and Spark Open judge every row once; every disagreement with the generator's label
  is adjudicated, blind to tuned replies, under the judge prompt's rules; labels are frozen and committed before any
  tuned reply is read.
- **Primary:** correct per row (`pack.read_problems`; unreadable = not flagged) on the ~800 new rows, exact McNemar of
  v4 vs Muse Spark and vs Muse Spark Open, two-sided, alpha 0.05 each. **Secondary:** model-written rows alone; clean
  rows flagged; public bench; tokens per verdict. Every number is reported, including a loss or a tie.
- **Amendment (Sat 31 Oct 2026, 22:22 IST, before any v4 training, label or tuned reply exists):** the test is enlarged
  to at least 1,000 new rows by adding letters with the same procedure and rules (seeds continuing from 40128 for Spark
  Open and 50109 for Spark, half each). Disclosed: the model-written edits' editor did not strictly alternate letter by
  letter, since RISKY review changed which letters made the cut; per writer the editors are near 50/50 (Spark Open's
  letters 50/50, Spark's 52/48). Edits already paid for were kept.
- **Before any v4 tuned reply was read (Sat 31 Oct 2026, after labels froze in 4484029):** rows 23 and 941 carry the
  same false sentence that adjudication found in their siblings 566 and 221, but no judge flagged them, so under the
  protocol they stay clean; the primary result is reported that way and once more with both counted as planted. Row
  785 is excluded: its "lie" is the editor's refusal text, so it plants nothing (a deviation from the written rule,
  which only foresaw a planted sentence the measurements support).

## Fine-tuned Glimmer judge v4: result (Sat 31 Oct 2026, read after labels froze in 4484029 and 86ae306)

Model `muse-starter-sl-judge-v4-main` (v3's recipe, retrained once), one vote, against
`provenance/glimmer-judge-lora-v4/labels-frozen.json`; replies in `provenance/glimmer-judge-lora-v4/main/`;
re-score: `python3 judge_v3_score.py v4`.

| 1,016 new test rows (primary) | Correct | Lies flagged | Clean letters flagged |
|---|---|---|---|
| **Glimmer + LoRA (v4)** | **998** | 512/525 | **5/491** |
| Muse Spark | 959 | 517/525 | 49/491 |
| Muse Spark Open | 980 | 493/525 | 4/491 |

**Primary endpoint met against both:** exact McNemar v4 vs Muse Spark 57 vs 18, **p 7.2e-06**; v4 vs Muse Spark Open
28 vs 10, **p 0.0051**. With rows 23 and 941 counted as planted: the same counts and p. On the 496 model-written rows:
487 vs 466 (p 0.0011) and vs 472 (p 0.0026). Public bench: 30/31 for all three. **Where it is weaker:** six letters
as written carried a real error of their own writer (found by adjudication); v4 flagged none of them, Muse Spark all
six and Spark Open three. On the 260 as-written letters v4 is ahead of Spark (251 vs 235, p 0.009) and level with
Spark Open (251 vs 254, p 0.51). So the tuned judge is better at planted and model-written lies and at not crying
wolf, and misses subtle slips a writer makes; the code checks and a second judge stay in the pipeline.

## Fine-tuned Glimmer judge v4: what the Muse Spark comparison rests on (Sun 1 Nov 2026; read after the result, not pre-registered)

The result above stands as recorded. This note says what it rests on, at $0 from `labels-frozen.json` and the committed
replies in `provenance/glimmer-judge-lora-v4/labels/`.
- **Most of Muse Spark's false alarms come from our prompt's wording.** `pack.JUDGE_PROMPT` asks for "a number above
  one written in words", which invites flagging ordinals; the training labels taught the tuned judge to read it our way
  (ordinals are fine), and the adjudication followed the same reading. Of Spark's 49 flags on clean rows, 41 list only
  ordinals ("second", "third", "fourth", "fifth"; 30 rows), only the method sentence ("SAM tracking", "road-plane
  geometry"; 9 rows), or both (2 rows). Rule: a flag counts when every problem it lists names one of those ordinals
  (and not "twice") or one of those two method phrases. The 8 that do not: rows 50, 74, 129, 531, 578, 739, 822, 848.
  The tuned judge flagged none of the 41.
- **Counterfactual, those 41 counted as not flagged:** tuned vs Muse Spark 16 vs 18, exact McNemar p 0.86 (998 vs
  1,000 right; Spark's clean rows flagged 8/491). Not a win. The same rule on v3: 11 of Spark's 15 clean-row flags,
  and 19 vs 5 becomes 8 vs 5, p 0.58.
- **What holds:** the win over Muse Spark Open (28 vs 10, p 0.0051), where 24 of the 28 are lies Spark Open missed (18
  model-written, 6 template); clean rows flagged 5/491 vs Spark Open's 4/491. All rows are synthetic and
  in-distribution: 1,016 rows from 260 letters.
- **Who adjudicated:** an AI agent (Claude, Anthropic), blind to the tuned replies, under written standards (the judge
  prompt's rules and v3's standards). It only moved labels from clean to planted (v4 12, v3 5) or excluded a row (v4 1);
  none from planted to clean.
- A fair re-test would add "ordinals and method descriptions are fine" to the prompt and re-run both Muse judges; not
  done.
- **Two phrases in the result above overstate (added 11:13 IST; the result's text is left as recorded):** "better at
  planted and model-written lies and at not crying wolf" holds against both judges only for correct per row (998 vs 959
  and 980): Muse Spark flagged more lies (517 vs 512 of 525; 253 vs 252 of 259 model-written) and Spark Open fewer
  clean rows (4 vs 5 of 491). "Level with Spark Open" on the 260 letters as written means not significantly
  different: v4 got 3 fewer right (251 vs 254, 3 vs 6, p 0.51).

## A code check for the writer's own slips (Sun 1 Nov 2026; built after reading v4, not pre-registered)

v4 showed the tuned judge misses slips a letter writer makes itself. `pack.slips` now checks three of them in code
and sends the letter back for another try: a "closest" time gap larger than the smallest measured (in the tier the
sentence names; "2nd closest" is left alone), "after the person"/"before the person" when the counts rule that order
out (sentences that state the counts are left alone), and more than two gaps "cut short" (only a recording's first and
last can be). It was written while looking at v4's adjudicated slips, so its catch rate on them is not a blind test:
it flags 11 of v4's 12 (all but 566, the most borderline) and all five of v3's (259-263). False alarms: 0 on the 750
clean train rows, 0 on the public bench's 8 clean letters, and on the v3 and v4 holdouts it flags only rows 402 and
941, which carry the same false sentence as rows adjudication had already found (they stayed clean only because no
judge flagged them). It changes no result above: the judges' scores are as recorded.

## Fine-tuned Glimmer judge v5: a fair test against Muse Spark (pre-registered Sun 1 Nov 2026, 11:28 IST, before any v5 letter, label or run)

v4's Muse Spark win rests mostly on flags our prompt's wording invited (the note above); here every judge reads the fix.
- **Prompt:** `pack.JUDGE_PROMPT` from b3b1fbe, which adds: "Ordinals ("first", "second", "third") and descriptions of
  how the measurement was made (tracking, road-plane geometry, the definitions) are not problems either." All three
  judges get it, and so does every v5 training and test row.
- **Training data:** v4's 260 test letters are not reused. Train = rows rebuilt with the new prompt from all earlier
  TRAIN letters (v3's 150) plus new train letters, in three families: template lies (as before); model-written lies
  and clean edits (`natural_edits.py`); writer-slip lies made by code (a wrong "closest" time gap, an order of arrival
  the counts rule out, a wrong count of serious near-misses or close passes, a wrong share or count of gaps, more than
  two gaps "cut short"), each with matching true restatements as clean controls.
- **Config:** rank 32, 2 epochs, learning rate 1e-4, seed 0, max_seq_len 3,072, max_eval_tokens 256; one run, no sweep.
- **Test:** 260 new letters (130 by Muse Spark Open, 130 by Muse Spark via the Meta API), seeds disjoint from every
  earlier seed, v4's rejection rules. Per letter v4's four rows (as written, template lie, model-written lie,
  model-written clean edit) plus one writer-slip row where code can plant one (kinds drawn round-robin); plus the 31
  public prompts rebuilt with the new prompt.
- **Labels:** as v4: Muse Spark and Spark Open judge every row once with the new prompt; disagreements are adjudicated
  blind by an AI agent (Claude, Anthropic) under its rules; frozen and committed before any tuned reply is read.
- **Primary:** correct per row (`pack.read_problems`; unreadable = not flagged) on the new test rows (public excluded),
  exact McNemar, tuned v5 vs Muse Spark, two-sided, alpha 0.05. **Secondary:** vs Muse Spark Open; the system (v5 OR
  `pack.slips` flags) vs Muse Spark; writer-slip rows alone; clean rows flagged; tokens and $ per verdict.
- Every result is reported, including a loss; v3's and v4's results stay as recorded.
- **Data-build note (Sun 1 Nov 2026, before any v5 label or run):** a new TRAIN letter that `pack.slips` flags is
  rejected (4 letters), so no train letter carrying a writer slip is labelled clean; test letters follow v4's rules.
  Model-written edits exist for all 260 test letters, the 60 new train letters and 29 of v3's 150 train letters.
- **Before any v5 tuned reply was read (Sun 1 Nov 2026, after labels froze in b143963):** the primary result is
  reported on the frozen labels, and twice more as sensitivity checks: with rows 92, 699 and 214 (an order of arrival
  the counts do not support, the adjudicator's closest call) counted clean, and with rows 115 and 931 (clean only
  because no judge flagged the same sentence their siblings carry) counted planted. Rows 608, 677, 865 and 996 are
  excluded: the editor wrote a refusal, not a lie.

## Fine-tuned Glimmer judge v5: result (Sun 1 Nov 2026, read after labels froze in b143963 and bc187e9)

Model `muse-starter-sl-judge-v5-main`, clarified prompt for all three judges, one vote, frozen labels
`provenance/glimmer-judge-lora-v5/labels-frozen.json`, replies `provenance/glimmer-judge-lora-v5/main/`.

| 1,278 new test rows (primary) | Correct | Lies flagged | Clean rows flagged |
|---|---|---|---|
| Glimmer + LoRA (v5) | 1,260 | 776/789 | 5/489 |
| **Muse Spark** | **1,271** | 786/789 | 4/489 |
| Muse Spark Open | 1,247 | 762/789 | 4/489 |

**Primary endpoint: not met. Muse Spark is ahead**, 7 vs 18, exact McNemar p 0.043. Against Muse Spark Open v5 wins,
22 vs 9, p 0.029. Sensitivity: rows 92/699/214 counted clean, 10 vs 15, p 0.42 (level); rows 115/931 counted planted,
7 vs 18, p 0.043. Where: on template lies 259/260 vs 258, model-written lies 249/249 vs 248, code-planted writer slips
260/260 vs 260, v5 is level with or ahead of Muse Spark; on the 20 real slips the letter writers made themselves (found
by adjudication) Muse Spark flags 20 and v5 8. Adding `pack.slips` to v5 changes the total by nothing (it catches 2
more slips and raises 2 more false alarms). Public bench: v5 31/31, both Muse judges 30/31.

## The writer-slip code check, widened (Sun 1 Nov 2026, 16:40 IST; built after reading v4's and v5's slips, not pre-registered)

`pack.slips` now also checks a "largest" near-miss gap below the largest measured (a sentence quoting the longest
gap between vehicles is left alone), a "fastest" speed below the fastest measured, a count of serious near-misses or
close passes that is not the measured one ("2 serious near-misses had 0.2 s" and a lone "1 serious event had" are left
alone), counts of person-first, vehicle-first and both-at-once that differ from those measured, and order counts said
of one tier that exceed or add up to more than that tier's events (the measurements count orders over all events); a
gap "cut short" at the start and end is no longer flagged. Built while looking at the slips, so this is not a blind
test. On the 32 real writer slips adjudication found (v4 12, v5 20) it flags 28 (was 19); the 4 it misses (v4 566, v5
92, 214, 699) give one event's order when the counts mix orders, a check left out because train letters labelled clean
say the same. False alarms: 0 on the 750 v4 and 1,556 v5 clean train rows and on every clean holdout row of v3, v4 and
v5, except v3 402, v4 941 and v5 115, which carry the same false sentence as rows adjudication called slips. Of v5's
260 code-planted test slips it flags 208 (was 156; gap counts and shares are still left to the judge). No result
above changes.

## Fine-tuned Glimmer judge v6: the open system against both Muse judges (pre-registered Sun 1 Nov 2026, 16:34 IST, before any v6 letter, label or run)

- **System:** a row is flagged if tuned Glimmer v6 flags it OR `pack.slips` flags it, with `pack.slips` frozen as
  committed in a270d6d (any later change to it is not part of this test). The tuned model alone is reported too.
- **Prompt:** v5's clarified `pack.JUDGE_PROMPT`, unchanged, for all three judges and every v6 training and test row.
- **Training data:** v5's training rows; plus model-written slip edits: for every train letter where affordable, a
  model rewrites one sentence to carry one subtle factual slip about the measurements (a wrong superlative, count,
  order, total or share), with a clean paraphrase of the same sentence as its control; plus the 32 real writer slips
  adjudicated in v4's and v5's test rows (usable now, since v6 tests on new letters). The other rows of v5's test
  letters are not added.
- **Config:** as v5: rank 32, 2 epochs, learning rate 1e-4, seed 0, max_seq_len 3,072, max_eval_tokens 256; one run.
- **Test:** 260 new letters (130 by Muse Spark Open, 130 by Muse Spark via the Meta API), seeds disjoint from every
  earlier seed, v4's rejection rules. Per letter: as written, template lie, model-written lie, model-written clean
  edit, code-planted writer slip (where code can plant one), model-written slip edit; plus the 31 public prompts.
- **Labels:** as v5: Muse Spark and Spark Open judge every row once with the clarified prompt; disagreements are
  adjudicated blind by an AI agent (Claude, Anthropic); frozen and committed before any tuned reply is read.
- **Primary (both must hold for "beats both"):** correct per row (`pack.read_problems`; unreadable = not flagged) on
  all new test rows (public excluded), exact McNemar, the system vs Muse Spark and the system vs Muse Spark Open, each
  two-sided at alpha 0.05 with the system ahead. **Secondary:** tuned v6 alone vs each Muse judge; model-written slip
  edit rows alone; real writer slips found by adjudication; clean rows flagged; tokens and $ per verdict.
- Every result is reported, including a loss; v3's, v4's and v5's results stay as recorded. v6 is the last judge run
  before submission.
- **Before any v6 tuned reply was read (Sun 1 Nov 2026, after labels froze in d2dbb29):** the primary results are
  reported on the frozen labels and three sensitivity checks: (A) rows 18, 556, 752, 782 (one event's order the counts
  do not support, the closest calls) counted clean; (B) rows 125 and 140 (clean only because no judge flagged the
  sentence their siblings carry) counted planted; (C) rows 1326, 1337, 1439, 1490 (slip edits of the same kind as the
  six excluded ones, left planted because both judges flagged them) excluded. The system uses `pack.slips` exactly as
  committed in a270d6d.

## Fine-tuned Glimmer judge v6: result (Sun 1 Nov 2026, read after labels froze in d2dbb29 and 881dbf0)

System = tuned v6 OR `pack.slips` (a270d6d); one vote; labels `provenance/glimmer-judge-lora-v6/labels-frozen.json`.

| 1,501 new test rows (primary) | Correct | Lies flagged | Clean rows flagged |
|---|---|---|---|
| System (v6 + code) | 1,445 | 959/1,006 | 9/495 |
| Glimmer + LoRA v6 alone | 1,442 | 954/1,006 | 7/495 |
| **Muse Spark** | **1,467** | 983/1,006 | 11/495 |
| Muse Spark Open | 1,403 | 911/1,006 | 3/495 |

**"Beats both" not met.** System vs Muse Spark Open: 84 vs 42, **p 0.00023 (win)**. System vs Muse Spark: 32 vs 54,
p 0.023 (**Muse Spark ahead**). Tuned alone: vs Spark Open 82 vs 43 (p 0.00062), vs Spark 32 vs 57 (p 0.011).
Sensitivity: (A) 36 vs 50, p 0.16 vs Spark; (B) and (C) unchanged. Where: model-written slip edits 225/230 vs Spark 214
(p 0.027, a win), template lies 259/260 vs 255; but model-written lies 214/245 vs Spark 243 (v5 had 249/249: training
on slip edits cost lie recall). As pre-registered, v6 is the last judge run before submission.

## A symmetric label audit of v5 and v6 (Sun 1 Nov 2026, post hoc)

Adjudication in v3-v6 looked only at rows where a Muse judge disagreed with the generator, so a wrong label on a row
only the tuned judge disagreed with was never checked: that could only count against the tuned judge. An AI agent
(Claude), shown no judge reply, re-checked all 46 such rows (v5 6, v6 40) mixed blind with 26 rows all three judges
agreed on. It agreed with every label: 0 of 72 changed (`provenance/symmetric-audit/`). The Muse Spark wins in v5 and v6
stand; the tuned judge's v6 misses are real (19 of them a child death risk worded by a model, which it catches when
the wording is the template's).

## Judge v7: the open ensemble against Muse Spark (pre-registered Sun 1 Nov 2026, 23:40 IST, before any v7 letter, label or run)

- **Why:** v6 had been declared the last judge run before submission; it lost to Muse Spark (1,445 vs 1,467). After
  v6, a post-hoc look at its saved replies found the system below (with tuned v6) 1,479 right, ahead of Muse Spark (33
  vs 21 discordant, p 0.13): not a result, it motivates one more confirmatory test. All runs v3-v7 stay reported.
- **System:** a row is flagged if tuned Glimmer v7 flags it OR Muse Spark Open (Fireworks, effort low, the clarified
  `pack.JUDGE_PROMPT`) flags it OR `pack.slips` flags it, `pack.slips` frozen as committed in 9c4573b (as a270d6d).
- **Tuned v7:** v6's training rows unchanged, plus about 600 model-written lie edits and about 600 model-written clean
  edits on v6's train letters (one inserted sentence each, diverse wording; the lies include a death risk for a child,
  invented outside facts such as a driver on a phone or reports from parents, a standard said to be met, one recording
  stretched to every day; Muse Spark and Spark Open edit alternately); no v6 test letter is used. Rank 32, 2 epochs,
  learning rate 1e-4, seed 0, max_seq_len 3,072, max_eval_tokens 256; one run.
- **Test:** 300 new letters (150 Spark Open, 150 Muse Spark), seeds disjoint from all earlier, v4's rejection rules;
  per letter v6's six rows (edits asked with v6's prompts) plus the 31 public prompts. Every model-written edit is
  checked by code as before (a clean one keeps only measured numbers); refusals are dropped.
- **Labels:** as v6 (both Muse judges once on every row, clarified prompt; disagreements with the generator label
  adjudicated blind by an AI agent, Claude). Symmetric this time: rows where only tuned v7 disagrees get the same blind
  check, mixed with as many all-agree controls, after the tuned replies exist but shown no judge reply. Labels frozen
  and committed before any score is read.
- **Primary:** correct per row (`pack.read_problems`) on all new test rows (public excluded), exact McNemar, the system
  vs Muse Spark, two-sided, alpha 0.05. **Secondary:** (system vs Spark Open is not meaningful: it is part of it) tuned
  v7 alone vs Muse Spark and vs Spark Open; clean rows flagged; $ per verdict. Every result is reported, even a loss.
- **Amended Sun 1 Nov 2026, 23:45 IST, before any v7 letter, label or run (the user approved):** for power (v6's
  post-hoc 33 vs 21 discordant would need about 2,700 rows to reach p < 0.05), the test is 450 new letters, 200 by
  Spark Open and 250 by Muse Spark; to save Fireworks credit, Muse Spark edits 2 of every 3 letters (test and train,
  Spark Open the third). The starter's base-model evaluation is skipped (never used; its replies were cut short), so
  only the tuned model is sampled. Nothing else changes.

## Judge v7 cancelled before any letter (Sun 1 Nov 2026)

v7 was pre-registered (7290b31, 89f466d) and then cancelled before any v7 letter, edit, label or run (two trial calls,
about $0.02). A pre-run review found: (1) the code check alone, given to Muse Spark too, ties the open ensemble on v6
(19 vs 19); (2) at the planned size the test had about 30-54% power, and 80% needs about 4,500 rows, beyond the
credit left; (3) v6's edge came almost entirely from a row family we created and trained on (slip edits, 16 vs 0); on
all other rows Muse Spark led 21 vs 17. Running it could only produce a weak or misleading claim, so v6 stays the
last judge run, as first pre-registered.

## Judge v6 served from a deployment (Mon 2 Nov 2026, 08:04-08:16 IST; a replication, not a new test)

The v6 adapter (`muse-starter-sl-judge-v6-main`) was deployed once on Fireworks (1 x H200, BF16 live merge), every one
of the 1,545 v6 holdout prompts was sent as the training session sent it (one user message, temperature 0, 256
tokens), and the deployment was deleted. Labels unchanged (frozen in d2dbb29 and 881dbf0). Served vs training session:
same verdict on 1,499 of 1,501 test rows; 1,442 right either way; vs Spark Open 82 vs 43 (p 0.00062), vs Muse Spark
32 vs 57 (p 0.011), as in the v6 result. Every reply finished (1,545 of 1,545 "stop"). Public bench through
`pack.py`'s judge path: 21 of 23 lies, 0 of 8 false alarms. Record: `provenance/glimmer-judge-lora-v6/live/`.

## The gate recording: hand-held, stabilized before analysis (Mon 2 Nov 2026, 17:53 IST, before any analysis run)

Written before `analyze.py`, `monday.py` or any model call touches the gate footage.
- **What was filmed:** `VID20261102153251.mp4` (OPPO F25 Pro, 1x lens, 1920x1080 HEVC, 1,002 s, file start 15:32:51
  IST by its name). Dismissal bell 15:30 (the filmer's note). Filmed from the highway above the retaining wall,
  camera 8.3 m above the road. **Hand-held over the railing** (the filmer did not leave a phone on a highway parapet),
  so filmcheck's steadiness check fails: the view moves 20-36 px (of 640) throughout.
- **Fix, decided now:** `stabilize.py` maps every frame onto the frame at 300 s by a RANSAC homography (SIFT), which is
  exact for a camera that only turns in place over a flat road; frames with under 40 inliers reuse the previous
  frame's homography and are logged (`gate-stable.mp4.stab.json`). Analysis runs on the stabilized file.
- **Calibration:** the taped rectangle N1-N2-F2-F1, 8 m along the road x 7 m across (filmer's sheet), clicked on the
  stabilized 300 s frame (F2 from a late frame, after a parked car left it). **Held out:** lines A and B, 15 m apart
  (3.5 m beyond each end of the rectangle); G2 passes at 12.75-17.25 m as before. The wall-side strip (2.20 m at A,
  1.90 m at B) is not a calibration input.
- **Window:** the rule's [B-2 min, B+13 min] = 15:28-15:43 starts before the file does; analysed: from the first
  frame that registers (inliers >= 40 for 10 s running, about 1:30 into the file) to 15:43:00, about 550 s, under the
  900 s target. Reported as recorded, not extended.
- **If G2 fails** on the stabilized file, its numbers are not used for the letter and the page says why.

## The gate run: two disputed events checked by eye; analysis kept to the taped stretch (Mon 2 Nov 2026, 18:40 IST)

First run on the stabilized file (`out/gate`, SAM $12.34 incl. images): 108 events, 30 kept after Muse Spark's review
(21 serious, 9 close passes); the case agent read line A to line B as 15.0 m (tape 15 m). The run's "check by eye"
list named two review_disputed people (kept by the walking-pace rule although Spark said "not a person"): c153 at
122.1 s and c530 at 375.5 s. **By eye, both are not people:** their boxes sit on the stabilized frame's right edge,
in the black border and the sliver beside it, and c153 is the path of the very motorcycle it "met" (event 1's clip).
Both lie outside the taped stretch (x = -0.6 and -1.2 m, beyond line A). **Decision, made before the next run:** set
`zone_m` to the taped stretch, x 0-15 m (line A to line B) by y 0-7 m (edge to edge), where the held-out 15 m check
held; nothing outside it is reported. This removes 14 of the 30 kept events (both disputed ones; 5 beyond line A at
the frame edge; 7 beyond line B, where the far end is extrapolated). It can only lower the counts. SAM replies are
reused from the cache ($0); the letter and judges run again.

## The gate run: one track ruled out by eye (Mon 2 Nov 2026, 18:45 IST)

Second run (taped stretch only): 9 kept events, 5 serious, 4 close passes. By eye on the evidence clips (events 2, 4
and 5), **piece c116/0 is not a pedestrian**: its box rides inside the moving motorcycle's and auto rickshaw's boxes
frame after frame and covers about 10 m in about 2 s, so it is someone on or in those vehicles (Spark judged one crop
of it, where it looked like someone standing). Its 3 serious and 1 close-pass events are removed through a new site
key, `by_eye_not_pedestrians: ["c116/0"]` (analyze.py marks that piece "not a pedestrian, by eye"). c483/0 (events 1
and 3), c169/0 and c589/0 walk across on foot in their clips and stay. Decided before the next run; it only lowers
the counts.

**The certified letter's 80 (note added Tue 3 Nov 2026).** The letter's "measured 80 pedestrian crossings" counts
tracked crossings before Muse Spark's review; 51 were people on foot. `pack.py` is fixed for future letters; the
certified letter stays as written.

## Tuned judge v6 on a free Kaggle GPU (pre-registered Wed 4 Nov 2026, 05:09 IST, before the run)

- **What:** the v6 adapter as Fireworks let us download it on 4 Nov 2026 (`adapter_model-00001-of-00001.safetensors`,
  sha256 `1a1f9c6a…`; `adapter_config.json`, `b4ea83e7…`), converted to GGUF by llama.cpp `b11976` and run over Meta's
  4-bit Glimmer base on Kaggle's free 2 x T4 (`kaggle/glimmer-judge-lora.ipynb`). No new training and no new labels:
  this replays v6, the last judge trained, on other hardware.
- **Primary:** on v6's 1,501 test rows, scored with the labels frozen on 1 Nov, the Kaggle judge against Muse Spark
  Open's saved replies, on the rows where exactly one is right: exact two-sided sign test, a win at p < 0.05.
- **Reported either way:** rows right; rows with the same verdict as the Fireworks deployment's replay
  (`predictions_served.jsonl`); the public bench through `judge_bench.py`; 6 reads of our gate letter on the 3 Nov
  prompt and 6 on today's.
- **Stops:** a failed conversion or a chat template that does not match training means not run. If the 7-hour wall
  cap ends the replay early, the replayed prefix (holdout order) is scored and its size stated.

## Tuned judge v6 on a free Kaggle GPU: result (Wed 4 Nov 2026, run 05:15-08:52 IST)

- **Primary: met.** No stop fired: the conversion ran, the chat template matched training, and all 1,545 holdout
  prompts were answered (0 errors, the wall cap not reached). On the 1,501 test rows: **1,435 right** (the Fireworks
  deployment 1,442; Muse Spark Open 1,403; Muse Spark 1,467). Against Muse Spark Open, **81 vs 49, p 0.0063**: a win.
  Against Muse Spark, 32 vs 64, p 0.0014: Muse Spark stays ahead.
- **Same verdict as the Fireworks deployment** on 1,492 of 1,501 rows; of the 9 that differ, the deployment is right
  on 8. Lies flagged 948 of 1,006 (deployment 954); clean rows flagged 8 of 495 (deployment 7). Our reading: the cost
  of Meta's 4-bit base in llama.cpp against Fireworks' serving.
- **Public bench** (`judge_bench.py`, 31 letters): 21 of 23 planted lies, 0 of 8 false alarms, 4.3 s a reply.
- **Our gate letter:** on the 3 Nov prompt, 6 of 6 reads (3 plain, 3 with the JSON schema) found no problem, as the
  deployment did on 3 Nov. On today's prompt (`pack.py` after 17b42a8, which counts 51 people), 6 of 6 reads named
  one problem, the same each time: the letter's "measured 80 pedestrian crossings" against the measurements' 51. That
  is the certified letter's known mismatch ("The certified letter's 80", above); the judge was not told of it.
- **Time and cost:** 1,545 verdicts in 2 h 58 min (4 at a time, median 26 s each); the whole notebook, llama.cpp build
  included, 3 h 37 min. $0.
- **Files:** `provenance/glimmer-judge-lora-v6/kaggle/`: every reply (`predictions_kaggle.jsonl`), `score.json`, the run record
  (`glimmer-judge-lora-provenance.json`: the adapter's, the GGUF's and the base's sha256, llama.cpp `b11976` = commit
  `2e0d86b`, code at git `394a797`), the gate reads, the bench and Kaggle's run log (`kaggle-run.log`). LoRA GGUF
  sha256 `bafc1117805a6918659d7c821e3c8e4ad2f809438e4aed3b04e44053958edd66`. Re-score at $0:
  `python3 provenance/glimmer-judge-lora-v6/kaggle/score_kaggle.py provenance/glimmer-judge-lora-v6/kaggle/predictions_kaggle.jsonl`.

## Log

- Edited Thu 29 Oct 2026, before the rehearsal or the main recording was filmed: wording and references only; no
  number, date or condition changed. Reviews are named as AI-assisted code reviews (their defect counts kept, the
  reviewer head-counts dropped), internal rank numbers and file names are gone, and "the last section" links name
  their section.
- Thu 29 Oct 2026, after the G7 rule above was written: the page began computing G7's mark from its own k, V and n
  with `passmark.py`, by the same one-sided Fisher exact test and the same p ≤ 0.05 comparator. It shows no "after"
  result. The G7 text is unchanged.
- Thu 29 Oct 2026, before the rehearsal or the main recording was filmed: a "Verdict now" table added under the
  pre-registered one, and the README's first screen links to it. No pre-registered text changed.
- Thu 29 Oct 2026, night: the three status sections were headed by times of day (evening, late night, early 29 Oct), but git shows all three arrived in the first commit, 91b8c9b, at 19:19 IST on Wed 28 Oct, so they are now headed first, second and third pass, written before that commit. Their text is unchanged.
- Sun 1 Nov 2026, 11:05 IST: "Verdict now" got a new last-updated date, G4's evidence cell and a dated note on the due
  dates that move to Mon 2 Nov; a dated note on what v4's Muse Spark comparison rests on was added after the v4 result.
  No pre-registered text changed.
- Tue 3 Nov 2026: the README's technical sections moved, headings unchanged, to TECHNICAL.md; earlier references to a
  README section now mean that section in TECHNICAL.md. No pre-registered text changed.
- Wed 4 Nov 2026, 09:10 IST: the Kaggle v6 pre-registration's time corrected from 05:40 to 05:09 IST. The text was
  saved at 05:09 IST and the run started at 05:15 IST (the notebook's nvidia-smi stamp, 23:45:32 UTC); 05:40 was a
  slip. The notebook's own copy of the pass bar, in the Kaggle version pushed at 05:15 IST, still says 05:40. No
  pre-registered text changed.
- Wed 4 Nov 2026, 15:40 IST: four times written on Mon 2 Nov were set to the commit times git shows for them ("Last
  updated" 20:15 -> 18:57; the recording note 18:00 -> 17:53; the two by-eye notes 19:10 -> 18:40 and 19:40 -> 18:45).
  Each was written before or at its commit; no pre-registered text changed.
