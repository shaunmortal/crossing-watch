# Crossing Watch: pre-registered gates

Written Wed 28 Oct 2026, before running the full pipeline on real footage. These conditions do not change after results come in.

| Gate | Pass condition | Test footage | Due (IST) |
|---|---|---|---|
| G1 Tracks | SAM 3.1 keeps one ID on each crossing pedestrian for at least 80% of the time they are visible | news CCTV `sites/kids-cctv.json` | passed 28 Oct (2 of 2 crossers, 150/150 frames) |
| G2 Metres | A road distance NOT used for calibration (a second lane width, or crossing-line length) comes out within ±15% of its assumed value | same | Wed 28 Oct 22:00 |
| G3 Conflicts | Checked by eye, at least 2 of the top 3 events are real close passes, and no event involves a parked or queued vehicle | same | Thu 29 Oct 22:00 |
| G4 Own footage | Footage filmed from height at the user's college gate runs end to end, with calibration from measured points | user's video | Sun 1 Nov 22:00 |

**Scope cut if G3 fails:** report the closest approach in metres plus vehicle speed (no PET). The evidence pack and letter still ship.

**Known limits (stated, not hidden):** a vehicle's lower box edge stands in for its footprint; up to 16 objects per frame per concept; one concept per SAM request; calibration lengths on the news clip are assumed.

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
  - long videos in 5-minute SAM parts with a cost guard;
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
