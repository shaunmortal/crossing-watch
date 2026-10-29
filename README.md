# Crossing Watch

Near-miss evidence for a dangerous crossing, from one phone video.

Put a phone somewhere high (a first-floor window, a wall) looking at the crossing outside a school, record the
pick-up rush, and Crossing Watch finds every moment a moving vehicle and a pedestrian were on the same spot less
than 1.5 seconds apart. It measures the vehicle's speed, the adult death risk had they collided, and what a
20 or 30 km/h limit would have changed. The output is an evidence pack a principal can send to the road authority:
clips, numbers, a proposed fix drawn onto the real street, and a ready letter. That is proof before a child is
hit, instead of waiting for crash statistics.

## Status

Not filed yet. The pack goes to the road authority by hand on Mon 2 or Tue 3 Nov 2026, in a named person's name.
Its reference number will be added here and in the site file's `"submitted"` key. Only "filed, reference X" is ever
written: whether anything is approved or fixed is for the authority to say, and no resolution date is promised.

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
| One number | Of the people who crossed, how many had a moving vehicle through the same spot within 3 s (and 1.5 s), each person once however many vehicles or track pieces: "k of n crossings (1 in N)", with exact 95% ranges (Clopper-Pearson for the share, Garwood's Poisson range for the count, so 0 seen still reads "up to 3.7"). It is the page's first line and the letter's first fact. With `"school_days"` and `"dismissal_minutes"` in the site file and 15 minutes of video or more, one more line: "If every dismissal is like this one: about X crossings a school year..." | `pack.py`, `road.py` |
| Safety pyramid | The headline's people drawn as a pyramid, not to scale (Laureshyn, Svensson & Hydén 2010): who crossed, within 3 s, within 1.5 s, and collisions at the tip, which nothing here measures: even 0 of n leaves the exact 95% bound ("up to 5.7% of crossings" for SinD's 63), so a short recording never reads as safe | `pack.py` |
| Where it happened | A bird's-eye map in road metres: each near-miss where it happened, with both paths 2 s either side | `roadmap.py` |
| Evidence clips | ffmpeg, pedestrian boxed cyan, vehicle red, every tracked person's head blurred on every frame so clips of children can be shared | `render.py` |
| Fix and letter | **Muse Spark** (JSON mode) picks a physical fix and writes the letter from the measurements only; verified in two layers before use: code checks every number against the measurements (and sends back numbers in words, speeds in mph, and a sentence that puts one near-miss's speed beside another's time gap), then **Muse Spark as a separate reviewer** (LLM as judge) lists unsupported claims (a warrant said to be met, a death risk for a child); either objection sends the letter back with the reason, and after 3 tries what remains is shown for a person to check, and code adds an AI-draft line for a named person to sign; **Muse Image** draws the fix onto the real street (for a raised crossing, code adds the IRC size: 4 m wide, a speed hump 10-20 m before it) | `pack.py`, `ailabel.py` |
| Why the authority can act (India) | With `"country": "IN"` in the site file, code (never a model) quotes the Supreme Court's order of 7 Oct 2025, 2025 INSC 1189: para 35.5 (in school zones, identify high-risk stretches "using accident data") and para 35.11 (an online grievance mechanism that takes "suggestions for pedestrian crossing"), each linked to its page. Para 35.6 is added when the site's `"city"` is one of the 50 in Annexure 46 of MoRTH's Road Accidents in India 2023. The page says near-misses are not accident data | `pack.py` |

## Run

Needs Python 3.11+ and ffmpeg. No other dependencies. Put `MODEL_API_KEY=...` (Meta Model API) in `.env`.

```
open calibrate.html                      # tape-measured rectangle, or no tape: match 4 points to a satellite view
python3 analyze.py VIDEO site.json       # tracks, near-misses, clips, Spark review -> out/VIDEO/events.json
python3 pack.py out/VIDEO site.json      # letter, fix image, evidence page -> out/VIDEO/index.html
python3 pack.py out/VIDEO site.json --notes notes.txt                                  # the principal's notes
python3 pack.py out/VIDEO site.json --approved-by "A. Rao, Principal" --school "..."   # sign the letter as it is
python3 pack.py --verify out/VIDEO/share  # MATCH, CHANGED or MISSING for each shared file
python3 test_cw.py                       # self-checks
```

**Signed and filed.** `pack.py` keeps the fix and letter in `out/VIDEO/plan.json` with the sha256 of the prompt they
came from. A re-run from the same measurements, language and letter model reuses it, and the Muse Image picture of the
same fix: no new Spark or Muse Image call. Other measurements ask for a new letter; to ask again anyway, delete
`plan.json`.

- `--notes FILE` sends the principal's notes back with the letter: "change only the sentences the notes ask for". The
  revised letter goes through both checks again (the legal-agent workshop's "Reject with notes"). The notes reach
  the code check and the judge labelled "stated by the principal, not measured", so the school's own facts (say, its
  number of pupils) are not rejected, and the page then says the letter was drafted from the measurements and the
  principal's notes. Notes can be given more than once.
- `--approved-by` with `--school` writes `signoff.json`: the name, school, date and the sha256 of the exact letter.
  The page fills in "Read and approved by" with them and says how many sentences the notes changed, counted by
  difflib against the first AI draft ("N of M sentences changed after the principal's notes"). If the letter
  changes after that, the page says "changed after sign-off, not signed". Signing asks no model.
- Once the pack is filed, `"submitted": {"to": ..., "channel": ..., "date": ..., "reference": ...}` in the site file
  prints "Filed with {to} on {channel}, {date}: reference {reference}." under the title.
- The page says where it fits in the CDC/FIA school-zone Traffic Conflict Technique toolkit: steps 5-7 (baseline
  counts, pre-intervention conflicts, analysis), without the trained observers step 3 normally needs, with a
  severity that is not the toolkit's observer scales; step 9 is the same film again after the fix.
- Printed, the page keeps light colours even in dark mode, shows only the 3 worst near-misses (a letter number from
  another reads "(clip N, not printed)") and puts the letter on its own sheet.

Filming your own crossing: [`FILMING.md`](FILMING.md) (phone locked at 1080p 30 fps, tape marks, consent notice; `python3 filmcheck.py CLIP` checks the test clip).

`pack.py` also writes `out/VIDEO/share/`: the page and only the files it shows (evidence clips, the blurred street
photo, the Muse Image picture). Publish that folder and nothing else. The unblurred `clip.mp4` and the person crops
Spark looked at never go in, even if a page names them; a self-check proves it.

**Tamper-evident.** `analyze.py` records the SHA-256 of the original video (`source_sha256` in events.json) and the
page prints it. `share/` gets a standard `SHA256SUMS` for every file in it, the page included, so anyone can check a
copy with `shasum -a 256 -c SHA256SUMS`, or `python3 pack.py --verify FOLDER`: MATCH, CHANGED or MISSING per file,
exit status 1 unless all match. For a site in India the page adds one line: Part A of the certificate in the
Schedule to the Bharatiya Sakshya Adhiniyam, 2023 (section 63(4)) asks for these hash values, and the school fills
and signs it. Nothing more is filled in for the school.

**Receipt.** Code writes under "How this was measured" what made the pack: the analysis run's wall-clock minutes and
the SAM requests it sent ("took every SAM reply from cache, so it paid nothing new" on a re-run), how many people
Muse Spark looked at, how many near-misses Muse Wonder listened around, the letter's tries and the Muse Image picture.
Dollars are given for SAM only.

Even the AI picture keeps Meta's made-by-AI tag: Muse Image's .webp is shipped exactly as it came, captioned
"AI-drawn proposal by Muse Image, not a photo", with "AI-generated by Muse Image" on the picture itself. Any image
made from it (a composite, a video still) loses that tag, so `ailabel.burn()` writes the label into its pixels. After
both letter checks, code (not the model) adds: "Drafted by Muse Spark from the measurements in this pack. Read and
approved by: ____ (name, role, date)."

Every number in the letter is one click from its evidence: a number with a unit that equals exactly one shown
near-miss's speed, time gap or death risk links to that near-miss's card, and clicking it plays the clip from the
moment (on paper it reads "(see clip N)"). The letter can be edited on the page before printing; each edit is
re-checked in the browser against the same measurements, and a number that is not there, a number in words or a
speed in mph gets a red underline.

SAM replies are cached per output folder, so re-running costs nothing. An output folder refuses a different video.
Videos are sent to SAM in 15-second parts that overlap by 2 s, so a person crossing a cut keeps one ID. Parts are
short because one SAM 3.1 video request tracks at most 16 objects **in all**: once 16 IDs are taken, later arrivals
are never picked up (none of 54 replies had more, and none gained an ID after filling). Any request that still hits
the limit is counted, and the page says its counts are a minimum. For crowds, set `"person_grid": 2` in the site file: people are
tracked in 4 overlapping tiles (SAM returns at most 16 objects per request) and joined where the tiles meet. The SAM cost is
estimated first, and a run over $10 needs `--allow-cost`.

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

## Checking the checks

**Judge bench: planted lies.** `judge_bench.py` plants one lie at a time in two real letters, Glimmer's v1 letter and
a Muse Spark letter from our cache, and scores each letter check on them: 24 copies with 12 kinds of lie, half of
them kinds the judge's prompt does not name (a near-miss called a collision, "every school day", two near-misses'
speeds swapped...), and 8 clean controls. The 18 added sentences have no digit, and the 2 swaps use only measured
numbers. Run offline today, the code check caught 4 of 24 (the numbers in words and the speeds in mph; Wilson 95%
7-36%) and flagged 0 of 8 controls (0-32%): the rest is the judge's job. Muse Spark and Muse Glimmer as judges are
not run yet; both are Muse models, so neither is an independent judge of Muse letters. A judge reply that cannot be
read is counted on its own, never as a catch. Details in [`GATES.md`](GATES.md).

```
python3 judge_bench.py --out out/judge-bench.json             # build the letters, score the code check
python3 judge_bench.py --out out/judge-bench.json --spark 2   # Muse Spark judges each letter twice (paid)
LETTER_MODEL_URL=http://127.0.0.1:8080/v1 python3 judge_bench.py --out out/judge-bench.json --glimmer 1
```

The bench file keeps every letter and verdict, so a later run only asks for what is missing.

**Blind check (G5).** `blind_set.py` mixes the pipeline's near-misses with decoys (a pedestrian and a moving vehicle
on the same spot 5 to 8 s apart, each pedestrian checked by Spark to be a person), cuts every clip to the same 12 s,
shuffles them and writes a page where a rater picks serious, close, none or can't tell for each, then downloads the
answers. The key stays apart. `score_humans.py` scores each rater against the key as danger vs none: agreement with
its Wilson 95% interval, Cohen's kappa, positive and negative agreement. The pass rule was written in `GATES.md`
before any clip was made. No rater has labelled yet.

```
python3 blind_set.py out/VIDEO site.json --review-decoys   # out/VIDEO/blind/ for the rater, blind-key.json kept
python3 score_humans.py out/VIDEO/blind-key.json answers-*.json
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
- **One number:** 37 of 63 crossings (1 in 1.7) had a moving vehicle through the same spot within 3 s, 25 of 63 (1 in 2.5) within 1.5 s; exact 95% ranges 45.6-71.0% and 27.6-52.8%. The tile it replaced divided conflicts (person-vehicle pairs) by crossings: 65 / 63, "103 per 100 crossings", because a person passed by several vehicles counted once per vehicle.

This checks the measurement layer on true positions.

### End to end, against ground truth (DUT)

`validate_dut.py` runs the whole pipeline (SAM 3.1, metres, near-misses, Muse Spark) on 8 drone clips of a campus
crosswalk full of students (DUT dataset, top-down view, 11 to 113 people per clip). It then matches each of our
conflicts to the dataset's own tracked people and cars by identity: same person, same car.

SAM 3.1 tracks at most 16 objects per video request, but on a single image it returns every match (71 people on
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
  alarms are not. Re-run with 15-second SAM parts and filled crowd boxes: still 29 of 36, all misses at a threshold,
  and 3 of 11 false alarms not at a threshold (one event in clip 10 moved from matched to extra).
- **Vehicles in crowd mode too** (`"vehicle_mode": "crowd"`, for dense traffic that fills SAM's 16 objects). Vehicles
  are detected on every frame (10 a second): at 5 a second a review showed motorcycles over ~36 km/h outran the
  tracker's one-body-size match and vanished. Result: speed bias against the dataset's own velocities fell from
  +0.9 to +0.2 km/h, and 12 of 36 conflicts are found. All 24 misses and 2 of the 3 false alarms are at a threshold:
  DUT's cars crawl at about 10 km/h, right on the "moving" bar, so ±1 km/h decides most of them. (At 5 a second the
  +0.9 km/h bias had pushed those cases over the bar: 35 of 36.) Every conflict clear of a threshold is found. Pedestrian pieces shorter than 1 s are dropped and Spark now calls
  people on motorcycles and bicycles riders; neither changed any DUT result.
- **Dense Indian intersection** (42 s, no ground truth, calibration guessed): SAM video saw on average 1.6 people and
  6 vehicles a frame, crowd mode 14.9 people and 20 vehicles. Before the two fixes above it reported 543 serious
  near-misses, nearly all one-frame track fragments and riders; after them, 18 events survive Spark's review (6
  serious). Speeds there are not trustworthy (up to 88 km/h) because nothing was measured on that road.
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
  heading). The view is top-down, not a phone at an angle. Crowd-mode cost uses Meta's list price for SAM images,
  $2.50 per 1,000.

- **Engineering numbers against ground truth** (same definitions applied to the dataset's own tracks):
  - Moving vehicles counted: right on 8 of 8 clips.
  - Gaps of 6 s or more where people crossed: right on 7 of 8; the other has the car at 10.1 km/h, on the threshold.
  - Longest gap: within 0.5 s on 6 of 8.
  - Pedestrian crossings: ours run high, 374 against 280 (1.3x), because a broken track counts a person twice. PV²
    scales with this count, so the page says so.

The DUT data has no licence and was used only for internal testing; it is not included.

## Scale

| Option | Cost | What it gives |
|---|---|---|
| A funded near-miss study (a 2020 Canadian programme) | about $5,000 per intersection | a full study |
| Telraam S2 window sensor | €199 per sensor | traffic counts, no near-misses |
| Crossing Watch, SAM only, at Meta's list prices | about $4-8 for a 15-minute dismissal (video mode); $34-79 frame by frame for dense crowds | a first screen that tells the authority where to do a full study |

The video-mode range is counted from the cached SAM replies of our two real-street test clips and scaled to 15
minutes, at $0.20 per 1,000 frames billed (at least 50 a request, the 2 s overlaps included): a school crossing on
CCTV with 2 concepts, $0.22 for 48 s; a dense Indian intersection with 4 concepts, $0.34 for 39 s. Frame by frame,
15 minutes is 4,500 images of people plus 9,000 per vehicle concept at $2.50 per 1,000: $34 with the one concept
"vehicle", $79 with three. Muse Spark, Muse Wonder and Muse Image are not in these dollars; the page's receipt counts
their calls, and its cost line gives each pack's own SAM cost. Sources: the
[at-network list thread](https://lists.umanitoba.ca/hyperkitty/list/at-network@lists.umanitoba.ca/thread/IDKSFWIEFDC5N73AYNEDYWW3TFUGMF52/)
and [Telraam's prices](https://telraam.net/en/pricing).

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
- Cost, at Meta's list prices: SAM video $0.20 per 1,000 frames (at least 50 a request), SAM images $2.50 per 1,000,
  Muse Image $0.01 a picture, Muse Wonder $4 per million input tokens and $20 per million output tokens. At 10 frames
  a second in 15 s parts that overlap by 2 s, an hour of video mode with four concepts sends 166,080 frames: about
  $33. Crowd mode costs more: 15 minutes of people at 5 images a second plus three vehicle concepts at 10 a second
  is 31,500 images, about $79. The page prints the SAM cost for each video.
- Box jitter alone gives a queued car an apparent speed of a few km/h. That is well under the 10 km/h "moving"
  threshold, so it does not create events, but very slow vehicles are not measured precisely.

## Sources

- Rosén E, Sander U (2009). Pedestrian fatality risk as a function of car impact speed. *Accident Analysis & Prevention* 41(3):536–542. doi:10.1016/j.aap.2009.02.002
- Allen BL, Shin BT, Cooper PJ (1978). Analysis of traffic conflicts and collisions. *Transportation Research Record* 667:67–74. (post-encroachment time)
- Indian Roads Congress, IRC:103-2012, Guidelines for Pedestrian Facilities, clause 6.7.4.1.2 (PV²). The Union told
  the Supreme Court (order below, para 18) that a Second Revision, IRC 103-2022, exists; the order quotes its
  raised-crossing advice (para 21 and footnote 1), which is where the size given to Muse Image comes from.
- Supreme Court of India, S. Rajaseekaran v. Union of India, Writ Petition (Civil) No. 295 of 2012, reportable order
  of 7 October 2025, 2025 INSC 1189, paras 35.5, 35.6 and 35.11. https://www.livelaw.in/pdf_upload/2037620122025-10-07-624635.pdf
- Ministry of Road Transport and Highways (MoRTH), Road Accidents in India 2023, Annexure 46 (the 50 million-plus
  cities). The morth.nic.in link no longer serves the PDF; mirror: https://data.opencity.in/dataset/road-accidents-in-india-2023
- UK Department for Transport (2019), Traffic Signs Manual chapter 6, section 13.5 (gaps in traffic).
- Traffic Conflict Technique (TCT) toolkit, school zones (CDC/FIA), one-pager:
  https://www.childhealthinitiative.org/media/v5bntgmp/tct-toolkit__one-pager_final_508_updated.pdf
- Laureshyn A, Svensson Å, Hydén C (2010). Evaluation of traffic safety, based on micro-level behavioural data:
  theoretical framework and first implementation. *Accident Analysis & Prevention* 42(6):1637–1646.
  doi:10.1016/j.aap.2010.03.021 (the safety pyramid)
- Bharatiya Sakshya Adhiniyam, 2023, section 63(4) and the certificate in its Schedule (Part A):
  https://www.advocatekhoj.com/library/bareacts/bharatiyaaakshya2023/b.php
- Tefft BC (2013). Impact speed and a pedestrian's risk of severe injury or death. *Accident Analysis & Prevention* 50:871–878. doi:10.1016/j.aap.2012.07.022 (checked; higher risks than Rosén & Sander, which we use to avoid overstating)

## Declarations

All code in this repository was written during the hackathon. The check-then-retry pattern for Spark's letter, the
reject-with-notes revision and the JSON-mode request field follow Meta's legal-agent workshop (github.com/meta-models/legal-agent-workshop, shown at a
hackathon session); no code was copied from it. No third-party code or libraries; Python standard
library and ffmpeg only. Test videos from YouTube were used only for local testing and are not included. The SinD sample (SOTIF-AVLab, non-commercial use) was used only for validation and is not included.
