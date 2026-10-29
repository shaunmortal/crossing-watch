"""Is a phone clip shot the way FILMING.md asks? ffprobe checks of size, orientation, frame rate and sound.
Run: python3 filmcheck.py CLIP   (prints "fit" or what to change; exit code 1 when anything is off)"""
import json
import subprocess
import sys

WANT_SIZE = (1920, 1080)  # 1080p landscape, as shown after the phone's rotation flag
WANT_FPS = 30
FPS_TOLERANCE = 0.05      # 29.97 fps (30000/1001) counts as 30
MAX_AVG_FPS_DROP = 0.5    # an average this far under the set rate means the rate changed while recording


def fps(fraction):
    """'30000/1001' -> 29.97; 0.0 for ffprobe's '0/0'."""
    num, _, den = fraction.partition("/")
    return float(num) / float(den) if den and float(den) else 0.0


def probe(clip):
    """ffprobe's stream list for `clip`."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(clip)],
                         check=True, capture_output=True, text=True).stdout
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
    if not any(s.get("codec_type") == "audio" for s in streams):
        found.append("no sound track: record with sound, so Muse Wonder can hear horns and brakes")
    return found


def main(clip):
    try:
        found = problems(probe(clip))
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"{clip}: ffprobe could not read it: {error.stderr.strip()}")
    print("\n".join(f"- {p}" for p in found) or
          "fit: 1920x1080 landscape, 30 fps, with sound. By eye: the 1x lens, and the phone did not move.")
    return 1 if found else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1]))
