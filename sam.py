"""SAM 3.1 video tracking through the Meta Model API: one concept ("person", "car", ...) per request."""
import base64
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API_URL = "https://api.meta.ai/v1/responses"
MODEL = "sam-3.1"
TIMEOUT_S = 600
RETRY_WAITS_S = (10, 30, 90)  # a failed request is sent again after each wait: a wifi drop must not end a 2-hour run
PROGRESS_EVERY = {"video": 25, "image": 250}  # a progress line per this many new replies (at 25, a crowd run's
                                              # images would print about 2,100 lines)
SAVED, SAVED_LOCK = {}, threading.Lock()  # new replies this run by kind, counted across worker threads
MAX_OBJECTS = 16  # one video request tracks at most this many objects in all; once they are taken, later
                  # arrivals are never picked up (no reply among 54 had more, and none gained an ID after filling)
ENV_FILE = Path(__file__).parent / ".env"
FRAME = re.compile(r"<(\d+)f>")
BOX = re.compile(r"(\d+)<\|box;x1=([\d.]+);y1=([\d.]+);x2=([\d.]+);y2=([\d.]+)")


def env_value(name):
    """`name` from the environment, else from .env, else ""."""
    value = os.environ.get(name, "")
    if not value and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            key, _, found = line.partition("=")
            if key.strip() == name:
                value = found.strip()
    return value


def load_api_key():
    key = env_value("MODEL_API_KEY")
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


def is_final(err):
    """A refusal no retry can change: an HTTP 4xx (bad key, no credits, bad request, too large), except 408 and
    429."""
    code = getattr(err.__cause__, "code", None) or getattr(err, "code", None)
    return isinstance(code, int) and 400 <= code < 500 and code not in (408, 429)


def asked_wait_s(err):
    """The seconds an HTTP error's Retry-After asks for (Meta sends 60 with a 503), else 0."""
    headers = getattr(err.__cause__, "headers", None) or getattr(err, "headers", None)
    value = str(headers.get("Retry-After", "")) if headers else ""
    return int(value) if value.isdigit() else 0


def fetch(cache, send, what, kind="video"):
    """`cache`'s text, from disk or else from send() (sent again after each of RETRY_WAITS_S when the network or the
    server fails, never after a refusal), written whole or not at all: a run stopped mid-write never leaves a cut
    reply that reads as complete. `kind` ("video" or "image") sets how often a progress line is printed."""
    if not cache.exists():
        for wait in (*RETRY_WAITS_S, None):
            try:
                text = send()
                break
            except (OSError, RuntimeError, ValueError, http.client.HTTPException) as err:  # URLError, timeouts, cut streams
                if wait is None or is_final(err):
                    raise
                wait = max(wait, asked_wait_s(err))
                print(f"{what} failed ({str(err)[:120]}); trying again in {wait} s", flush=True)
                time.sleep(wait)
        partial = cache.with_suffix(".part")
        partial.write_text(text)
        partial.replace(cache)
        with SAVED_LOCK:
            SAVED[kind] = saved = SAVED.get(kind, 0) + 1
        if saved % PROGRESS_EVERY[kind] == 0:  # a long run shows it is alive (and the screen recording shows progress)
            print(f"{saved} new SAM {kind} replies saved ({time.strftime('%H:%M')})", flush=True)
    return cache.read_text()


def each(fn, items, workers):
    """[fn(item) for item in items], `workers` at a time. On the first error the items not started yet are dropped,
    so a dropout ends the run in minutes instead of every queued request waiting out RETRY_WAITS_S in turn."""
    pool = ThreadPoolExecutor(workers)
    try:
        return list(pool.map(fn, items))
    finally:
        pool.shutdown(cancel_futures=True)


def track(video, concept, api_key, cache_dir):
    """Tracks for one concept, re-using the cached SAM reply for this clip when there is one."""
    return parse(fetch(cache_path(cache_dir, concept), lambda: request(video, concept, api_key),
                       f"SAM {concept} on {video}"))
