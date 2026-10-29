# Filming a crossing for Crossing Watch

Everything rests on one recording. Road metres are fixed from one frame, so if the phone moves, switches lens or
changes frame rate, every distance and speed after that is wrong, and nothing in a shot clip can be fixed later.
So: settings first, a 10-second test clip, then the real shoot.

**Our shoot:** test clip at Thu 29 Oct dismissal; main shoot Fri 30 Oct at dismissal. Backup slot: Sat 31 Oct if the
college is open, else Mon 2 Nov. Agree the backup with the filmer now.

## Before the day

- Written OK from the college office to film and to publish blurred clips.
- Ask the office two numbers for the site file: school days a year (`"school_days"`) and how long dismissal lasts (`"dismissal_minutes"`). With both and 15 minutes of video, the page adds a school-year line.
- Print an A3 notice and tape it at the gate: "Road-safety study by [student], [college]. Vehicles are measured.
  The video and its sound are analysed with Meta's AI services. Only clips and pictures with faces blurred are
  published. The raw video stays with the study team and is deleted when the study ends. Contact: ___."
  Film the notice for 3 seconds at the start of the recording.
- Tape measure (15 m or longer), chalk, coloured tape, a tripod or tape to fix the phone, a power bank.

## Phone

- **iPhone:** Settings > Camera > Record Video:
  - **1080p at 30 fps.**
  - **Lock Camera ON** (no switching lenses while recording).
  - **Auto FPS OFF** (it drops to 24 fps in low light).
- Plain **Video** mode. **No Cinematic, no Action mode**: both can record at 24 fps.
- **1x lens.** No zoom, no 0.5x.
- Landscape. Touch and hold on the road until "AE/AF LOCK" shows, so exposure and focus stay put.
- On a tripod, or wedged or taped on the parapet. It must not move or turn for the whole recording.
- Phone in shade (heat throttles it), airplane mode, storage for 40+ minutes, power bank plugged in.
- Sound ON, so Muse Wonder can hear horns and brakes.
- Android: find the same settings (1080p, 30 fps, no automatic frame rate, no stabilised "action" mode). Names vary
  by phone and were not checked.

Why 30 fps, locked: `analyze.py` resamples every clip to 10 frames a second. From 25 or 30 fps that keeps evenly
spaced frames. From 24 fps it keeps uneven steps of 2, 2, 3, 2, 3 source frames. The old median-of-steps speed read a
steady car there at 0.834 times its true speed (17% slow); today's least-squares speed in `road.speeds()` reads the
true speed at 24 fps too (a self-check in `test_cw.py`). We still ask for 30 fps locked, so every clip is treated
alike and the G6 speed check is timed on a 30 fps original.

## Framing

- From the building top, angled down at the road.
- In frame: the gate, the whole crossing kerb to kerb, and 20-30 m of approach road on both sides.
- If there is a zebra, all of it.

## Tape and chalk (kerb and footpath only; nobody stands in the road)

Mark everything before the rush, and photograph each mark with the tape visible.

1. **Calibration rectangle, 8 m or more along the road.** Two corners on the near kerb, two straight across on the
   far kerb. A small rectangle turns a few pixels of click error into a large scale error. Tape the far side and
   the width across in a clear gap, the way anyone crosses; nobody waits on the road. If a zebra exists, its corners
   can be the rectangle.
2. **Two speed lines, 15 m apart.** Four more tape marks, two on EACH kerb, making two lines across the road 15 m
   apart and centred on the crossing (7.5 m either side). Not the rectangle's corners. Vehicles timed between them
   check our speeds, and the 15 m is the road distance never used for calibration (gate G2).
3. Carriageway width where students queue.
4. One parked car and one auto-rickshaw: length and width.
5. Notes: gate position, zebra yes or no, speed breakers, kerb parking, where autos and buses stop. Photograph any
   speed-limit board.

## Test clip first (10 seconds)

Record 10 seconds with every setting above, send the original (see below), and check it before the main shoot:

```
python3 filmcheck.py TEST.MOV        # ffprobe: 1920x1080 landscape, 30 fps (29.97 is fine), steady rate, sound
```

It prints `fit` or what to change. Then by eye: the view matches the 1x lens (no fish-eye bend, not zoomed), and the
first and last frames line up:

```
ffmpeg -v error -i TEST.MOV -frames:v 1 first.png
ffmpeg -v error -sseof -1 -i TEST.MOV -update 1 last.png
```

## What to record

- 20-40 minutes: the dismissal rush plus a quieter stretch. The 10-15 minute rush is analysed first.
- First 10 seconds: one sentence with the place, date, bell time and posted speed limit. Then the notice.
- After that, one quiet word ("close") for each near-miss you see, then silence. Chatter merges speech and can be
  heard as a shout.
- Do not touch the phone until the end.

## B-roll (with consent)

- The rooftop set-up and the tape measuring.
- A wide shot of the gate and the notice.
- No close-ups of students' faces.

## Send and keep

- Send the **original file by a Google Drive link** (or cable, or AirDrop). **Never WhatsApp**: it shrinks and
  re-compresses the video. `filmcheck.py` catches a shrunken copy.
- Back it up twice until the study ends, and note its fingerprint: `shasum -a 256 CLIP.MOV`. `analyze.py` records
  the same SHA-256 and the page prints it, which ties the pack to this one recording, so send the original, not a
  copy.
- What leaves the laptop: `analyze.py` sends the unblurred video to SAM, crops of people to Muse Spark and the sound
  to Muse Wonder, through Meta's API. `pack.py` sends the measurements and the first frame, faces and number plates
  blurred, to the letter's writer: Muse Spark through Meta's API, or the server in `LETTER_MODEL_URL` (e.g. Fireworks,
  not Meta). The measurements and the letter go to its judges (Muse Spark, and the server in `JUDGE_MODEL_URL`), and
  the blurred frame to Muse Image through Meta's API. Only `out/VIDEO/share/` is published: blurred clips and
  pictures.
- The unblurred files stay in `out/VIDEO/`: `clip.mp4` (and the parts cut from it), the `person-*.jpg` crops Spark
  saw and the `event*.wav` sound. When the study ends (the letter filed, the hackathon judged), delete them with the
  raw video and its backups, as the notice says:

  ```
  find out/VIDEO \( -name clip.mp4 -o -name 'person-*.jpg' -o -name '*.wav' \) -delete
  rm CLIP.MOV
  ```

  The SAM replies (`*.sam.txt`: boxes and silhouettes, no picture) and the share folder stay; the page keeps the
  original's SHA-256. After this, `analyze.py` and `pack.py` cannot run on that folder again.

## After the footage arrives

- `python3 filmcheck.py CLIP.MOV`, then compare the first and last frames as above.
- Calibrate in `calibrate.html` with the taped rectangle. G2: the 15 m between the speed lines must come out within
  ±15%.
- Screen-record the first run. Keep `.env` and API keys out of frame.
