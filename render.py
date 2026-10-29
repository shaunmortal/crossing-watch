"""Evidence clips: a few seconds around each near-miss, with the pedestrian boxed cyan and the vehicle red, and
every person's head blurred so clips of children can be shared.
Captions (PET, gap, speed) are shown by the evidence page, since this ffmpeg build has no text filter."""
import subprocess

PAD_S = 2.0
HEAD_SHARE = 0.3   # the top 30% of a person box holds the head
MIN_BLUR_PX = 3    # heads smaller than this are unrecognisable anyway, and delogo needs room


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


def window(event, fps):
    """(first, last) clip frames of an event's evidence clip: PAD_S before the first of the pedestrian and the
    vehicle reached the spot to PAD_S after the second did, so a close pass still shows the vehicle arriving."""
    times = event["t_person_s"], event["t_vehicle_s"]
    return max(0, round(min(times) * fps) - round(PAD_S * fps)), round(max(times) * fps) + round(PAD_S * fps)


def render(clip, event, person_track, vehicle_track, fps, out_path, everyone=(), frame_size=None):
    """Write the evidence clip for one event, heads of `everyone` blurred; returns out_path."""
    first, last = window(event, fps)
    blurs = blur_filters(everyone, first, last, frame_size) if frame_size else []
    filters = ",".join(blurs + box_filters([(person_track, "cyan"), (vehicle_track, "red")], first, last)) or "null"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{first / fps:.3f}", "-i", str(clip),
                    "-frames:v", str(last - first + 1), "-vf", filters, "-an", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)], check=True)
    return out_path
