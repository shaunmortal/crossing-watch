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
| Numbers road engineers use | Pedestrians and vehicles an hour, PV² (IRC:103-2012), 85th-percentile speed, and gaps in traffic of 6 s and 12 s where people actually crossed (UK Traffic Signs Manual ch. 6) | `road.py`, `pack.py` |
| Second look | **Muse Spark** checks each clip: is that a person, and who (child, elderly, wheelchair user...) | `review.py` |
| Ear witness | **Muse Wonder** listens to the original audio around each near-miss for horns, screeching brakes and shouts | `listen.py` |
| Where it happened | A bird's-eye map in road metres: each near-miss where it happened, with both paths 2 s either side | `roadmap.py` |
| Evidence clips | ffmpeg, pedestrian boxed cyan, vehicle red, every tracked person's head blurred on every frame so clips of children can be shared | `render.py` |
| Fix and letter | **Muse Spark** (JSON mode) picks a physical fix and writes the letter from the measurements only; verified in two layers before use: code checks every number against the measurements, then **Muse Spark as a separate reviewer** (LLM as judge) lists unsupported claims (a warrant said to be met, a death risk for a child); either objection sends the letter back with the reason, and after 3 tries what remains is shown for a person to check; **Muse Image** draws the fix onto the real street | `pack.py` |

## Run

Needs Python 3.11+ and ffmpeg. No other dependencies. Put `MODEL_API_KEY=...` (Meta Model API) in `.env`.

```
open calibrate.html                      # tape-measured rectangle, or no tape: match 4 points to a satellite view
python3 analyze.py VIDEO site.json       # tracks, near-misses, clips, Spark review -> out/VIDEO/events.json
python3 pack.py out/VIDEO site.json      # letter, fix image, evidence page -> out/VIDEO/index.html
python3 test_cw.py                       # self-checks
```

SAM replies are cached per output folder, so re-running costs nothing. An output folder refuses a different video.
Videos are sent to SAM in 15-second parts that overlap by 2 s, so a person crossing a cut keeps one ID. Parts are
short because one SAM 3.1 video request tracks at most 16 objects **in all**: once 16 IDs are taken, later arrivals
are never picked up (none of 54 replies had more, and none gained an ID after filling). Any request that still hits
the limit is counted, and the page says its counts are a minimum. For crowds, set `"person_grid": 2` in the site file: people are
tracked in 4 overlapping tiles (SAM returns at most 16 objects per request) and joined where the tiles meet. The SAM cost is
estimated first at Meta's list prices: a run over $10 needs `--allow-cost`, and `--budget USD` is a hard cap that
nothing lifts. With `"person_mode": "auto"` or `"vehicle_mode": "auto"`, a concept goes to SAM video first; if a part
fills its 16 objects before the next part takes over, that concept is detected frame by frame instead and the page
says when it filled (on the Indian clip: "person: 16 objects taken within 1.0-1.6 s in 3 of 3 parts").

### Open weights: Muse Glimmer writes the letter

Set `LETTER_MODEL_URL` to any OpenAI-compatible server and the fix and letter come from that model instead of Muse
Spark, with the same number check. `<removed-run-record>` runs Meta's official 4-bit **Muse Glimmer 30B**
(`meta-models/Muse-Glimmer-30B-GGUF`, Apache 2.0) with llama.cpp on Kaggle's free 2 x T4, shows it the blurred
street photo when there is one, and writes the evidence page. Run end to end twice on Kaggle's 2 x T4 with the
synthetic sample: both times Glimmer proposed a raised zebra crossing and wrote a letter whose every number passed
the code check, in 627 s and 592 s (Muse Spark: about 20 s). The committed run's log and Glimmer's text are in
[`<removed-run-record>`](<removed-run-record>). Its letter was correct but stiff, so Muse Spark stays the default writer.
`sample/` is a synthetic example (made-up tracks, no video) for trying the letter step anywhere.

```
LETTER_MODEL_URL=http://127.0.0.1:8080/v1 python3 pack.py out/VIDEO site.json
```

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

SAM 3.1 tracks at most 16 objects per video request, but on a single image it returns every match (71 people on
one crowded frame). So **crowd mode** (`"person_mode": "crowd"`) has SAM detect people on images 5 times a second.
`crowd.py` then keeps their IDs with a small tracker: constant-velocity prediction, a match within one body size,
and a 1 s grace period for people hidden behind others.

Every DUT number here was re-scored on 29 Oct with today's code, at $0, from the cached SAM replies and Spark's
stored verdicts: `python3 validate_offline.py DUT_REPO out/dut-15s out/dut-vcrowd` (the video rows: the 28 Oct
folder with `--site '{"person_mode": "video", "person_grid": 1}'`, or 2 for tiles). The speed fix below moved the
ground truth too: the dataset's own tracks now give 52 conflicts, not 36 (GATES.md, 29 Oct, shows old and new side
by side). Found by the geometry, before Spark's review:

| Clips | People per clip | Mode | True conflicts | Found | Missed (at a threshold) | False alarms (at a threshold) |
|---|---|---|---|---|---|---|
| 04 09 10 12 (crowded) | 24–113 | video, whole frame | 37 | 9 | 28 (1) | 1 (1) |
| | | video, 2 x 2 tiles | 37 | 19 | 18 (1) | 7 (2) |
| | | **crowd mode** | 37 | **34** | 3 (3) | 5 (1) |
| 15 01 03 16 (held out) | 11–21 | video, whole frame | 15 | 13 | 2 (0) | 0 (0) |
| | | **crowd mode** | 15 | **15** | 0 (0) | 1 (1) |

The video rows are the 28 Oct runs, one SAM request per clip; Spark's verdicts for them were not kept.
The crowd tracker rule was fixed once from walking speed versus body size. The four held-out clips were not used
to set it.

- **Crowd mode over all 8 clips:** the geometry finds 49 of 52 conflicts, every miss a threshold case; 4 of its 6
  false alarms are not. After Spark's review: 44 of 52 found, 3 real false alarms. Spark called 5 pedestrians in
  true conflicts "not a person". 8 events come from track pieces Spark has not seen yet (new with today's code); they
  stay in, as unreviewed events do on the page. If Spark rejected all of them it would be 37 of 52.
- **Vehicles in crowd mode too** (`"vehicle_mode": "crowd"`, for dense traffic that fills SAM's 16 objects). Vehicles
  are detected on every frame (10 a second): at 5 a second a review showed motorcycles over ~36 km/h outran the
  tracker's one-body-size match and vanished. The geometry finds 48 of 52, all 4 misses at a threshold. After
  Spark's review: 45 of 52 found and 4 real false alarms; Spark called 3 pedestrians in true conflicts "unclear", and
  17 events come from pieces it has not seen (30 of 52 if it rejected them all).
- **Spark's rider calls:** Spark called walking students "rider" or "cyclist", though DUT tracks no bikes. In vehicle
  crowd mode that cost 17 true conflicts (28 of 52 found). So a rider call now stands only when SAM finds a
  motorcycle, bicycle, scooter or auto rickshaw box under the person (`review.gated`); otherwise they stay a
  pedestrian, and the card says Spark thought "rider" and gives their measured walking speed. Pedestrian pieces
  shorter than 1 s are also dropped.
- **Speed** against the dataset's positions at their own 23.976 fps (vehicle crowd mode, 2,079 frames): mean error
  0.16 km/h, 95th percentile 0.55 km/h. The old median of frame-to-frame steps read a 24 fps source slow (0.83 x in
  the self-check): 0.52 and 1.89 km/h. DUT's cars crawl at about 10 km/h, right on the "moving" bar, so this decides
  which conflicts exist: of the frames with the car at 7–13 km/h, 7.5% still land on the wrong side of the bar (28%
  before).
- **Dense Indian intersection** (39 s, no ground truth, calibration guessed): SAM video saw on average 1.6 people and
  6 vehicles a frame, crowd mode 14.9 people and 20 vehicles. Before the fixes above it reported 543 serious
  near-misses, nearly all one-frame track fragments and riders; re-scored from its cache, 10 events survive Spark's
  review (5 serious; 2 from pieces Spark has not seen). Speeds there are not trustworthy (up to 57 km/h) because
  nothing was measured on that road.
- **What the real false alarms are:** two are in clip 09 and were checked frame by frame on 28 Oct. One is a real
  person in yellow whom the dataset stops tracking after 1.8 s while they keep walking along the kerb, so it may be a
  gap in the ground truth. The other is a person standing still at the road edge for the whole clip; the dataset
  does not label them. Dropping standing people would also drop a true conflict in clip 12, so they stay. The third,
  a close pass in clip 10, is not checked yet. Vehicle crowd mode adds a fourth in clip 09: someone Spark called a
  rider, kept by the rider gate because DUT tracks no bikes, so none can be found under anyone.
- **ID fragmentation:** across the 8 clips the dataset's 301 pedestrians are followed by our tracks for 296 of them,
  with a median of 1 track per pedestrian (at most 4).
- **"At a threshold" defined:** a disagreement the other side also finds once each threshold is widened by about our
  measured error (speed ±1.5 km/h around the 10 km/h "moving" bar, gap +0.3 m, PET +0.3 s). For example, a car the
  dataset has at 10.1 km/h and we measured at 10.0 km/h.
- **Accuracy on matched events** (crowd mode): speed within 1 km/h on 41 of 44 (2.0 km/h at worst); PET within 1 s
  on 38 of 44 (2.5 s at worst).
- **Spark review:** it judges a zoomed crop of each person's clearest frame. A full-frame snapshot had rejected real
  students who were a few pixels wide.
- **Caveats:** this is still a small sample. The true conflicts assume a 4.6 x 1.8 m car (DUT gives only centre and
  heading). The view is top-down, not a phone at an angle. Meta's per-image price was not found; cost estimates
  use $0.002 per image.

- **Engineering numbers against ground truth** (crowd mode; same definitions applied to the dataset's own tracks):
  - Moving vehicles counted: right on 8 of 8 clips.
  - Gaps of 6 s or more where people crossed: right on 8 of 8.
  - Longest gap: within 0.5 s on 6 of 8.
  - Pedestrian crossings: ours run high, 374 against 280 (1.3x), because a broken track counts a person twice. PV²
    scales with this count, so the page says so.

The DUT data has no licence and was used only for internal testing; it is not included.

## Limits, stated

- A vehicle's lower box edge stands in for its footprint.
- SAM 3.1 video tracking keeps at most 16 objects per request, so crowded sites need crowd mode, which costs more
  (one image request per 0.2 s). Dense traffic fills even a 15-second part: on our Indian intersection clip every
  vehicle concept hit the limit within 2 s, so there vehicle counts are a minimum. People SAM did not track are also
  not blurred.
- A person standing still on the carriageway when a car passes within 1 m is reported as a near-miss.
- The death-risk curve is for adults (15+) hit by a car front; children are not covered by that study.
- Distances are only as good as the measured calibration rectangle.
- Rates per hour from a short video are scaled, not a peak-hour count; the page says so next to PV², and shows no
  PV² for videos under 15 minutes.
- SAM video tracking at 10 frames a second costs $0.20 per 1,000 frames per concept at Meta's list price, so an hour
  with four concepts is about $33 (the 2 s overlaps between parts are billed too). Frame-by-frame detection costs
  $2.50 per 1,000 images: about $79 for 15 minutes of people and three vehicle concepts, about $34 with the single
  concept "vehicle". The page prints the SAM cost of each pack.
- Box jitter alone gives a queued car an apparent speed of a few km/h. That is well under the 10 km/h "moving"
  threshold, so it does not create events, but very slow vehicles are not measured precisely.

## Sources

- Rosén E, Sander U (2009). Pedestrian fatality risk as a function of car impact speed. *Accident Analysis & Prevention* 41(3):536–542. doi:10.1016/j.aap.2009.02.002
- Allen BL, Shin BT, Cooper PJ (1978). Analysis of traffic conflicts and collisions. *Transportation Research Record* 667:67–74. (post-encroachment time)
- Indian Roads Congress, IRC:103-2012, Guidelines for Pedestrian Facilities, clause 6.7.4.1.2 (PV²).
- UK Department for Transport (2019), Traffic Signs Manual chapter 6, section 13.5 (gaps in traffic).
- Tefft BC (2013). Impact speed and a pedestrian's risk of severe injury or death. *Accident Analysis & Prevention* 50:871–878. doi:10.1016/j.aap.2012.07.022 (checked; higher risks than Rosén & Sander, which we use to avoid overstating)

## Declarations

All code in this repository was written during the hackathon. The check-then-retry pattern for Spark's letter and the
JSON-mode request field follow Meta's legal-agent workshop (github.com/meta-models/legal-agent-workshop, shown at a
hackathon session); no code was copied from it. No third-party code or libraries; Python standard
library and ffmpeg only. Test videos from YouTube were used only for local testing and are not included. The SinD sample (SOTIF-AVLab, non-commercial use) was used only for validation and is not included.
