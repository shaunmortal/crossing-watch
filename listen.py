"""Muse Wonder listens around each near-miss: horns, screeching brakes and shouts are a second, independent
witness that something nearly happened (CCTV usually has no sound; a phone recording does)."""
import base64
import http.client
import json
import re
import subprocess
import urllib.request

import sam

MODEL = "muse-wonder-1.0"
TIMEOUT_S = 120
PAD_S = 3.0
SAMPLE_RATE = 16_000
MIN_WAV_BYTES = 1000  # less than this is a header with no sound
SOUNDS = {"horn", "brakes", "shout", "crash"}
PROMPT = ("This is {seconds:.0f} seconds of street audio around a moment when a vehicle passed very close to a "
          "pedestrian. List only the vehicle horns, screeching brakes, shouts or crash sounds you clearly hear; "
          "leave out engines, traffic hum and normal talking. Reply JSON only: "
          '{{"sounds": [{{"t_s": <seconds from the start of this audio>, "sound": "horn"|"brakes"|"shout"|"crash"}}]}}')


def read_sounds(text, seconds):
    """Validated [{t_s, sound}] from Wonder's reply, or None if the reply is unusable."""
    match = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(match[0]) if match else None
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("sounds"), list):
        return None
    return [{"t_s": round(float(s["t_s"]), 1), "sound": s["sound"]} for s in data["sounds"]
            if isinstance(s, dict) and s.get("sound") in SOUNDS
            and isinstance(s.get("t_s"), (int, float)) and 0 <= s["t_s"] <= seconds]


def audio_around(video, t_s, out_path):
    """(mono 16 kHz WAV of PAD_S either side of t_s from the original video, its start time); the path is None
    when the video has no sound. Only the first audio track is read: an iPhone's Spatial Audio file also holds a
    4-channel APAC track, which ffmpeg would pick (most channels) and cannot decode."""
    start = max(0.0, t_s - PAD_S)
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-t", f"{2 * PAD_S:.2f}", "-i", str(video),
                        "-map", "0:a:0?", "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), str(out_path)], check=True,
                       capture_output=True)
    except subprocess.CalledProcessError:
        return None, start
    return (out_path if out_path.stat().st_size >= MIN_WAV_BYTES else None), start


def listen(video, event, out_path, api_key, offset_s=0.0):
    """Sounds heard around the event, times relative to the near-miss (negative = before); None if there is no
    audio or the call failed. `offset_s`: where the analysed clip starts in `video` (window_s)."""
    t_s = min(event["t_person_s"], event["t_vehicle_s"]) + offset_s
    wav, start = audio_around(video, t_s, out_path)
    if wav is None:
        return None
    seconds = 2 * PAD_S
    body = json.dumps({"model": MODEL, "reasoning": {"effort": "minimal"}, "input": [{"role": "user", "content": [
        {"type": "input_text", "text": PROMPT.format(seconds=seconds)},
        {"type": "input_file", "filename": "street.wav",
         "file_data": "data:audio/wav;base64," + base64.b64encode(wav.read_bytes()).decode()}]}]}).encode()
    req = urllib.request.Request(sam.API_URL, data=body, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
            reply = json.load(response)
    except (OSError, ValueError, http.client.HTTPException) as err:
        print(f"listening failed for {wav.name}: {err}", flush=True)
        return None
    text = "".join(c.get("text", "") for o in reply.get("output", []) if o.get("type") == "message"
                   for c in o.get("content", []) if isinstance(c, dict)) if isinstance(reply, dict) else ""
    heard = read_sounds(text, seconds)
    if heard is None:
        return None
    return [{"t_s": round(start + s["t_s"] - t_s, 1), "sound": s["sound"]} for s in heard]
