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

import openweights
import road
import sam
import seal

# Standard mode only: never a -contributor id (Meta trains on Contributor-mode content).
MODEL = "muse-spark-1.3"
# opt-in, for measuring an open-weights reviewer in Spark's place (validate_offline.py --reviewer open): any
# OpenAI-compatible chat server that takes images, e.g. Fireworks' https://api.fireworks.ai/inference/v1. Same prompt,
# same read_verdict; its replies are saved beside the crop as .open.json, so Spark's saved .json replies stay as they are.
OPEN_URL = sam.env_value("REVIEW_MODEL_URL")
OPEN_MODEL = sam.env_value("REVIEW_MODEL") or "accounts/fireworks/models/muse-spark-open"
OPEN_KEY = sam.env_value("REVIEW_MODEL_KEY")  # its own key, else FIREWORKS_API_KEY on Fireworks only (openweights)
OPEN_EFFORT = "low"  # reasoning_effort, sent to Fireworks only, as pack.JUDGE_EFFORT
TIMEOUT_S = 120
CROP_FACTOR = 3     # crop this many box-sizes around the person
MIN_CROP_PX = 80
CROP_OUT_PX = 384   # upscaled so a small person is visible
BOX_PX = 2          # the cyan box is drawn after upscaling, this thick...
BOX_PAD_PX = 4      # ...and this far outside the person, so no cyan smears onto them
REASON_CHARS = 70   # Spark's reason is shown cut to this...
LINE_COLS = 100     # ...and a printed line to this, so it fits a terminal at 18-20 pt in a screen recording
ROAD_USERS = {"child", "adult", "elderly", "wheelchair user", "rider", "cyclist", "not a person", "unclear"}
NOT_PEDESTRIANS = {"not a person", "rider", "cyclist"}  # riders are vehicles here, as bicycles are in SinD
RIDER_VERDICTS = {"rider", "cyclist"}
RIDEABLE = {"motorcycle", "bicycle", "scooter", "auto rickshaw",  # vehicle concepts a person can ride on or in;
            "vehicle"}  # the single concept "vehicle" covers two-wheelers too, so its boxes count
RIDER_GATE_SHARE = 0.3  # a rider call stands only if the person's box is this much inside a rideable box
RIDE_KMH = 8            # ...or if the person's median speed is over this: faster than a walk
WALK_KMH = (1.5, 8)     # a "not a person" piece walking at a median speed in this band...
WALK_MIN_M = 2          # ...that moved this far start to end is kept (review_disputed)...
SHADOW_M = 1.5          # ...unless another piece stays this close on most of its frames: then it is that walker's shadow
VIEWS = {False: "a traffic camera looking down at a street crossing at an angle",
         True: "a drone looking straight down on a street crossing; people look like small heads and shoulders from above"}
PROMPT = ('Zoomed crop from {view}. Is the thing in the thin CYAN box a pedestrian on foot? Someone riding or sitting '
          'on a bicycle, motorcycle or scooter, or in a vehicle, is a "rider", not a pedestrian. Reply JSON only: '
          '{{"cyan_is_a_pedestrian": true|false, "road_user": "child"|"adult"|"elderly"|"wheelchair user"|"rider"|'
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
    if not isinstance(data, dict) or not isinstance(data.get("cyan_is_a_pedestrian"), bool) \
            or data.get("road_user") not in ROAD_USERS:
        return None
    is_person = data["cyan_is_a_pedestrian"] and data["road_user"] not in NOT_PEDESTRIANS  # contradictions: no
    return {"is_person": is_person, "road_user": data["road_user"],
            "reason": str(data.get("reason", ""))[:200]}


def gated(verdict, person_boxes, rideables, walk_kmh=None, moved_m=0.0, beside=False):
    """Spark's verdict, except that "rider" or "cyclist" rejects the person only when SAM found a rideable vehicle
    under them: their box RIDER_GATE_SHARE or more inside its box on the same frame, feet no lower than its bottom
    plus road.RIDER_FEET_PX (road.without_riders' rule: a walker passing in front of a parked bike has lower feet).
    Otherwise they stay a pedestrian, marked rider_unconfirmed (on the DUT drone test Spark called walking students
    riders). "unclear" keeps the person too, marked review_unclear: only a sure "no" rejects (a rule set after seeing
    3 DUT cases, not checked on held-out data). A rider call over RIDE_KMH stands without a bike box. Any other "no"
stands unless the piece walked (WALK_KMH, WALK_MIN_M) with no other piece beside it (`beside`, within SHADOW_M on
most frames): then it is kept, marked review_disputed (on DUT, Spark's "not a person" was 0 for 6, all walkers; a
rule set after seeing those DUT cases, its first held-out test is new footage)."""
    if verdict and not verdict["is_person"] and verdict["road_user"] == "unclear":
        return {**verdict, "is_person": True, "review_unclear": True}
    if not verdict or verdict["is_person"]:
        return verdict
    if verdict["road_user"] not in RIDER_VERDICTS:
        walking = walk_kmh is not None and WALK_KMH[0] <= walk_kmh <= WALK_KMH[1] and moved_m >= WALK_MIN_M
        return {**verdict, "is_person": True, "review_disputed": True, "walk_kmh": walk_kmh} \
            if walking and not beside else verdict
    share = max((road.inside_share(b, w[f]) for w in rideables for f, b in person_boxes.items()
                 if f in w and b[3] <= w[f][3] + road.RIDER_FEET_PX), default=0.0)
    if share >= RIDER_GATE_SHARE or (walk_kmh or 0) > RIDE_KMH:
        return verdict
    return {**verdict, "is_person": True, "rider_unconfirmed": True, "walk_kmh": walk_kmh}


def unconfirmed_rider(verdict):
    """How a page names someone Spark called a rider with no bike under them, or a walker it called not a person
    (review_disputed), or None for any other verdict."""
    verdict = verdict or {}
    walk = "" if verdict.get("walk_kmh") is None else f"; measured walking {verdict['walk_kmh']} km/h"
    if verdict.get("review_disputed"):
        return f"pedestrian (Spark thought {verdict['road_user']}; kept{walk})"
    if not verdict.get("rider_unconfirmed"):
        return None
    return f"pedestrian (Spark thought {verdict['road_user']}; no bike found under them{walk})"


def public_reason(reason, chars=REASON_CHARS):
    """Spark's reason as it may be shown: cut to `chars`, or "" when it holds a digit (a number plate could be in
    it)."""
    reason = " ".join(str(reason or "").split())
    if any(c.isdigit() for c in reason):
        return ""
    return reason if len(reason) <= chars else reason[:chars - 3].rstrip() + "..."


def said(pid, verdict):
    """The terminal line for a track Spark's gated verdict removed, or None when it was kept or not reviewed."""
    if not verdict or verdict["is_person"]:
        return None
    why = (f"{verdict['road_user']}, bike box under them" if verdict["road_user"] in RIDER_VERDICTS
           else "not a pedestrian")
    line = f"{reviewer()}: track {pid} removed: {why}"
    reason = public_reason(verdict.get("reason"), min(REASON_CHARS, LINE_COLS - len(line) - len(' ("")')))
    return line + (f' ("{reason}")' if reason else "")


def crop_window(box, frame_size):
    """(x, y, side) of a square crop CROP_FACTOR box-sizes wide around the box, kept inside the frame."""
    side = min(max(MIN_CROP_PX, CROP_FACTOR * max(box[2] - box[0], box[3] - box[1])), *frame_size)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    x = max(0, min(frame_size[0] - side, cx - side / 2))
    y = max(0, min(frame_size[1] - side, cy - side / 2))
    return int(x), int(y), int(side)


def person_crop(clip, person_track, frame_size, out_path):
    """JPEG crop of the frame where the person's box is largest, upscaled, then the box drawn in cyan."""
    frame, box = max(person_track.items(), key=lambda kv: (kv[1][2] - kv[1][0]) * (kv[1][3] - kv[1][1]))
    x, y, side = crop_window(box, frame_size)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf",
                    f"select=eq(n\\,{frame}),crop={side}:{side}:{x}:{y},"
                    f"scale={CROP_OUT_PX}:{CROP_OUT_PX}:flags=lanczos,{outline(box, x, y, side)}",
                    "-frames:v", "1", str(out_path)], check=True)
    return out_path


def outline(box, x, y, side):
    """ffmpeg drawbox for `box` (frame pixels) on the (x, y, side) crop once upscaled to CROP_OUT_PX: BOX_PX thick,
    BOX_PAD_PX outside the person. Drawn before upscaling, a 1 px line grew into a thick, blurred band on their edges."""
    k = CROP_OUT_PX / side
    left, top = (box[0] - x) * k - BOX_PAD_PX, (box[1] - y) * k - BOX_PAD_PX
    width, height = (box[2] - box[0]) * k + 2 * BOX_PAD_PX, (box[3] - box[1]) * k + 2 * BOX_PAD_PX
    return f"drawbox=x={left:.0f}:y={top:.0f}:w={width:.0f}:h={height:.0f}:color=cyan:t={BOX_PX}"


def reviewer():
    """Who reviews, as a terminal line names them: the REVIEW_MODEL_URL model when one is set, else Muse Spark."""
    return openweights.name(OPEN_MODEL) if OPEN_URL else "Muse Spark"


def reply_path(crop):
    """Where the reviewer's reply about `crop` is saved: .json for Spark, .open.json for a REVIEW_MODEL_URL model."""
    return crop.with_suffix(".open.json" if OPEN_URL else ".json")


def ask(image_path, api_key, top_down=False):
    """Spark's raw reply text about one crop ("" when it held no message), or None if the call failed. With
    REVIEW_MODEL_URL set, the open model's reply instead (ask_open); `api_key` is then not sent anywhere."""
    if OPEN_URL:
        return ask_open(image_path, top_down)
    url = "data:image/jpeg;base64," + base64.b64encode(image_path.read_bytes()).decode()
    body = json.dumps({"model": MODEL, "reasoning": {"effort": "minimal"}, "text": {"format": {"type": "json_object"}},
                       "input": [{"role": "user", "content": [
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
    return "".join(c.get("text", "") for o in reply.get("output", []) if o.get("type") == "message"
                   for c in o.get("content", []) if isinstance(c, dict)) if isinstance(reply, dict) else ""


def ask_open(image_path, top_down=False):
    """The REVIEW_MODEL_URL model's reply text about one crop, on the same prompt as Spark's, or None if the call
    failed. JSON object format, as Spark is asked; the key goes to that server only (openweights.server_key)."""
    url = "data:image/jpeg;base64," + base64.b64encode(image_path.read_bytes()).decode()
    body = {"model": OPEN_MODEL, "response_format": {"type": "json_object"},
            **({"reasoning_effort": OPEN_EFFORT} if openweights.host(OPEN_URL) == openweights.FIREWORKS_HOST else {}),
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT.format(view=VIEWS[top_down])},
                {"type": "image_url", "image_url": {"url": url}}]}]}
    try:
        answer = openweights.post(OPEN_URL, openweights.server_key(OPEN_URL, OPEN_KEY), body)
        usage = answer.get("usage") or {}
        print(f"open review {image_path.name}: {usage.get('prompt_tokens', '?')} in, "
              f"{usage.get('completion_tokens', '?')} out", flush=True)
        return answer["choices"][0]["message"]["content"] or ""
    except (OSError, ValueError, http.client.HTTPException, KeyError, IndexError, TypeError, AttributeError) as err:
        print(f"open review failed for {image_path.name}: {err}", flush=True)
        return None


def review(clip, person_track, frame_size, out_path, api_key, top_down=False):
    """Spark's verdict on one tracked pedestrian (None if the call or its reply failed). Its reply is kept beside the
    crop (`out_path` as .json, or .open.json for a REVIEW_MODEL_URL model) and read again while the crop, model and
    prompt are the same, so a re-run neither pays again nor changes the counts a signed letter quotes; delete the
    .json to make Spark look again."""
    if not person_track:
        return None
    crop = person_crop(clip, person_track, frame_size, out_path)
    model = OPEN_MODEL if OPEN_URL else MODEL
    return seal.reused(reply_path(out_path), [crop.read_bytes(), model, PROMPT, VIEWS[top_down]],
                       lambda: ask(crop, api_key, top_down), read_verdict)
