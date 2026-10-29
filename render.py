"""Evidence clips: a few seconds around each near-miss, with the pedestrian drawn cyan and the vehicle red (as SAM's
own silhouettes where its masks are cached, else as boxes), the pedestrian's footsteps dotted cyan up to a yellow spot
where the two met, and every person's head blurred so clips of children can be shared.
Captions (PET, gap, speed) are shown by the evidence page, since this ffmpeg build has no text filter."""
import subprocess
from pathlib import Path

import masks

PAD_S = 2.0
HEAD_SHARE = 0.3   # the top 30% of a person box holds the head
MIN_BLUR_PX = 3    # heads smaller than this are unrecognisable anyway, and delogo needs room
TRAIL_STEP = 2     # a footstep dot every 2nd frame
DOT_PX = 6         # footstep dot size
SPOT_PX = 14       # the meeting spot, larger than a footstep
TINT = 89          # silhouettes are filled at 35% (of 255), so the street shows through
HOLD_FRAMES = 1    # crowd mode finds people every 2nd frame: the frame between borrows its neighbour's mask
RGB = {"cyan": b"\x00\xff\xff", "red": b"\xff\x00\x00"}


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


def render(clip, event, person_track, vehicle_track, fps, out_path, everyone=(), frame_size=None, top_down=False):
    """Write the evidence clip for one event, heads of `everyone` blurred, the two drawn as SAM silhouettes where
    their masks are cached next to `clip` (else as boxes); returns out_path."""
    first, last = window(event, fps)
    pairs = [(vehicle_track, "red"), (person_track, "cyan")]  # the pedestrian drawn last, on top
    blurs = blur_filters(everyone, first, last, frame_size) if frame_size else []
    tint, drawn = (silhouettes(pairs, Path(clip).parent, first, last, frame_size) if frame_size
                   else (b"", [set(), set()]))
    marks = trail_filters(person_track, event, fps, first, last, top_down) + box_filters(
        [({f: b for f, b in track.items() if f not in done}, colour) for (track, colour), done in zip(pairs, drawn)],
        first, last)
    args = ["ffmpeg", "-v", "error", "-y", "-ss", f"{first / fps:.3f}", "-i", str(clip)]
    if tint:  # silhouettes go over the blurred heads, under the footsteps
        args += ["-f", "rawvideo", "-pix_fmt", "rgba", "-video_size", "{}x{}".format(*frame_size),
                 "-framerate", str(fps), "-i", "-",
                 "-filter_complex", f"[0:v]setpts=PTS-STARTPTS,{','.join(blurs) or 'null'}[v];"
                 f"[1:v]setpts=PTS-STARTPTS[s];[v][s]overlay=shortest=1,{','.join(marks) or 'null'}"]
    else:
        args += ["-vf", ",".join(blurs + marks) or "null"]
    subprocess.run(args + ["-frames:v", str(last - first + 1), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                           "-movflags", "+faststart", str(out_path)], check=True, input=tint or None)
    return out_path

