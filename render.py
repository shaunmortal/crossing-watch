"""Evidence clips: a few seconds around each near-miss, with the pedestrian drawn cyan and the vehicle red (as SAM's
own silhouettes where its masks are cached, else as boxes), the pedestrian's footsteps dotted cyan up to a yellow spot
where the two met, every person's head blurred so clips of children can be shared, and every number plate SAM 3.1
found under a light mosaic that hides it (the vehicle stays a vehicle). Then a StroMotion still of each clip: the
whole near-miss in one picture.
Captions (PET, gap, speed) are shown by the evidence page, since this ffmpeg build has no text filter.
The clip then gets the road's own sound (road_sound), every voice Muse Voice Transcribe hears silenced, so the horn
Muse Wonder heard can be heard too."""
import shutil
import subprocess
import tempfile
from pathlib import Path

import crowd
import masks
import sam
import seal
import voice

PAD_S = 2.0
HEAD_SHARE = 0.3   # the top 30% of a person box holds the head
MIN_BLUR_PX = 3    # heads smaller than this are unrecognisable anyway, and delogo needs room
MAX_FILTERS = 2000  # ffmpeg 9 died (SIGBUS) on one chain of 5000 delogos (fine at 3000): a crowd is blurred in passes
MOSAIC_PX = 6      # on the 640 px frame a ~10x5 px plate is ~2 flat blocks, a car stays a car; even for yuv420p
FALLBACK_MIN_PX = 240  # no plate found: whole box only from here (4.5 m car, 65 mm characters: 240 * 65 / 4500 = 3.5 px)
FALLBACK_EDGE_MIN_PX = 120  # ...or, cut by the frame edge, from this shorter side (1.8 m wide: 120 * 65 / 1800 = 4.3 px)
EDGE_PX = 2        # a box this near the frame edge is cut by it: its length is hidden
PLATE_CONCEPT = "license plate"  # what SAM 3.1 is asked to find, on full-resolution cuts (analyze.fetch_plates)
PLATE_PAD = 0.4    # a found plate's mosaic reaches this share of its size past each side: SAM's box is tight
MIN_PLATE_PX = 8   # ...and is at least this many px each way on the 640 px frame (a far plate is a few px)
TRAIL_STEP = 2     # a footstep dot every 2nd frame
DOT_PX = 6         # footstep dot size
SPOT_PX = 14       # the meeting spot, larger than a footstep
TINT = 89          # silhouettes are filled at 35% (of 255), so the street shows through
HOLD_FRAMES = 1    # crowd mode finds people every 2nd frame: the frame between borrows its neighbour's mask
RGB = {"cyan": b"\x00\xff\xff", "red": b"\xff\x00\x00"}
STEP_S = 0.5       # the still copies both road users this often, so wider spacing means faster
CAR_STEP_S = 1.0   # a car is long: at 0.5 s its copies would pile up
MAX_IOU = 0.3      # a copy that overlaps the last one kept on its side more than this is left out
MIN_COPY_PX = 2    # a copy cut thinner than this by the frame edge is left out
EDGE = "@0.7:t=1"  # each pasted copy gets a thin outline in its colour
VOICE_PAD_S = 0.25  # a muted voice starts and ends this much wider: Voice Transcribe's turn edges are approximate


def box_filters(tracks, first, last):
    """One drawbox per tracked box per frame, timed to the cut clip (frame numbers restart at 0)."""
    out = []
    for track, colour in tracks:
        for f in range(first, last + 1):
            b = track.get(f)
            if b:
                out.append(f"drawbox=x={b[0]:.0f}:y={b[1]:.0f}:w={b[2] - b[0]:.0f}:h={b[3] - b[1]:.0f}"
                           f":color={colour}:t=3:enable='eq(n,{f - first})'")
    return out


def blur_filters(person_tracks, first, last, frame_size):
    """One delogo (smear) per head per frame. delogo needs the area strictly inside the frame, so it is clamped."""
    width, height = frame_size
    out = []
    for track in person_tracks:
        for f in range(first, last + 1):
            b = track.get(f)
            if not b:
                continue
            x1, y1 = max(1, round(b[0])), max(1, round(b[1]))
            x2, y2 = min(width - 2, round(b[2])), min(height - 2, round(b[1] + HEAD_SHARE * (b[3] - b[1])))
            if x2 - x1 >= MIN_BLUR_PX and y2 - y1 >= MIN_BLUR_PX:
                out.append(f"delogo=x={x1}:y={y1}:w={x2 - x1}:h={y2 - y1}:enable='eq(n,{f - first})'")
    return out


def plate_filters(vehicle_tracks, first, last, frame_size, plate_tracks=()):
    """A light mosaic (MOSAIC_PX blocks) over every number plate on frames first..last: each plate SAM found
    (`plate_tracks`, in clip pixels), and on a frame SAM missed it, the plate carried on its vehicle (plate_boxes),
    each grown by `padded`. A vehicle with no plate found in first..last gets it over its whole box on the frames a
    plate on it could be legible (plate_readable): seen from above at an angle, a turned vehicle's plate can sit
    anywhere in its box. A smaller one is left as filmed. Clamped to the frame; one filtergraph per MAX_FILTERS boxes (see
    mosaic); none without a box."""
    plates, found_on = plate_boxes(vehicle_tracks, plate_tracks, first, last)
    covers = [(f, padded(b)) for f, boxes in plates.items() for b in boxes]
    covers += [(f, t[f]) for i, t in enumerate(vehicle_tracks) if i not in found_on for f in range(first, last + 1)
               if f in t and plate_readable(clamped(t[f], frame_size), frame_size)]
    boxes = [f"drawbox=x={x1}:y={y1}:w={x2 - x1}:h={y2 - y1}:color=white:t=fill:enable='eq(n,{f - first})'"
             for f, b in covers for x1, y1, x2, y2 in [clamped(b, frame_size)]
             if x2 - x1 >= MIN_BLUR_PX and y2 - y1 >= MIN_BLUR_PX]
    return [mosaic(boxes[k:k + MAX_FILTERS]) for k in range(0, len(boxes), MAX_FILTERS)]


def clamped(box, frame_size):
    """(x1, y1, x2, y2) of a box rounded to whole pixels and cut to the frame."""
    return (max(0, round(box[0])), max(0, round(box[1])), min(frame_size[0], round(box[2])),
            min(frame_size[1], round(box[3])))


def padded(plate):
    """A found plate grown by PLATE_PAD of its size past each side, and to at least MIN_PLATE_PX each way."""
    cx, cy = (plate[0] + plate[2]) / 2, (plate[1] + plate[3]) / 2
    half_w = max((plate[2] - plate[0]) * (0.5 + PLATE_PAD), MIN_PLATE_PX / 2)
    half_h = max((plate[3] - plate[1]) * (0.5 + PLATE_PAD), MIN_PLATE_PX / 2)
    return [cx - half_w, cy - half_h, cx + half_w, cy + half_h]


def plate_boxes(vehicle_tracks, plate_tracks, first, last):
    """({frame: [plate box]}, indices of the vehicles a plate was found on) for frames first..last: every plate SAM
    found, and on each frame it missed a plate on a vehicle it was found on, the plate carried there from the nearest
    frame it was found on that vehicle, as shares of the vehicle's box (so it grows as the vehicle nears). A plate is
    on the smallest vehicle box that holds its centre; one on none is hidden where seen and carried nowhere."""
    out, found_on = {}, set()
    for plate in plate_tracks:
        shares = {}  # vehicle index -> {frame: the plate as shares of that vehicle's box}
        for f in range(first, last + 1):
            if f in plate:
                out.setdefault(f, []).append(plate[f])
                v = holder(plate[f], {i: t[f] for i, t in enumerate(vehicle_tracks) if f in t})
                if v is not None:
                    shares.setdefault(v, {})[f] = share_of(vehicle_tracks[v][f], plate[f])
        for v, seen in shares.items():
            found_on.add(v)
            for f in range(first, last + 1):
                if f in vehicle_tracks[v] and f not in plate:
                    near = min(seen, key=lambda g: abs(g - f))
                    out.setdefault(f, []).append(share_of(vehicle_tracks[v][f], seen[near], back=True))
    return out, found_on


def holder(plate, vehicles):
    """The key of the smallest of `vehicles` ({key: box}) holding the plate's centre, or None."""
    cx, cy = (plate[0] + plate[2]) / 2, (plate[1] + plate[3]) / 2
    held = [k for k, b in vehicles.items() if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]]
    return min(held, key=lambda k: (vehicles[k][2] - vehicles[k][0]) * (vehicles[k][3] - vehicles[k][1]), default=None)


def share_of(box, plate, back=False):
    """The plate as shares of the box's width and height; with `back`, shares (`plate`) put back on the box."""
    x, y, w, h = box[0], box[1], box[2] - box[0], box[3] - box[1]
    if back:
        return [x + plate[0] * w, y + plate[1] * h, x + plate[2] * w, y + plate[3] * h]
    return [(plate[0] - x) / w, (plate[1] - y) / h, (plate[2] - x) / w, (plate[3] - y) / h]


def plate_folder(out_dir, first, last):
    """Where analyze.fetch_plates keeps the full-resolution cut of clip frames first..last and SAM's plate reply."""
    return Path(out_dir) / "plates" / f"{first}-{last}"


def cached_plates(out_dir, first, last, frame_size):
    """The number plates SAM found on clip frames first..last (analyze.fetch_plates), from the reply cached under
    `out_dir`, in clip frames and in pixels of a `frame_size` frame: [{frame: box}]. [] when SAM was not asked."""
    reply = sam.cache_path(plate_folder(out_dir, first, last), PLATE_CONCEPT)
    text = reply.read_text() if reply.exists() else ""
    seen = sam.frame_size(text)
    if not seen:
        return []
    scale = lambda b: [b[0] * frame_size[0] / seen[0], b[1] * frame_size[1] / seen[1],
                       b[2] * frame_size[0] / seen[0], b[3] * frame_size[1] / seen[1]]
    return [{first + f: scale(b) for f, b in track.items()} for track in sam.parse(text).values()]


def plate_readable(box, frame_size):
    """Whether a plate on a vehicle's box (x1, y1, x2, y2, inside the frame) could be legible: its longer side is
    FALLBACK_MIN_PX or more, or the box touches the frame edge (within EDGE_PX), which hides the vehicle's length, and
    its shorter side is FALLBACK_EDGE_MIN_PX or more."""
    x1, y1, x2, y2 = box
    width, height = frame_size
    cut = min(x1, y1) <= EDGE_PX or x2 >= width - EDGE_PX or y2 >= height - EDGE_PX
    return max(x2 - x1, y2 - y1) >= FALLBACK_MIN_PX or (cut and min(x2 - x1, y2 - y1) >= FALLBACK_EDGE_MIN_PX)


def mosaic(boxes):
    """One input, one output: the frame pixelized, let through only where a mask of white `boxes` (drawbox filters on
    black) is drawn, so it joins a filter chain like one more filter."""
    return (f"split=3[mo][mp][mk];[mp]pixelize=w={MOSAIC_PX}:h={MOSAIC_PX}[mq];"
            f"[mk]drawbox=color=black:t=fill,{','.join(boxes)},lut=y='255*gt(val,128)'[ma];"
            f"[mq][ma]alphamerge[mv];[mo][mv]overlay")


def foot(box, top_down=False):
    """Pixel the pedestrian stands on: the bottom centre of the box, or its centre seen from straight above."""
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2 if top_down else box[3]


def dot(point, size, colour, from_n):
    """A filled square centred on `point` that stays on screen from clip frame `from_n` to the end."""
    return (f"drawbox=x={point[0] - size / 2:.0f}:y={point[1] - size / 2:.0f}:w={size}:h={size}:color={colour}"
            f":t=fill:enable='gte(n,{from_n})'")


def trail_filters(track, event, fps, first, last, top_down=False):
    """Footsteps: a cyan dot where the pedestrian stood every TRAIL_STEP frames, each staying to the end of the
    clip, then a yellow spot where the two met (the pedestrian's feet at the event), shown from when the first of
    them got there."""
    dots = [dot(foot(track[f], top_down), DOT_PX, "cyan", f - first)
            for f in range(first, last + 1, TRAIL_STEP) if f in track]
    fp, fv = round(event["t_person_s"] * fps), round(event["t_vehicle_s"] * fps)
    at = min(track, key=lambda f: abs(f - fp), default=None)  # the box at the event, or the nearest one
    return dots + ([dot(foot(track[at], top_down), SPOT_PX, "yellow", min(fp, fv) - first)] if at is not None else [])


def window(event, fps):
    """(first, last) clip frames of an event's evidence clip: PAD_S before the first of the pedestrian and the
    vehicle reached the spot to PAD_S after the second did, so a close pass still shows the vehicle arriving."""
    times = event["t_person_s"], event["t_vehicle_s"]
    return max(0, round(min(times) * fps) - round(PAD_S * fps)), round(max(times) * fps) + round(PAD_S * fps)


def replay(event, feet, shapes, fps):
    """Where the two were in road metres on each frame of the event's clip (window()), for the hero split shot:
    [{"frame", "person": [x, y], "vehicle": [[x, y], ...]}], None where one was not measured on that frame. `feet`
    is the pedestrian piece's {frame: point}, `shapes` the vehicle's {frame: shape} (road.vehicle_edges)."""
    first, last = window(event, fps)
    metres = lambda points: [[round(x, 2), round(y, 2)] for x, y in points]
    return [{"frame": f, "person": metres([feet[f]])[0] if f in feet else None,
             "vehicle": metres(shapes[f]) if f in shapes else None} for f in range(first, last + 1)]


def shapes(track, found, first, last):
    """{frame: (x, y, mask rows)} for frames first..last: the SAM mask under the track's box (from masks.find), or
    one within HOLD_FRAMES moved to this frame's box; frames with neither are left out and keep their box."""
    rows = {}
    for f in range(first - HOLD_FRAMES, last + HOLD_FRAMES + 1):
        entry = found.get(masks.key(track[f])) if f in track else None
        if entry:
            try:
                rows[f] = masks.decode(entry[2], entry[0], entry[1])
            except ValueError as err:  # drawing only: the frame keeps its box
                print(f"SAM mask at frame {f} not drawn: {err}", flush=True)
    out = {}
    for f in range(first, last + 1):
        near = min(rows, key=lambda g: abs(g - f), default=None)
        if f in track and near is not None and abs(near - f) <= HOLD_FRAMES:
            out[f] = (round(track[f][0]), round(track[f][1]), rows[near])
    return out


def paint(frame, frame_size, x0, y0, rows, rgba):
    """Fill one RGBA frame with `rgba` where a mask whose top-left is (x0, y0) is 1, clamped to the frame."""
    width, height = frame_size
    for y, row in enumerate(rows, y0):
        x = row.find(1) if 0 <= y < height else -1
        while x >= 0:
            end = row.find(0, x)
            end = len(row) if end < 0 else end
            a, b = max(x + x0, 0), min(end + x0, width)
            if a < b:
                frame[(y * width + a) * 4:(y * width + b) * 4] = rgba * (b - a)
            x = row.find(1, end)


def silhouettes(pairs, folder, first, last, frame_size):
    """(RGBA frames first..last with each (track, colour) pair's SAM masks filled in its colour, later pairs on top;
    per pair, the frames drawn so). No frames (b"") when no box in the window has a mask cached under `folder`."""
    boxes = [t[f] for t, _ in pairs for f in range(first - HOLD_FRAMES, last + HOLD_FRAMES + 1) if f in t]
    found = masks.find(folder, boxes)
    drawn = [shapes(t, found, first, last) for t, _ in pairs]
    if not any(drawn):
        return b"", [set() for _ in pairs]
    frames = []
    for f in range(first, last + 1):
        frame = bytearray(frame_size[0] * frame_size[1] * 4)
        for shape, (_, colour) in zip(drawn, pairs):
            if f in shape:
                paint(frame, frame_size, *shape[f], RGB[colour] + bytes([TINT]))
        frames.append(frame)
    return b"".join(frames), [set(shape) for shape in drawn]


def render(clip, event, person_track, vehicle_track, fps, out_path, everyone=(), frame_size=None, vehicles=(),
           top_down=False):
    """Write the evidence clip for one event, heads of `everyone` blurred and number plates under a light mosaic
    (plate_filters: the plates SAM found, cached next to `clip` by analyze.fetch_plates, else every one of `vehicles`
    near enough for a readable plate), the two drawn as SAM silhouettes where their masks are cached next to `clip`
    (else as boxes); returns out_path."""
    first, last = window(event, fps)
    pairs = [(vehicle_track, "red"), (person_track, "cyan")]  # the pedestrian drawn last, on top
    heads = blur_filters(everyone, first, last, frame_size) if frame_size else []
    plates = plate_filters(vehicles, first, last, frame_size, cached_plates(Path(clip).parent, first, last,
                                                                            frame_size)) if frame_size else []
    tint, drawn = (silhouettes(pairs, Path(clip).parent, first, last, frame_size) if frame_size
                   else (b"", [set(), set()]))
    marks = trail_filters(person_track, event, fps, first, last, top_down) + box_filters(
        [({f: b for f, b in track.items() if f not in done}, colour) for (track, colour), done in zip(pairs, drawn)],
        first, last)
    frames = ["-frames:v", str(last - first + 1), "-an"]
    # each mosaic holds up to MAX_FILTERS drawboxes of its own, so it gets a pass of its own after the heads
    passes = [heads[k:k + MAX_FILTERS] for k in range(0, len(heads), MAX_FILTERS)] + [[m] for m in plates] or [[]]
    with tempfile.TemporaryDirectory() as tmp:
        source, start = Path(clip), f"{first / fps:.3f}"
        for k, chunk in enumerate(passes[:-1]):  # a crowd: blurred in lossless passes first, the cut's frame numbers
            done = Path(tmp) / f"pass{k}.mkv"     # (eq(n,...)) kept
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", start, "-i", str(source), "-vf", ",".join(chunk)]
                           + frames + ["-c:v", "ffv1", str(done)], check=True)
            source, start = done, "0"
        blurs = passes[-1]
        args = ["ffmpeg", "-v", "error", "-y", "-ss", start, "-i", str(source)]
        if tint:  # silhouettes go over the blurred heads, under the footsteps
            args += ["-f", "rawvideo", "-pix_fmt", "rgba", "-video_size", "{}x{}".format(*frame_size),
                     "-framerate", str(fps), "-i", "-",
                     "-filter_complex", f"[0:v]setpts=PTS-STARTPTS,{','.join(blurs) or 'null'}[v];"
                     f"[1:v]setpts=PTS-STARTPTS[s];[v][s]overlay=shortest=1,{','.join(marks) or 'null'}"]
        else:
            args += ["-vf", ",".join(blurs + marks) or "null"]
        subprocess.run(args + frames + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                                        str(out_path)], check=True, input=tint or None)
    return out_path


def speech_wav(video, start_s, seconds, wav):
    """The video's first sound track from start_s for `seconds` as Voice Transcribe's WAV (voice.to_wav's format), or
    None when the video has no sound."""
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start_s:.3f}", "-t", f"{seconds:.3f}", "-i", str(video),
                        "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(voice.SAMPLE_RATE), "-c:a", "pcm_s16le",
                        "-map_metadata", "-1", str(wav)], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        return None
    return wav


def road_sound(clip_path, video, event, fps, offset_s, api_key):
    """Give an evidence clip the video's own sound under its frames (window(); `offset_s`: where clip frame 0 is in
    `video`), with every stretch Muse Voice Transcribe hears as speech silenced (voice.muted, VOICE_PAD_S wider each
    side), horns and traffic kept; the picture is copied untouched. Its reply is kept beside the clip (event1.mp4:
    event1-voices.json) and read again while the sound is the same, so a re-run sends nothing. Returns the silenced
    [[start, end]] clip seconds, or None, the clip left silent, when the video has no sound or the call failed."""
    first, last = window(event, fps)
    start_s, seconds, clip_path = offset_s + first / fps, (last - first + 1) / fps, Path(clip_path)
    with tempfile.TemporaryDirectory() as tmp:
        wav = speech_wav(video, start_s, seconds, Path(tmp) / "speech.wav")
        silenced = None if wav is None else seal.reused(
            clip_path.with_name(f"{clip_path.stem}-voices.json"), [wav.read_bytes(), voice.MODEL, str(voice.TURNS)],
            lambda: voice.turns(wav, api_key), lambda text: voice.muted(text, seconds, VOICE_PAD_S))
        if silenced is None:
            return None
        mute = ",".join(f"volume=0:enable='between(t,{a},{b})'" for a, b in silenced) or "anull"
        out = Path(tmp) / clip_path.name
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip_path), "-ss", f"{start_s:.3f}", "-t",
                        f"{seconds:.3f}", "-i", str(video), "-map", "0:v", "-map", "1:a:0", "-c:v", "copy", "-af", mute,
                        "-c:a", "aac", "-movflags", "+faststart", str(out)], check=True)
        shutil.move(out, clip_path)
    return silenced


def copies(track, anchor, step, first, last):
    """Frames of `track` pasted into the still: `anchor` and every `step` frames out from it within first..last, each
    left out when it overlaps the last copy kept on its side more than MAX_IOU."""
    kept = [anchor] if anchor in track else []
    for sign, end in ((-1, first - 1), (1, last + 1)):
        drawn = track.get(anchor)
        for f in range(anchor + sign * step, end, sign * step):
            if f in track and (drawn is None or crowd.iou(drawn, track[f]) <= MAX_IOU):
                kept.append(f)
                drawn = track[f]
    return sorted(kept)


def crop(box, frame_size):
    """(x, y, w, h) of a box clamped to the frame, or None when the frame edge leaves under MIN_COPY_PX of it."""
    x1, y1 = max(0, round(box[0])), max(0, round(box[1]))
    x2, y2 = min(frame_size[0], round(box[2]) + 1), min(frame_size[1], round(box[3]) + 1)
    return (x1, y1, x2 - x1, y2 - y1) if min(x2 - x1, y2 - y1) >= MIN_COPY_PX else None


def one_frame(n):
    return f"trim=start_frame={n}:end_frame={n + 1},setpts=PTS-STARTPTS"


def strobe(video, event, person_track, vehicle_track, fps, frame_size, out_path):
    """A StroMotion still from the evidence clip `video` (already blurred and drawn on): its frame where the first of
    the two reached the spot, with copies of the vehicle, then the pedestrian, cut from the clip at a fixed step
    before and after, so wider spacing means faster. Returns the page's {"image", "moments", "step_s"}."""
    first, last = window(event, fps)
    step_s = CAR_STEP_S if event["vehicle"].split("#")[0] == "car" else STEP_S
    anchor = round(min(event["t_person_s"], event["t_vehicle_s"]) * fps)
    pasted = [(f, box, colour) for track, colour in ((vehicle_track, "red"), (person_track, "cyan"))
              for f in copies(track, anchor, round(step_s * fps), first, last)
              if (box := crop(track[f], frame_size))]
    chain = [f"[0:v]{one_frame(anchor - first)}[s0]"]
    for k, (f, (x, y, w, h), colour) in enumerate(pasted, 1):
        chain.append(f"[{k}:v]{one_frame(f - first)},crop={w}:{h}:{x}:{y},drawbox=color={colour}{EDGE}[c{k}];"
                     f"[s{k - 1}][c{k}]overlay={x}:{y}[s{k}]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *["-i", str(video)] * (len(pasted) + 1), "-filter_complex",
                    ";".join(chain), "-map", f"[s{len(pasted)}]", "-frames:v", "1", "-q:v", "2", str(out_path)],
                   check=True)
    return {"image": Path(out_path).name, "moments": len({anchor} | {f for f, _, _ in pasted}), "step_s": step_s}
