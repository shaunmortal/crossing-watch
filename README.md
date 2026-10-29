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
| Evidence clips | ffmpeg, SAM silhouettes (boxes where no mask is cached): pedestrian cyan, vehicle red, every tracked person's head and the bottom quarter of every tracked vehicle (its number plate) blurred on every frame so clips of children can be shared; when a SAM video request for people is full, SAM image search finds the people it missed every 0.2 s of every published clip, with boxes filled in between, and the page says how many (check every public frame by eye) | `render.py`, `masks.py`, `analyze.py` |
| The near-miss in one picture | A StroMotion still cut from the blurred clip: copies of the vehicle, then the pedestrian, every 0.5 s (1 s for a car), so wider spacing means faster | `render.py` |
| Hero shot for the video | The blurred clip beside the same frames seen from above in road metres: footsteps, the vehicle's footprint, the 1 m ring and the gap clock. One SVG tile per frame, screenshotted once by headless Chrome, stepped through by ffmpeg | `video/split.py` |
| Fix and letter | **Muse Spark** (JSON mode) picks a physical fix and writes the letter from the measurements only; verified in two layers before use: code checks every number against the measurements (and sends back numbers in words, speeds in mph, and a sentence that puts one near-miss's speed beside another's time gap), then **Muse Spark as a separate reviewer** (LLM as judge) lists unsupported claims (a warrant said to be met, a death risk for a child); either objection sends the letter back with the reason, and after 3 tries what remains is shown for a person to check, and code adds an AI-draft line for a named person to sign; **Muse Image** draws the fix onto the real street, kept only inside the strip where people were measured crossing (every other pixel stays the real, blurred street), or on the whole photo when no path was measured (there, for a raised crossing, code adds the IRC size: 4 m wide, a speed hump 10-20 m before it) | `pack.py`, `ailabel.py`, `openweights.py` |
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
python3 video/split.py out/VIDEO 1       # hero shot: event1.mp4 beside it in road metres -> out/VIDEO/event1-hero.mp4
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
Spark looked at never go in, even if a page names them; a self-check proves it. In `docs/` (GitHub Pages), git
ignores every video except `eventN.mp4` and `eventN-hero.mp4`, and the person crops and blind clips too. Before
anything is published, the unblurred video goes to SAM, crops of people to Muse Spark and the sound to Muse Wonder,
through Meta's API; the unblurred files stay in `out/VIDEO/` on the machine that ran it until deleted (`FILMING.md`
gives the command).

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
estimated first at Meta's list prices: a run over $10 needs `--allow-cost`, and `--budget USD` is a hard cap that
nothing lifts. With `"person_mode": "auto"` or `"vehicle_mode": "auto"`, a concept goes to SAM video first; if a part
fills its 16 objects before the next part takes over, that concept is detected frame by frame instead and the page
says when it filled (on the Indian time-lapse: "person: 16 objects taken within 1.0-1.6 s in 3 of 3 parts").

### Open weights: Muse Glimmer writes the letter

Set `LETTER_MODEL_URL` to any OpenAI-compatible server and the fix and letter come from that model instead of Muse
Spark, with the same number check. `<removed-run-record>` runs Meta's official 4-bit **Muse Glimmer 30B**
(`meta-models/Muse-Glimmer-30B-GGUF`, Apache 2.0) with llama.cpp on Kaggle's free 2 x T4 and writes the evidence
page; when the pack has a blurred street photo, Glimmer is shown it too. One run has a record so far,
[`<removed-run-record>`](<removed-run-record>): on the synthetic sample, which has no person tracks and so no
photo, Glimmer's part took 592 s; it proposed a raised zebra crossing and wrote a letter whose every number passed the
code check. No Glimmer run has been sent a street photo yet. The letter was correct but stiff, so Muse Spark stays the
default writer. Version 1 ran with llama-server's default sampling and the template's default "high" reasoning. The
notebook now pins llama.cpp `b11976` and the Hugging Face revision, checks both files against their published sha256,
runs one 32,768-token slot with medium reasoning and the model card's sampling, stops with a clear error if Glimmer
runs out of context, and writes `<removed-run-record>` (llama.cpp build, GPUs, timings, the letter's sha256, the git
commit and pack.py's sha256). The page then says "Muse Glimmer 30B wrote this in N s on Kaggle 2 x T4", with N from
the server's own timings. The Kaggle notebook was run by the author.
The open-weights model is also sent a JSON schema whose strings may hold digits only as the measured numbers, each
followed by a non-digit. By llama.cpp's source, llama-server turns it into a grammar that should still let Glimmer
think first; that is not tested yet, as no Glimmer run has used it. The code check and the reviewer still run after
it, and the run record counts Glimmer's tries.
`LETTER_MODEL_KEY` adds a Bearer token for a server that needs one, and the letter says "self-hosted" only when the
server runs on the same machine.
`JUDGE_MODEL_URL` makes the open-weights model a judge too: it reviews the letter beside Muse Spark, or alone without a
Meta key, and the page names only the judges that ran. No Glimmer judge run has been made yet.
`sample/` is a synthetic example (made-up tracks, no video) for trying the letter step anywhere.

```
LETTER_MODEL_URL=http://127.0.0.1:8080/v1 python3 pack.py out/VIDEO site.json
```

#### Open weights: two paths

`LETTER_MODEL` is the model id sent to the server; the page shows the product name and where it ran. A self-hosted
server is named "self-hosted" only when it runs on the machine that ran pack.py, and Fireworks' API "on Fireworks".

**Muse Glimmer 30B, self-hosted on Kaggle** (the notebook sets these; the page says "Muse Glimmer 30B (open weights,
self-hosted)"):

```
LETTER_MODEL_URL=http://127.0.0.1:8080/v1
LETTER_MODEL_HOST="Kaggle 2 x T4"
```

**Muse Spark Open on Fireworks**, a hackathon infra partner (the page says "Muse Spark Open (open weights, on
Fireworks)"). With no `LETTER_MODEL_KEY`, pack.py reads `FIREWORKS_API_KEY` from the environment or `.env`, and sends
it only to `api.fireworks.ai`:

```
LETTER_MODEL_URL=https://api.fireworks.ai/inference/v1
LETTER_MODEL=accounts/fireworks/models/muse-spark-open
FIREWORKS_API_KEY=...
```

Fireworks sends no llama-server timings, so pack.py times the reply itself and writes `letter-provenance.json` beside
`plan.json`: model id, host, request id, token usage, wall seconds, the response format used, tries and the letter's
sha256, never the key. The page then says "Muse Spark Open wrote this in N s on Fireworks", N being that wall time. If
the server rejects the JSON schema with HTTP 400, pack.py asks once more for any JSON object and the record says
`json_object`; the number check and the judges still run. No Fireworks run has been made with pack.py yet.

Either model can judge the other's letter. `JUDGE_MODEL` (default: `LETTER_MODEL`) and `JUDGE_MODEL_KEY` belong to the
judge server alone, and neither server is sent the other's key; a judge on the letter's own URL with no
`JUDGE_MODEL_KEY` uses `LETTER_MODEL_KEY`, as it is the same server. A Glimmer writer on Kaggle with a Spark Open judge:

```
LETTER_MODEL_URL=http://127.0.0.1:8080/v1
JUDGE_MODEL_URL=https://api.fireworks.ai/inference/v1
JUDGE_MODEL=accounts/fireworks/models/muse-spark-open
```

A letter for `sample/` from Muse Spark Open (with `MODEL_API_KEY` set, Muse Spark judges it too):

```
LETTER_MODEL_URL=https://api.fireworks.ai/inference/v1 LETTER_MODEL=accounts/fireworks/models/muse-spark-open python3 pack.py sample sample/site.json
```

### Case agent: it stops to ask for a tape measure

`agent.py` is optional; analyze.py and pack.py never call it. Muse Spark works the case through five tools (track,
review, measure, request_measurement, submit_letter), one tool per turn, with at most 25 turns per start and a $1
cap on its own turns. That cap is an estimate at Muse Spark Open's Fireworks list price ($1.25 / $4.25 per million
input / output tokens); the Meta API price of muse-spark-1.3 is NOT CHECKED. Tracking is outside the cap: SAM, Spark's
pedestrian reviews and the sound check in analyze.py are billed apart, and analyze.py still refuses a SAM estimate
over $10 without `--allow-cost`. Its one tracking decision: when SAM video hits its 16-object limit, it tracks that
concept again in crowd mode, which bills SAM per image. The site file marks a distance that was not used for
calibration, `"check": {"what": "kerb to kerb at the zebra", "points": [[x, y], [x, y]]}`. The agent asks a person to
tape it (answered in m or cm), and the letter is refused until the video and the tape agree within 15% (gate G2) and
the near-misses were tracked with the site's current calibration points. Three refusals in a row go to a person.
The head of the school then approves the letter or sends it back with notes. Every step goes to
`out/VIDEO/case/agent_log.jsonl`, and the page shows "How the agent worked this case". No agent run has been made
against the Meta API yet; a test drives it with a scripted model.

```
python3 agent.py VIDEO site.json                      # runs until it needs a person
python3 agent.py VIDEO site.json --answer R1 "7.2 m"  # the taped length; the agent continues
python3 agent.py VIDEO site.json --approve            # or --reject --notes "..."
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

The bench file keeps every letter and verdict, so a later run only asks for what is missing. For the notebook's
Glimmer pass on Kaggle, attach `out/judge-bench.json` with Add Input: the Spark letter lives in `out/`, which the repo
zip leaves out, so without the file the notebook benches Glimmer's letter alone (12 lies and 4 controls) and its
record says so.

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
metres at a busy Tianjin intersection, 63 pedestrian crossings and 554 moving vehicles (cars, motorcycles, bicycles,
tricycles, buses, trucks). It needs no Meta API. Re-scored on 29 Oct after the speed fix (old and new in `GATES.md`).

- **Speed:** ours, from positions, against SinD's own velocity: mean error 0.24 km/h, 95th percentile 0.91 km/h.
- **PET:** 66 conflicts under 3 s (42 serious). An independent textbook PET over a conflict area (Allen et al.
  1978) agrees within 0.5 s on 53 of 66 and gives the same tier on 57. In every disagreement the area method gives
  the lower PET, because its conflict area is broader, so ours errs on the side of not overstating.
- **Pairs only the textbook flagged** as serious: 9, the same 9 pairs as before the speed fix, and each was checked.
  2 were stopped cars beside a person; we exclude vehicles under 10 km/h on purpose. 4 never came within 3 m at the
  same moment, an artefact of the broad area. 3 were cycles under 10 km/h passing 1.2–1.6 m away, at our thresholds'
  edge.
- **Speed of the search:** the grid index searches 20 minutes of mixed traffic in about a second (1.0 s on a laptop).
- **One number:** 37 of 63 crossings (1 in 1.7) had a moving vehicle through the same spot within 3 s, 25 of 63 (1 in 2.5) within 1.5 s; exact 95% ranges 45.6-71.0% and 27.6-52.8%. The tile it replaced divided conflicts (person-vehicle pairs) by crossings: 66 / 63, "105 per 100 crossings", because a person passed by several vehicles counted once per vehicle.

This checks the measurement layer on true positions.

**A phone at an angle.** SinD is filmed from above. `python3 validate_sind.py data/sind --oblique 10,25` films the
same 20 minutes with a simulated phone 10 m up and 25 m back (focal length 1,500 px), calibrated from four road points
as `calibrate.html` is. Each vehicle becomes the box SAM would draw round it (1.3-3 m tall by type), and the
conflicts found from those boxes are compared with the conflicts from SinD's true footprints on the same frames.
Footprint sizes are SinD's median per vehicle type, as a tape-measured `vehicle_sizes_m` would give:

| Vehicle shape | Conflicts | Serious | Serious missed | Serious extra | PET vs truth (mean) |
|---|---|---|---|---|---|
| SinD footprints (truth) | 55 | 35 | 0 | 0 | +0.00 s |
| lower box edge (before) | 93 | 63 | 6 | 34 | -0.10 s |
| car-shaped footprint | 57 | 37 | 3 | 5 | -0.01 s |
| footprint, boxes off by 3 px | 58 | 38 | 2 | 5 | -0.04 s |
| footprint, lengths 20% too long | 59 | 35 | 4 | 4 | -0.05 s |

The lower box edge lies under the vehicle's near side, not its middle, and nearly doubled the serious
conflicts. A view that is not top-down now uses a car-shaped footprint instead (`road.vehicle_footprints`):
a rectangle of the vehicle type's size, turned to its direction of travel and moved until its image fits the SAM box
(the lowest corner on the box's bottom edge, centred on the box), its centre median-smoothed over ±2 frames. Phone
6 m up and 15 m back: 29 serious in truth, 42 from the lower edge, 31 from footprints; 15 m up and 20 m back: 37, 64
and 38. This is a simulation: the box noise is independent per frame, and no real phone footage was checked.

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
- **Dense Indian intersection** (a YouTube stock clip, 39 s, no ground truth, calibration guessed) **is a
  time-lapse.** In 16 consecutive source frames (0.53 s at 30 fps) people cross half the road and the whole traffic
  state changes. Every speed, PET and near-miss count we gave for it is withdrawn (listed in `GATES.md`, 29 Oct). In
  its worst stored "near-miss" (87.9 km/h) the pedestrian's box slides over empty road while the car's box jumps
  between cars: the tracker joined different road users across the skipped time. Only its detection coverage, the
  objects found per frame, still means something: SAM video found on average 1.6 people and 6 vehicles a frame, crowd
  mode 14.9 people and 20 vehicles. Its site file now says `"not_measurements"`, so pack.py and the case agent
  show the warning and ask for no letter whatever its events.json holds. The walking-pace guard below flags it on
  its own only in crowd mode after an analyze.py re-run (SAM video mode keeps too few walkers to judge).
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
  heading). The view is top-down, not a phone at an angle. Crowd-mode cost uses Meta's list price for SAM images,
  $2.50 per 1,000.

- **Engineering numbers against ground truth** (crowd mode; same definitions applied to the dataset's own tracks):
  - Moving vehicles counted: right on 8 of 8 clips.
  - Gaps of 6 s or more where people crossed: right on 8 of 8.
  - Longest gap: within 0.5 s on 6 of 8.
  - Pedestrian crossings: ours run high, 374 against 280 (1.3x), because a broken track counts a person twice. PV²
    scales with this count, so the page says so.

The DUT data has no licence and was used only for internal testing; it is not included.

### People are the clock

People walk at about 1.2-1.5 m/s, so the people in a video check its clock and its calibration at once. `pace.py`
takes the median walking speed, in road metres a second, of the pedestrian pieces that crossed (the crossing count's
own pieces), and analyze.py writes it to events.json as `"walking"`. With 10 or more walking pieces, a median over
2.4 m/s (sped up, or a calibration rectangle marked too big) or under 0.5 m/s (slowed down, or marked too small) flags
the video. The page then says "People here walk at X m/s (the median of N walking pieces), about K times a normal
walking pace of 1.3 m/s..." in place of the headline, leaves out the near-miss and speed tiles, the pyramid, the
engineering numbers and the gap barcode, shows each card as its clip and time only (no speed, PET, gap, tier or death
risk) and the map without near-miss tiers, and no letter is asked for (no Spark or Glimmer call). A site file's
`"not_measurements"` (a sentence, e.g. "This clip is a time-lapse") does the same whatever the walkers show, also for
an events.json from before pace.py, which has no `"walking"`. Medians measured at $0 from the cached SAM
replies on 29 Oct (details in `GATES.md`):

| Video | Walking pieces | Median walking speed |
|---|---|---|
| DUT drone clips, our tracks (8 clips, each in crowd mode, SAM video and 2 x 2 tiles) | 11-129 per run | 1.05-1.48 m/s |
| DUT and SinD, the datasets' own tracks | 280 / 63 | 1.22 / 1.13 m/s |
| Schoolchildren CCTV (assumed calibration), two runs | 13 / 14 | 0.80 / 1.66 m/s |
| Indian time-lapse, crowd mode | 13 | 2.71 m/s: flagged |
| Indian time-lapse, SAM video | 0 | not judged |

It sees only the people the tracker keeps: on the time-lapse the fastest were lost, so it reads 2.1x normal walking,
not the true speed-up, and a video sped up less than about 2x would pass.

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
"vehicle", $79 with three. The $34 holds only if "vehicle" finds 95% or more of what car, motorcycle and auto
rickshaw find; that $0.15 test (below) has not been run, so "vehicle" is not adopted. Muse Spark, Muse Wonder and
Muse Image are not in these dollars; the page's receipt counts their calls, and its cost line gives each pack's own
SAM cost. Sources: the
[at-network list thread](https://lists.umanitoba.ca/hyperkitty/list/at-network@lists.umanitoba.ca/thread/IDKSFWIEFDC5N73AYNEDYWW3TFUGMF52/)
and [Telraam's prices](https://telraam.net/en/pricing).

```
python3 vehicle_test.py out/indian-crowd           # what the "vehicle" test would cost; sends nothing
python3 vehicle_test.py out/indian-crowd --spend   # 60 cached crowd frames, about $0.15, capped at $0.20
```

## Limits, stated

- From a phone at an angle, a vehicle is a car-shaped footprint of its type's size: car 4.6 x 1.8 m, motorcycle
  1.7 x 0.8 m, auto rickshaw 2.4 x 1.1 m, or tape-measured sizes in the site file
  (`"vehicle_sizes_m": {"car": [3.9, 1.7]}`). Other concepts, including the single concept "vehicle", and vehicles
  that never move far enough for a heading, keep the lower box edge (see the simulation above).
- SAM 3.1 video tracking keeps at most 16 objects per request, so crowded sites need crowd mode, which costs more
  (one image request per 0.2 s). Dense traffic fills even a 15-second part: on our Indian intersection clip every
  vehicle concept hit the limit within 2 s, so there vehicle counts are a minimum. For people it did not track,
  SAM image search looks again on the clips and the street photo (one image request per 0.2 s of published
  video) and blurs those it finds; check every public frame by eye. Number plates are blurred only on vehicles
  SAM tracked.
- Crowd mode fills in a box across up to 1 s of missed detections, so a near-miss can sit on an inferred position
  rather than a seen one. Each card says which: "Seen at the moment", or how long SAM did not detect the person or
  the vehicle when that was 0.5 s or more ("position inferred"). Re-scored at $0 from the cached replies on 29 Oct,
  before Spark's review: 1 of 54 conflicts (vehicle crowd mode) and 1 of 55 (crowd mode) on the top-down DUT clips.
  SAM video mode fills nothing in, so it never flags one.
- A person standing still on the carriageway when a car passes within 1 m is reported as a near-miss.
- The death-risk curve is for adults (15+) hit by a car front; children are not covered by that study.
- Distances are only as good as the measured calibration rectangle.
- Rates per hour from a short video are scaled, not a peak-hour count; the page says so next to PV², and shows no
  PV² for videos under 15 minutes.
- Cost, at Meta's list prices: SAM video $0.20 per 1,000 frames (at least 50 a request), SAM images $2.50 per 1,000,
  Muse Image $0.01 a picture, Muse Wonder $4 per million input tokens and $20 per million output tokens. At 10 frames
  a second in 15 s parts that overlap by 2 s, an hour of video mode with four concepts sends 166,080 frames: about
  $33. Crowd mode costs more: 15 minutes of people at 5 images a second plus three vehicle concepts at 10 a second
  is 31,500 images, about $79 (about $34 with the single concept "vehicle", if `vehicle_test.py` shows it finds 95%
  of what the three concepts find; not run yet). The page prints the SAM cost for each video.
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

All code in this repository was written during the hackathon, except the mask decoder in `masks.py`: a Python port
of the one_bit decoder in Meta's meta-sam-parser (`_mask_codec.py`, Copyright (c) Meta Platforms, Inc. and
affiliates), used under its SAM License (github.com/meta-models/meta-sam). The check-then-retry pattern for Spark's
letter, the reject-with-notes revision and the JSON-mode request field follow Meta's legal-agent workshop
(github.com/meta-models/legal-agent-workshop, shown at a hackathon session); no code was copied from it. The
case agent follows the shape of that workshop's loop (one tool per turn, plain text sent back, a stop for a person,
resume from saved progress, escalation after 3 refusals); its code is our own. No
third-party libraries; Python standard library and ffmpeg only. Test videos from YouTube were used only for local
testing and are not included. The SinD sample (SOTIF-AVLab, non-commercial use) was used only for validation and is
not included.
