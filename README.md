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
| Track every pedestrian and vehicle through the video | **SAM 3.1** (one concept per request: person, car, motorcycle, auto rickshaw...) | `sam.py` |
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
open calibrate.html                      # mark a measured rectangle on a frame, download site.json
python3 analyze.py VIDEO site.json       # tracks, near-misses, clips, Spark review -> out/VIDEO/events.json
python3 pack.py out/VIDEO site.json      # letter, fix image, evidence page -> out/VIDEO/index.html
python3 test_cw.py                       # self-checks
```

SAM replies are cached per output folder, so re-running costs nothing. An output folder refuses a different video.
Long recordings (for example an hour of a school's CCTV) are sent to SAM in 5-minute parts. The SAM cost is
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

`validate_dut.py` runs the whole pipeline (SAM 3.1, metres, near-misses, Muse Spark) on drone clips of a campus
crosswalk full of students (DUT dataset, top-down view). It then matches each of our conflicts to the dataset's own
tracked people and cars.

| Clip | True conflicts | We found (same person and car) | Missed | False alarms |
|---|---|---|---|---|
| 15 | 8 | 6 | 2 | 0 |
| 01 | 2 | 0 | 2 | 0 |
| 03 | 0 | 0 | 0 | 0 |
| **All** | **10** | **6** | **4** | **0** |

- **Tracking:** SAM's pedestrian positions were 2–16 cm from the dataset's.
- **Errors on matched events:** speed within ±0.8 km/h; PET 0–1.4 s off (mean 0.7 s).
- **Why 4 were missed:** 2 people were not yet tracked in the first 0.4 s of a clip. 2 had the car measured at
  9.5 km/h against the dataset's 10.5 km/h, just under our pre-set 10 km/h "moving" threshold. We did not move the
  threshold to fit the test.
- **What this run changed:** Spark at first rejected 4 real students as "not a person", because they were a few
  pixels wide and half hidden by the car. It now judges a zoomed crop of the frame where each person is clearest.
  Boxes on empty road, a pole and part of a car are still rejected.
- **Caveats:** this is a small sample (10 events). The true conflicts assume a 4.6 x 1.8 m car (DUT gives only the
  car's centre and heading). The view is top-down, not a phone at an angle.

The DUT data has no licence and was used only for internal testing; it is not included.

## Limits, stated

- A vehicle's lower box edge stands in for its footprint.
- SAM 3.1 tracks up to 16 objects per frame per concept, so dense crowds are undercounted. The tool is for crossings, not crowds.
- The death-risk curve is for adults (15+) hit by a car front; children are not covered by that study.
- Distances are only as good as the measured calibration rectangle.
- In long recordings sent to SAM in 5-minute parts, a person or vehicle crossing a part boundary gets a new ID, so
  exposure counts (and rarely an event) can be counted twice at the boundaries.
- Box jitter alone gives a queued car an apparent speed of a few km/h. That is well under the 10 km/h "moving"
  threshold, so it does not create events, but very slow vehicles are not measured precisely.

## Sources

- Rosén E, Sander U (2009). Pedestrian fatality risk as a function of car impact speed. *Accident Analysis & Prevention* 41(3):536–542. doi:10.1016/j.aap.2009.02.002
- Allen BL, Shin BT, Cooper PJ (1978). Analysis of traffic conflicts and collisions. *Transportation Research Record* 667:67–74. (post-encroachment time)
- Tefft BC (2013). Impact speed and a pedestrian's risk of severe injury or death. *Accident Analysis & Prevention* 50:871–878. doi:10.1016/j.aap.2012.07.022 (checked; higher risks than Rosén & Sander, which we use to avoid overstating)

## Declarations

All code in this repository was written during the hackathon. No third-party code or libraries; Python standard
library and ffmpeg only. Test videos from YouTube were used only for local testing and are not included. The SinD sample (SOTIF-AVLab, non-commercial use) was used only for validation and is not included.
