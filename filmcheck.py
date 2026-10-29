"""Is a phone clip shot the way FILMING.md asks? ffprobe checks of size, orientation, frame rate, HDR and sound, and
ffmpeg checks that the view held still and did not darken.
Run: python3 filmcheck.py CLIP [START END]   (START END: the site's window_s in seconds; prints "fit" or what to
change; exit code 1 when anything is off)"""
import json
import operator
import subprocess
import sys

WANT_SIZE = (1920, 1080)  # 1080p landscape, as shown after the phone's rotation flag
WANT_FPS = 30
FPS_TOLERANCE = 0.05      # 29.97 fps (30000/1001) counts as 30
MAX_AVG_FPS_DROP = 0.5    # an average this far under the set rate means the rate changed while recording
HDR_TRANSFERS = ("arib-std-b67", "smpte2084")  # HLG (iPhone HDR Video) and PQ
SPATIAL_AUDIO = ("apac", "apple_apac")         # Apple's Spatial Audio codec: its tag, and ffprobe 9's codec name
STEADY_WIDTH = 640        # frames compared at the analysis width, where calibrate.html's clicks live
STEADY_EVERY_S = 60       # one sample a minute, plus the last second
MIN_SAMPLES = 4           # a short test clip is sampled more often, so two samples in a row exist
REF_S = 1.0               # the reference frame without a window: 1 s in, after the hand has left the phone
COARSE = 4                # searched first at a quarter of that width, where +-REACH px is +-32 px at 640
REACH = 8                 # px searched either way at that quarter size
FINE_REACH = COARSE       # then +-4 px at full width around that, which covers one coarse pixel either way
ROW_STEP = 2              # every 2nd row at full width: half the time, the same answer
MAX_SHIFT_PX = 5          # a uniform 2-3 px shift costs at most 4-6% on speeds (G2 allows 15%); tune on Saturday's clip
DARK_SHARE = 0.6          # a frame under 60% of the reference's brightness: light falling under a locked exposure


def fps(fraction):
    """'30000/1001' -> 29.97; 0.0 for ffprobe's '0/0'."""
    num, _, den = fraction.partition("/")
    return float(num) / float(den) if den and float(den) else 0.0


def probe(clip):
    """ffprobe's stream list for `clip`."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(clip)],
                         check=True, capture_output=True, text=True).stdout
    if not out.strip():
        raise SystemExit(f"{clip}: ffprobe found no streams (is this a video file?)")
    return json.loads(out).get("streams", [])


def problems(streams):
    """What to change, one sentence each; [] when the clip is fit."""
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        return ["no video stream"]
    found = []
    rotation = next((d["rotation"] for d in video.get("side_data_list", []) if "rotation" in d),
                    video.get("tags", {}).get("rotate", 0))  # older ffprobe puts it in a tag
    size = (video.get("width", 0), video.get("height", 0))
    if round(float(rotation)) % 180:  # held sideways: shown with width and height swapped
        size = size[::-1]
    if size != WANT_SIZE:
        found.append(f"shown {size[0]}x{size[1]}, want {WANT_SIZE[0]}x{WANT_SIZE[1]}: 1080p, phone held landscape, "
                     "and send the original file (WhatsApp shrinks it)")
    nominal, average = fps(video.get("r_frame_rate", "0/0")), fps(video.get("avg_frame_rate", "0/0"))
    if abs(nominal - WANT_FPS) > FPS_TOLERANCE:
        found.append(f"{nominal:.2f} fps, want {WANT_FPS}: Record Video at 1080p 30 fps, Auto FPS off, "
                     "no Cinematic or Action mode")
    elif average and nominal - average > MAX_AVG_FPS_DROP:
        found.append(f"averages {average:.2f} fps against a set {nominal:.2f}: the rate changed while recording; "
                     "turn Auto FPS off")
    if video.get("color_transfer") in HDR_TRANSFERS:
        found.append("recorded in HDR: Settings > Camera > Record Video > HDR Video off (HDR colours come out dark "
                     "and washed out in the clips, the street photo and what SAM sees)")
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if not audio:
        found.append("no sound track: record with sound, so Muse Wonder can hear horns and brakes")
    elif any(s.get("codec_tag_string") in SPATIAL_AUDIO or s.get("codec_name") in SPATIAL_AUDIO for s in audio):
        found.append("a Spatial Audio track (apac), which ffmpeg cannot decode: Settings > Camera > Record Sound > "
                     "Stereo")
    return found


def gray(clip, t):
    """The frame at `t` s as grey bytes, STEADY_WIDTH wide and as displayed; b"" past the end."""
    return subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(clip), "-frames:v", "1", "-vf",
                           f"scale={STEADY_WIDTH}:-2,format=gray", "-f", "rawvideo", "-"],
                          check=True, capture_output=True).stdout


def around(reach, centre=(0, 0)):
    """Every (dx, dy) within `reach` of `centre`, nearest first, so a tie reads as the smaller move."""
    steps = sorted(((dx, dy) for dx in range(-reach, reach + 1) for dy in range(-reach, reach + 1)),
                   key=lambda s: abs(s[0]) + abs(s[1]))
    return [(centre[0] + dx, centre[1] + dy) for dx, dy in steps]


def best_shift(ref, img, width, shifts, row_step=1):
    """The (dx, dy) of `shifts` that best lays `img` on `ref` (grey bytes, `width` wide): the least summed grey
    difference over the part of the frame every shift keeps in view. Traffic adds about the same difference at every
    shift, so the still street decides."""
    height, edge = len(ref) // width, max(max(abs(dx), abs(dy)) for dx, dy in shifts)

    def cost(dx, dy):
        return sum(sum(map(abs, map(operator.sub, ref[y * width + edge:(y + 1) * width - edge],
                                    img[(y + dy) * width + edge + dx:(y + dy + 1) * width - edge + dx])))
                   for y in range(edge, height - edge, row_step))
    return min(shifts, key=lambda s: cost(*s))


def shrink(img, width):
    """`img` (grey bytes, `width` wide) at 1/COARSE the size: the mean of each COARSE x COARSE block."""
    small = []
    for y in range(0, len(img) // width - COARSE + 1, COARSE):
        block = [img[(y + j) * width + i:(y + j + 1) * width:COARSE] for j in range(COARSE) for i in range(COARSE)]
        small.append(bytes(sum(pixels) // COARSE ** 2 for pixels in zip(*block)))
    return b"".join(small)


def shift(ref, img):
    """How far the view moved from `ref` to `img` (grey bytes STEADY_WIDTH wide), (dx, dy) px: searched at 1/COARSE
    size, then refined at full size. Searching small patches instead read 20 and 40 px moves as 0-4 px.
    ponytail: a move past about 36 px (knocked to another view) can read as any shift; add a wider coarse search
    if Saturday's clip shows one."""
    cx, cy = best_shift(shrink(ref, STEADY_WIDTH), shrink(img, STEADY_WIDTH), STEADY_WIDTH // COARSE, around(REACH))
    return best_shift(ref, img, STEADY_WIDTH, around(FINE_REACH, (COARSE * cx, COARSE * cy)), ROW_STEP)


def summary(seen):
    """{max_shift_px, at_s, moved, dx_dy} from (t, dx, dy) samples. A move needs 2 samples in a row over MAX_SHIFT_PX,
    so one sway or passing bus is not one; at_s is the first of them, else the sample with the largest shift."""
    size = [max(abs(dx), abs(dy)) for _, dx, dy in seen]
    over = [i for i in range(len(seen) - 1) if min(size[i], size[i + 1]) > MAX_SHIFT_PX]
    at = over[0] if over else max(range(len(seen)), key=size.__getitem__, default=None)
    return {"max_shift_px": max(size, default=0), "at_s": None if at is None else seen[at][0], "moved": bool(over),
            "dx_dy": None if at is None else list(seen[at][1:])}


def steadiness(clip, start, end, every=STEADY_EVERY_S):
    """How still the view held from `start` to `end` s: a frame every `every` s and the last second, each against
    the frame at `start` (where the calibration was clicked). summary()'s dict, plus darker_pct and dark_at_s when a
    frame fell under DARK_SHARE of the reference's brightness: the check stops there, as a dark frame cannot be
    matched."""
    ref, seen = gray(clip, start), []
    step = min(every, (end - start) / MIN_SAMPLES)
    times = [start + step * k for k in range(1, int((end - start) / step) + 1) if start + step * k < end - 1]
    for t in [*times, end - 1]:
        img = gray(clip, t)
        if len(img) != len(ref):  # past the real end there is no frame; it would read as all black
            continue
        if sum(img) < DARK_SHARE * sum(ref):
            return {**summary(seen), "darker_pct": round(100 - 100 * sum(img) / sum(ref)), "dark_at_s": t}
        seen.append((t, *shift(ref, img)))
    return summary(seen)


def clock(seconds):
    """142.6 -> '2:22' (minutes:seconds into the recording)."""
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def camera_lines(held):
    """(what to change, one sentence each; the measured shift, said without calling it a problem)."""
    found = []
    if held["moved"]:
        found.append("the view moved {:+d}, {:+d} px (of {}) by {}: the phone was knocked or sagged, and the "
                     "calibration holds only before that: re-shoot, or set window_s to end before the move"
                     .format(*held["dx_dy"], STEADY_WIDTH, clock(held["at_s"])))
    if "darker_pct" in held:
        found.append(f"the picture is {held['darker_pct']}% darker by {clock(held['dark_at_s'])} (the steadiness "
                     "check stopped there): light is falling under the locked exposure; film earlier, or end window_s "
                     "before it")
    if held["moved"] or held["at_s"] is None:
        return found, ""
    return found, (f"camera: largest shift {held['max_shift_px']} px (of {STEADY_WIDTH}) at {clock(held['at_s'])}; "
                   f"a move is over {MAX_SHIFT_PX} px on two samples in a row")


def main(clip, window=None):
    try:
        streams = probe(clip)
        found = problems(streams)
        seconds = float(next((s.get("duration") for s in streams if s.get("codec_type") == "video"), 0) or 0)
        start, end = window or (REF_S, seconds)
        if end > seconds:
            found.append(f"window_s ends at {end:g} s, after the recording's end at {seconds:.1f} s")
        held = steadiness(clip, start, min(end, seconds)) if min(end, seconds) - start >= 2 else None
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"{clip}: ffprobe or ffmpeg could not read it: {error.stderr.strip()}")
    moved, note = camera_lines(held) if held else ([], "")
    found = found + moved
    print("\n".join([*(f"- {p}" for p in found), *([note] if note else [])]))
    if not found:
        print("fit: 1920x1080 landscape, 30 fps, SDR, with sound" + ("; the view held still" if held else "")
              + ". By eye: the 1x lens.")
    return 1 if found else 0


if __name__ == "__main__":
    if len(sys.argv) not in (2, 4) or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        sys.exit(0 if len(sys.argv) == 2 else 2)
    window = tuple(map(float, sys.argv[2:])) or None
    if window and not 0 <= window[0] < window[1]:
        raise SystemExit(f"window {window}: want START END with 0 <= START < END (seconds)")
    sys.exit(main(sys.argv[1], window))
