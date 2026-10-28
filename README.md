# Crossing Watch

Near-miss evidence for a dangerous crossing, from one phone video.

Put a phone somewhere high (a first-floor window, a wall) looking at the crossing outside a school, record the
pick-up rush, and Crossing Watch finds every moment a moving vehicle and a pedestrian were on the same spot less
than 1.5 seconds apart. It measures the vehicle's speed, the adult death risk had they collided, and what a
20 or 30 km/h limit would have changed. The output is an evidence pack a principal can send to the road authority:
clips, numbers, a proposed fix drawn onto the real street, and a ready letter. That is proof before a child is
hit, instead of waiting for crash statistics.

## How it works

| Step | Model or method | File |
|---|---|---|
| Track every pedestrian and vehicle through the video | **SAM 3.1** (one concept per request: person, car, motorcycle, auto rickshaw...); in crowds, SAM image detection 5 times a second plus our tracker | `sam.py`, `crowd.py` |
| Pixels to metres on the road | 4-point homography from a rectangle marked on the road | `road.py`, `calibrate.html` |
| Clean the tracks | Drop riders inside vehicle boxes, split tracks where the ID jumps, ignore static objects, cut-off boxes and teleport speeds | `road.py` |
| Near-miss | Post-encroachment time (PET) under 1.5 s, within 1 m, vehicle over 10 km/h | `road.py` |
| Severity | Adult death risk at that speed, Rosén & Sander (2009); replay under 30 and 20 km/h limits | `road.py` |
| Second look | **Muse Spark** checks each clip: is that a person, and who (child, elderly, wheelchair user...) | `review.py` |
| Ear witness | **Muse Wonder** listens to the original audio around each near-miss for horns, screeching brakes and shouts | `listen.py` |
| Evidence clips | ffmpeg, pedestrian boxed cyan, vehicle red, every person's head blurred so clips of children can be shared | `render.py` |
| Fix and letter | **Muse Spark** picks a physical fix and writes the letter from the measurements only; **Muse Image** draws the fix onto the real street | `pack.py` |

## Run

Needs Python 3.11+ and ffmpeg. No other dependencies. Put `MODEL_API_KEY=...` (Meta Model API) in `.env`.

```
open calibrate.html                      # tape-measured rectangle, or no tape: match 4 points to a satellite view
python3 analyze.py VIDEO site.json       # tracks, near-misses, clips, Spark review -> out/VIDEO/events.json
python3 pack.py out/VIDEO site.json      # letter, fix image, evidence page -> out/VIDEO/index.html
python3 test_cw.py                       # self-checks
```

SAM replies are cached per output folder, so re-running costs nothing. An output folder refuses a different video.
Long recordings (for example an hour of a school's CCTV) are sent to SAM in 5-minute parts that overlap by
2 s, so a person crossing a cut keeps one ID. For crowds, set `"person_grid": 2` in the site file: people are
tracked in 4 overlapping tiles (SAM returns at most 16 objects per request) and joined where the tiles meet. The SAM cost is
estimated first, and a run over $10 needs `--allow-cost`.

## Validation on ground-truth trajectories

`validate_sind.py` runs the near-miss maths on the SinD public sample: 20 minutes of drone-measured trajectories in
metres at a busy Tianjin intersection, 63 pedestrian crossings and 556 moving vehicles (cars, motorcycles, bicycles,
tricycles, buses, trucks). It needs no Meta API.

- **Speed:** ours, from positions, against SinD's own velocity: mean error 0.26 km/h, 95th percentile 0.96 km/h.
- **PET:** 65 conflicts under 3 s (42 serious). An independent textbook PET over a conflict area (Allen et al.
  1978) agrees within 0.5 s on 51 of 65 and gives the same tier on 56. In every disagreement the area method gives
  the lower PET, because its conflict area is broader, so ours errs on the side of not overstating.
- **Pairs only the textbook flagged:** 9, and each was checked. 2 were stopped cars beside a person; we exclude
  vehicles under 10 km/h on purpose. 4 never came within 3 m at the same moment, an artefact of the broad area.
  3 were cycles under 10 km/h passing 1.2–1.6 m away, at our thresholds' edge.
- **Speed of the search:** the grid index searches 20 minutes of mixed traffic in under a second.

This checks the measurement layer on true positions.

### End to end, against ground truth (DUT)

`validate_dut.py` runs the whole pipeline (SAM 3.1, metres, near-misses, Muse Spark) on 8 drone clips of a campus
crosswalk full of students (DUT dataset, top-down view, 11 to 113 people per clip). It then matches each of our
conflicts to the dataset's own tracked people and cars by identity: same person, same car.

SAM 3.1 tracks at most 16 objects per frame in a video, but on a single image it returns every match (71 people on
one crowded frame). So **crowd mode** (`"person_mode": "crowd"`) has SAM detect people on images 5 times a second.
`crowd.py` then keeps their IDs with a small tracker: constant-velocity prediction, a match within one body size,
and a 1 s grace period for people hidden behind others.

| Clips | People per clip | Mode | True conflicts | Found | Missed (at a threshold) | False alarms (at a threshold) |
|---|---|---|---|---|---|---|
| 04 09 10 12 (crowded) | 24–113 | video, whole frame | 25 | 7 | 18 (2) | 0 (0) |
| | | video, 2 x 2 tiles | 25 | 10 | 15 (3) | 11 (7) |
| | | **crowd mode** | 25 | **21** | 4 (4) | 10 (8) |
| 15 01 03 16 (held out) | 11–21 | video, whole frame | 11 | 7 | 4 (2) | 0 (0) |
| | | **crowd mode** | 11 | 8 | 3 (3) | 1 (1) |

The crowd tracker rule was fixed once from walking speed versus body size. The four held-out clips were not used
to set it.

- **Crowd mode over all 8 clips:** 29 of 36 conflicts found. Every miss is a threshold case, and 2 of the 11 false
  alarms are not.
- **What the 2 real false alarms are** (both clip 09, checked frame by frame): one is a real person in yellow whom
  the dataset stops tracking after 1.8 s while they keep walking along the kerb, so it may be a gap in the ground
  truth. The other is a person standing still at the road edge for the whole clip; the dataset does not label them.
  Dropping standing people would also drop a true conflict in clip 12, so they stay.
- **ID fragmentation:** across the 8 clips the dataset's 301 pedestrians are followed by our tracks for 297 of them,
  with a median of 1 track per pedestrian (at most 5).
- **"At a threshold" defined:** a disagreement the other side also finds once each threshold is widened by about our
  measured error (speed ±1.5 km/h around the 10 km/h "moving" bar, gap +0.3 m, PET +0.3 s). For example, a car the
  dataset has at 8.6 km/h and we measured at 10.1 km/h.
- **Accuracy on matched events:** speed is usually within 1 km/h (2 km/h at worst). PET is within about 1 s.
- **Spark review:** it judges a zoomed crop of each person's clearest frame. A full-frame snapshot had rejected real
  students who were a few pixels wide.
- **Caveats:** this is still a small sample. The true conflicts assume a 4.6 x 1.8 m car (DUT gives only centre and
  heading). The view is top-down, not a phone at an angle. Meta's per-image price was not found; cost estimates
  use $0.002 per image.

The DUT data has no licence and was used only for internal testing; it is not included.

## Limits, stated

- A vehicle's lower box edge stands in for its footprint.
- SAM 3.1 video tracking keeps up to 16 objects per frame per concept, so crowded sites need crowd mode, which costs
  more (one image request per 0.2 s).
- A person standing still on the carriageway when a car passes within 1 m is reported as a near-miss.
- The death-risk curve is for adults (15+) hit by a car front; children are not covered by that study.
- Distances are only as good as the measured calibration rectangle.
- Box jitter alone gives a queued car an apparent speed of a few km/h. That is well under the 10 km/h "moving"
  threshold, so it does not create events, but very slow vehicles are not measured precisely.

## Sources

- Rosén E, Sander U (2009). Pedestrian fatality risk as a function of car impact speed. *Accident Analysis & Prevention* 41(3):536–542. doi:10.1016/j.aap.2009.02.002
- Allen BL, Shin BT, Cooper PJ (1978). Analysis of traffic conflicts and collisions. *Transportation Research Record* 667:67–74. (post-encroachment time)
- Tefft BC (2013). Impact speed and a pedestrian's risk of severe injury or death. *Accident Analysis & Prevention* 50:871–878. doi:10.1016/j.aap.2012.07.022 (checked; higher risks than Rosén & Sander, which we use to avoid overstating)

## Declarations

All code in this repository was written during the hackathon. No third-party code or libraries; Python standard
library and ffmpeg only. Test videos from YouTube were used only for local testing and are not included. The SinD sample (SOTIF-AVLab, non-commercial use) was used only for validation and is not included.
