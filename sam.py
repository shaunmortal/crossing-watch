"""SAM 3.1 video tracking through the Meta Model API: one concept ("person", "car", ...) per request."""
import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.meta.ai/v1/responses"
MODEL = "sam-3.1"
TIMEOUT_S = 600
MAX_OBJECTS = 16  # one video request tracks at most this many objects in all; once they are taken, later
                  # arrivals are never picked up (no reply among 54 had more, and none gained an ID after filling)
ENV_FILE = Path(__file__).parent / ".env"
FRAME = re.compile(r"<(\d+)f>")
BOX = re.compile(r"(\d+)<\|box;x1=([\d.]+);y1=([\d.]+);x2=([\d.]+);y2=([\d.]+)")


def load_api_key():
    key = os.environ.get("MODEL_API_KEY", "")
    if not key and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "MODEL_API_KEY":
                key = value.strip()
    if not key:
        raise SystemExit(f"MODEL_API_KEY is missing: set it in the environment or in {ENV_FILE}")
    return key


def parse(text):
    """SAM's streamed text -> {track_id: {frame: [x1, y1, x2, y2]}} in clip pixels."""
    parts = FRAME.split(text)
    tracks = {}
    for i in range(1, len(parts) - 1, 2):
        frame = int(parts[i])
        for obj, *box in BOX.findall(parts[i + 1]):
            x1, y1, x2, y2 = (float(v) for v in box)
            if x2 > x1 and y2 > y1:  # SAM sometimes emits empty boxes
                tracks.setdefault(obj, {})[frame] = [x1, y1, x2, y2]
    return tracks


def saturation_frame(tracks):
    """The frame on which a video reply's MAX_OBJECTS-th object first appeared (`tracks` from parse), or None if it
    never filled: from then on, newcomers were not tracked."""
    firsts = sorted(min(track) for track in tracks.values())
    return firsts[MAX_OBJECTS - 1] if len(firsts) >= MAX_OBJECTS else None


def request(video, concept, api_key):
    """Raw streamed text for one concept tracked through an MP4 (H.264, faststart)."""
    url = "data:video/mp4;base64," + base64.b64encode(Path(video).read_bytes()).decode()
    body = json.dumps({"model": MODEL, "stream": True, "metadata": {"mask_encoding": "one_bit"},
                       "input": [{"type": "message", "role": "user", "content": [
                           {"type": "input_text", "text": concept}, {"type": "input_video", "video_url": url}]}]}).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    chunks, completed = [], False
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
            for raw in response:
                line = raw.decode().strip()
                if not line.startswith("data:") or line[5:].strip() in ("", "[DONE]"):
                    continue
                event = json.loads(line[5:])
                kind = event.get("type")
                if kind == "error":
                    raise RuntimeError(f"SAM error for {concept!r}: {event}")
                if kind == "response.output_text.delta":
                    chunks.append(event["delta"])
                completed = completed or kind == "response.completed"
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"SAM request for {concept!r} failed: {err.code} {err.read()[:300]!r}") from err
    if not completed:
        raise RuntimeError(f"SAM stream for {concept!r} ended before response.completed")
    return "".join(chunks)  # empty when nothing matching the concept was seen


def cache_path(cache_dir, concept):
    return Path(cache_dir) / f"{re.sub(r'[^A-Za-z0-9]+', '_', concept)}.sam.txt"


def track(video, concept, api_key, cache_dir):
    """Tracks for one concept, re-using the cached SAM reply for this clip when there is one."""
    cache = cache_path(cache_dir, concept)
    if not cache.exists():
        cache.write_text(request(video, concept, api_key))
    return parse(cache.read_text())
