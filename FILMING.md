# Filming a crossing for Crossing Watch

Everything rests on one recording. Road metres are fixed from one frame, so if the phone moves, switches lens or
changes frame rate, every distance and speed after that is wrong, and nothing in a shot clip can be fixed later.
So: settings first, a 10-second test clip, then the real shoot.

**Our shoot:** a full dress rehearsal on Sat 31 Oct at dismissal (same spot, stand, clock time and settings as the
main shoot, 20-25 minutes), and the main shoot on Mon 2 Nov at dismissal. Keep the rehearsal file (`REH.MOV`) as
Monday's fallback (rain, no permission, a knocked stand). If the college is shut on Saturday, rehearse the steps
below on the first 2 minutes of Monday's footage before the paid run.

## Before the day

- Written OK from the college office to film and to publish blurred clips (in the demo video, the public project
  page and one X post). In the same request, ask for the filming spot (see Position) and whether the principal's
  name and role may appear on the evidence page.
- Ask the office two numbers for the site file: school days a year (`"school_days"`) and how long dismissal lasts
  (`"dismissal_minutes"`). With both and at least 15 analysed minutes, the page adds a school-year line.
- Print an A3 notice and tape it at the gate: "Road-safety study by [student], [college]. Vehicles are measured.
  The video and its sound are analysed with Meta's AI services. Only clips and pictures with faces blurred are
  published. The raw video stays with the study team and is deleted when the study ends. Contact: ___."
  The recording phone never films it: film it with another phone as B-roll, or leave it taped where it already
  sits inside the fixed frame. Frame 0 of the analysed video becomes the public street photo and Muse Image's input.
- Tape measure (15 m or longer), chalk, coloured tape, the stand or a tripod (or tape to fix the phone), a power
  bank, paper and a pen.

## Phone

- **iPhone:** Settings > Camera > Record Video:
  - **1080p at 30 fps.**
  - **Lock Camera ON** (no switching lenses while recording).
  - **Auto FPS OFF** (it drops to 24 fps in low light).
- Look for **HDR Video** and turn it **off**: an HDR recording comes out darker and paler in every published clip
  and still.
- If the phone has a **Record Sound** setting, set it to **Stereo**, not Spatial Audio.
- Plain **Video** mode. **No Cinematic, no Action mode**: both can record at 24 fps.
- **1x lens.** No zoom, no 0.5x.
- Landscape. Touch and hold on the road until "AE/AF LOCK" shows, so exposure and focus stay put. If the shoot will
  run into dusk, skip the lock: Auto FPS off already holds 30 fps.
- On the stand or a tripod, or wedged or taped at the window or terrace edge. It must not move or turn for the
  whole recording.
- Start at 100% battery, phone in shade (heat throttles it), airplane mode. At least 5 GB free: 25 minutes is about
  1.5 GB in HEVC and about 3.3 GB in H.264. Leave the power bank unplugged unless the battery will not last; then
  plug it in before recording starts, never during.
- Sound ON, so Muse Wonder can hear horns and brakes.
- Android: find the same settings (1080p, 30 fps, no automatic frame rate, no HDR, no stabilised "action" mode).
  Names vary by phone and were not checked.

Why 30 fps, locked: `analyze.py` resamples every clip to 10 frames a second. From 25 or 30 fps that keeps evenly
spaced frames. From 24 fps it keeps uneven steps of 2, 2, 3, 2, 3 source frames. The old median-of-steps speed read a
steady car there at 0.834 times its true speed (17% slow); today's least-squares speed in `road.speeds()` reads the
true speed at 24 fps too (a self-check in `test_cw.py`). We still ask for 30 fps locked, so every clip is treated
alike and the G6 speed check is timed on a 30 fps original.

## Position and framing

- A stand on the footpath at 2.5-3 m, or the highest safe spot, such as a first-floor window or a terrace, angled
  down at the road. Higher is better: in a simulation on SinD tracks, a person was hidden or had their feet
  blocked about three times as often from 3 m up as from 10 m up.
- In frame: the gate, the whole crossing kerb to kerb, and 20-30 m of approach road on both sides.
- If there is a zebra, all of it.

## Tape and chalk (kerb and footpath only; nobody stands in the road)

Mark everything before the rush, and photograph each mark with the tape visible. Write every distance in
`notes.txt` (it is never committed).

1. **One zero point** on the near kerb, such as a gate post. Write the along-kerb distance from it to all 8 marks:
   the 4 rectangle corners and the 4 speed-line marks. A far mark sits straight across from its near mark.
2. **Calibration rectangle, 8 m or more along the road.** Two corners on the near kerb, two straight across on the
   far kerb. A small rectangle turns a few pixels of click error into a large scale error. Tape the far side and
   the width across in a clear gap, the way anyone crosses; nobody waits on the road. If a zebra exists, its corners
   can be the rectangle.
3. **Two speed lines, 15 m apart.** Four more tape marks, two on EACH kerb, making two lines across the road 15 m
   apart and centred on the crossing (7.5 m either side). Not the rectangle's corners. Vehicles timed between them
   check our speeds (G6).
   - **This 15 m is the held-out distance, and it must never enter any fit.** calibrate.html writes it as the
     site's `check` from the A near and B near clicks; G2, G6 and the agent's tape-measure question rely on it.
   - Never use the kerb-to-kerb width as the check: it is a calibration input, so it can never fail.
4. Carriageway width where students queue.
5. One parked car, one auto-rickshaw and one college bus: length and width. A motorcycle is optional (a default size
   is built in). Measuring the bus is not claimed to improve accuracy.
6. Notes: gate position, zebra yes or no, speed breakers, kerb parking, where autos and buses stop. Photograph any
   speed-limit board.

## Test clip first (10 seconds)

Record 10 seconds with every setting above, send the original (see below), and check it before the main shoot:

```
python3 filmcheck.py TEST.MOV
```

It prints `fit` or what to change: the size, the frame rate, the sound, HDR, Spatial Audio, and whether the camera
moved or the picture darkened. Then by eye: the view matches the 1x lens (no fish-eye bend, not zoomed).

## Recording

- Put up the stand, fix and frame the phone, and only then start recording (a watch remote, or the camera's timer
  if it has one for video), so nobody setting up is filmed.
- Record 20-25 minutes: the dismissal rush plus a quieter stretch. Only a window of 15 minutes or more is analysed
  (see below).
- First: one sentence with the place, date, bell time and posted speed limit. Then silence to the end. No spoken
  calls such as "close": Muse Wonder listens for shouts around each near-miss, and the filmer's own word would be
  reported as another witness's.
- Do not touch the phone until the end.
- Optional: a second person, away from the phone, writes the clock time of each near-miss they see on paper, and
  the time of one thing easy to find in the video (the bell, the first bus). Nothing reads these yet. To line them
  up, take the recording's start time from the clip's info in Photos, or from
  `ffprobe -v error -show_entries format_tags=creation_time -of default=nw=1:nk=1 CLIP.MOV` (UTC: add 5 h 30 min
  for IST), and check it against that one event.

## Which minutes are analysed, and the cost

- The site file's `"window_s": [S, E]` (seconds from the start of the recording, `E - S` at least 900) names the
  minutes analysed. Choose S and E by the window rule in GATES.md, written before any footage (for example "bell
  minus 2 min, 15 min long"), never after seeing the near-misses. `analyze.py` still hashes the whole original, so
  the page stays tied to the phone's file.
- Why: SAM bills by the frame. The whole 25 minutes with calibrate.html's four default vehicles and "Dense traffic"
  ticked (vehicles found frame by frame) is about $169, more than the $150 in credits.
- Add `bicycle` to the vehicles only if the rehearsal shows cyclists: each extra vehicle costs about $2 per 15
  minutes, or $22.50 with "Dense traffic" ticked.
- Fallback, only if the free estimate (below) reports the whole recording's minutes instead of the window's: cut
  the window by hand (`-t` is the window's length, E - S) and analyse the cut file. A cut file has its own SHA-256,
  so note both fingerprints.

  ```
  ffmpeg -v error -ss S -i CLIP.MOV -t 900 -map 0:v:0 -map 0:a:0 -c copy CUT.MOV
  ```

## B-roll

- B-roll is raw 1080p that the pipeline never blurs. Default: no recognisable faces (hands on the tape, the stand,
  backs to the camera), or blur them in the edit.
- The set-up and the tape measuring.
- The notice, filmed with a second phone.
- No close-ups of students' faces.

## Send and keep

- Send the **original file by AirDrop or cable** (or a Google Drive link). **Never WhatsApp**: it shrinks and
  re-compresses the video. `filmcheck.py` catches a shrunken copy.
- Back it up twice (an external drive or the cloud, not the laptop's own disk) until the study ends, and note its
  fingerprint: `shasum -a 256 CLIP.MOV`. `analyze.py` records the same SHA-256 and the page prints it, which ties
  the pack to this one recording, so send the original, not a copy.
- What leaves the laptop: `analyze.py` sends the unblurred video to SAM, crops of people to Muse Spark and the sound
  to Muse Wonder, through Meta's API. `pack.py` sends the measurements and the first frame, faces and number plates
  blurred, to the letter's writer: Muse Spark through Meta's API, or the server in `LETTER_MODEL_URL` (e.g. Fireworks,
  not Meta). The measurements and the letter go to its judges (Muse Spark, and the server in `JUDGE_MODEL_URL`), and
  the blurred frame to Muse Image through Meta's API. Only `out/VIDEO/share/` is published: blurred clips and
  pictures.
- The unblurred files stay in `out/VIDEO/`: `clip.mp4` (and the parts cut from it), the `person-*.jpg` crops Spark
  saw and the `event*.wav` sound. When the study ends (the letter filed, the hackathon judged), delete them in each
  video's folder (Monday's and the rehearsal's), with the raw videos, the test clip, the calibration frame and any
  cut file, as the notice says:

  ```
  find out/VIDEO \( -name clip.mp4 -o -name 'person-*.jpg' -o -name '*.wav' \) -delete
  rm -f CLIP.MOV TEST.MOV REH.MOV CUT.MOV frame.jpg first.png last.png
  ```

  Then delete the backups and the phone's own copies (Photos, then Recently Deleted). The SAM replies (`*.sam.txt`:
  boxes and silhouettes, no picture) and the share folder stay; the page keeps the original's SHA-256. After this,
  `analyze.py` and `pack.py` cannot run on that folder again.

## After the footage arrives

- `python3 filmcheck.py CLIP.MOV`. If the camera moved, re-shoot, or end the window before the move.
- Set `window_s` by the rule, then take the calibration frame from inside the window:
  `ffmpeg -v error -ss S -i CLIP.MOV -frames:v 1 frame.jpg` (with a hand-cut file, S is 0).
- Calibrate in `calibrate.html` with the taped rectangle. After the 4 rectangle corners, click the speed-line marks
  A near, B near, B far, A far. The page writes `trap` and `check` from them; SITE.json is empty at 5-7 clicks.
  G2: the 15 m between the speed lines must come out within ±15%.
- Add the taped vehicle sizes to the saved site file by hand (calibrate.html does not write them), length first,
  under the names in `"vehicles"`: `"vehicle_sizes_m": {"car": [L, W], "auto rickshaw": [L, W], "bus": [L, W]}`.
- Free estimate: `python3 analyze.py CLIP.MOV SITE.json --budget 0` prints the minutes it would analyse and "SAM
  cost about $X", then, on a first run, stops before any request. It does not include auto mode's worst case: a
  site with `"person_mode"` or `"vehicle_mode"` set to `"auto"` can switch to frame-by-frame after the video
  requests are paid. Pick the modes and the budget from the estimate.

**The paid run (screen-recorded once; a retake costs money).**

- Record `analyze.py`, not the agent. The agent calls `analyze.py` without `--budget`, so its $10 default cap would
  stop it on camera: 15 minutes of people and the four default vehicles in video mode is about $10.40. On mains
  power, with N from the free estimate:

  ```
  date; time caffeinate -dims python3 analyze.py CLIP.MOV SITE.json --budget N; date
  ```

- Before it: both backups made, and 30-40 GB free on the Mac.
- Chat apps closed. Optional: seconds shown in the menu-bar clock.
- Label the run in the video as sped up, by the real factor from the recording's length. On the rehearsal: a
  5-second Cmd+Shift+5 test checked with `ffprobe`, and a timed short run for that factor.
- Optional page takes in a Chrome app window, recorded with a Cmd+Shift+5 selection inside the page:

  ```
  open -na "Google Chrome" --args --user-data-dir=/tmp/cw-rec --no-first-run --no-default-browser-check \
    --app="file://$HOME/Desktop/crossing-watch/out/CLIP/index.html#event-1"
  ```

**Every screen recording.**

- No QuickTime, Finder or Quick Look window on `CLIP.MOV`, `clip.mp4` or `person-*.jpg`.
- No editor tab on `.env`; keep API keys out of frame.
- Do the real calibration off camera. To show it, re-enact it in `calibrate.html` on `out/CLIP/street.jpg` (blurred,
  written by `pack.py`) with "This frame is from the prepared clip.mp4" ticked, and never save that re-enactment
  over the real site file: it would change every measured number.
- Do Not Disturb or a Focus on; browser tabs and the bookmarks bar hidden.
- Paths printed in the terminal are not a leak.
