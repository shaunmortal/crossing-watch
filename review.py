"""Muse Spark's second look at each near-miss: is the tracked "pedestrian" really a person, and who
(child, elderly, wheelchair user...). Catches SAM calling a pole a person, which the geometry cannot.

Spark sees a zoomed crop of the frame where that track's box is largest: at the near-miss itself the person is
often half hidden by the vehicle and only a few pixels big, which made Spark reject real people (DUT drone test)."""
import base64
import http.client
import json
import re
import subprocess
import urllib.request

import sam

MODEL = "muse-spark-1.3"
TIMEOUT_S = 120
CROP_FACTOR = 3     # crop this many box-sizes around the person
MIN_CROP_PX = 80
CROP_OUT_PX = 384   # upscaled so a small person is visible
ROAD_USERS = {"child", "adult", "elderly", "wheelchair user", "cyclist", "not a person", "unclear"}
VIEWS = {False: "a traffic camera looking down at a street crossing at an angle",
         True: "a drone looking straight down on a street crossing; people look like small heads and shoulders from above"}
PROMPT = ('Zoomed crop from {view}. Is the thing in the thin CYAN box a person (pedestrian)? Reply JSON only: '
          '{{"cyan_is_a_person": true|false, "road_user": "child"|"adult"|"elderly"|"wheelchair user"|"cyclist"|'
          '"not a person"|"unclear", "reason": "<one sentence>"}}')


def read_verdict(text):
    """The validated verdict in a model reply, or None."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match[0])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("cyan_is_a_person"), bool) \
            or data.get("road_user") not in ROAD_USERS:
        return None
    is_person = data["cyan_is_a_person"] and data["road_user"] != "not a person"  # contradictions count as no
    return {"is_person": is_person, "road_user": data["road_user"],
            "reason": str(data.get("reason", ""))[:200]}


def crop_window(box, frame_size):
    """(x, y, side) of a square crop CROP_FACTOR box-sizes wide around the box, kept inside the frame."""
    side = min(max(MIN_CROP_PX, CROP_FACTOR * max(box[2] - box[0], box[3] - box[1])), *frame_size)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    x = max(0, min(frame_size[0] - side, cx - side / 2))
    y = max(0, min(frame_size[1] - side, cy - side / 2))
    return int(x), int(y), int(side)


def person_crop(clip, person_track, frame_size, out_path):
    """JPEG crop of the frame where the person's box is largest, the box drawn in cyan."""
    frame, box = max(person_track.items(), key=lambda kv: (kv[1][2] - kv[1][0]) * (kv[1][3] - kv[1][1]))
    x, y, side = crop_window(box, frame_size)
    outline = f"drawbox=x={box[0] - x:.0f}:y={box[1] - y:.0f}:w={box[2] - box[0]:.0f}:h={box[3] - box[1]:.0f}:color=cyan:t=1"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf",
                    f"select=eq(n\\,{frame}),crop={side}:{side}:{x}:{y},{outline},"
                    f"scale={CROP_OUT_PX}:{CROP_OUT_PX}:flags=lanczos", "-frames:v", "1", str(out_path)], check=True)
    return out_path


def ask(image_path, api_key, top_down=False):
    url = "data:image/jpeg;base64," + base64.b64encode(image_path.read_bytes()).decode()
    body = json.dumps({"model": MODEL, "reasoning": {"effort": "minimal"}, "input": [{"role": "user", "content": [
        {"type": "input_text", "text": PROMPT.format(view=VIEWS[top_down])},
        {"type": "input_image", "image_url": url}]}]}).encode()
    req = urllib.request.Request(sam.API_URL, data=body, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
            reply = json.load(response)
    except (OSError, ValueError, http.client.HTTPException) as err:  # URLError and JSONDecodeError included
        print(f"review failed for {image_path.name}: {err}", flush=True)
        return None
    text = "".join(c.get("text", "") for o in reply.get("output", []) if o.get("type") == "message"
                   for c in o.get("content", []) if isinstance(c, dict)) if isinstance(reply, dict) else ""
    return read_verdict(text)


def review(clip, person_track, frame_size, out_path, api_key, top_down=False):
    """Spark's verdict on one tracked pedestrian (None if the call or its reply failed)."""
    if not person_track:
        return None
    return ask(person_crop(clip, person_track, frame_size, out_path), api_key, top_down)
