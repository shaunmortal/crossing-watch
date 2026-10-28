"""Crowd mode for pedestrians (opt-in: "person_mode": "crowd" in the site file). SAM 3.1 video tracking keeps at
most 16 objects per frame, but on a single image it returns every match (71 people on one crowded DUT frame). So in
crowds SAM detects people frame by frame as images, and a small tracker here keeps their IDs.
"""
import base64
import json
import math
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import sam

CROWD_FPS = 5        # frames a second sent as images; a walker moves ~30 cm between them
WORKERS = 6          # parallel image requests
MATCH_IOU = 0.3      # a detection continues a track when it overlaps the predicted box this much...
MATCH_SIZES = 1.0    # ...or when its centre is within one box size (the larger side) of the predicted centre:
                     # between samples a walker moves less than their own body width
MAX_GAP_S = 1.0      # a track hidden for up to this long picks up its ID again


def detect(clip, frames, concept, api_key, cache_dir, clip_fps):
    """{frame: [box, ...]} from SAM on single images of the clip, every frame in `frames`; replies cached per frame."""
    cache_dir.mkdir(parents=True, exist_ok=True)

    def one(frame):
        cache = cache_dir / f"{frame:06d}.sam.txt"
        if not cache.exists():
            jpeg = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{frame / clip_fps:.3f}", "-i", str(clip),
                                   "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "-q:v", "3", "-"],
                                  check=True, capture_output=True).stdout
            cache.write_text(request(jpeg, concept, api_key))
        return frame, [box for track in sam.parse(cache.read_text()).values() for box in track.values()]

    with ThreadPoolExecutor(WORKERS) as pool:
        return dict(pool.map(one, frames))


def request(jpeg, concept, api_key):
    """Raw streamed SAM text for one concept on one image."""
    url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
    body = json.dumps({"model": sam.MODEL, "stream": True, "metadata": {"mask_encoding": "one_bit"},
                       "input": [{"type": "message", "role": "user", "content": [
                           {"type": "input_text", "text": concept}, {"type": "input_image", "image_url": url}]}]}).encode()
    req = urllib.request.Request(sam.API_URL, data=body, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    chunks, completed = [], False
    with urllib.request.urlopen(req, timeout=sam.TIMEOUT_S) as response:
        for raw in response:
            line = raw.decode().strip()
            if not line.startswith("data:") or line[5:].strip() in ("", "[DONE]"):
                continue
            event = json.loads(line[5:])
            if event.get("type") == "error":
                raise RuntimeError(f"SAM error for {concept!r}: {event}")
            if event.get("type") == "response.output_text.delta":
                chunks.append(event["delta"])
            completed = completed or event.get("type") == "response.completed"
    if not completed:
        raise RuntimeError(f"SAM image stream for {concept!r} ended before response.completed")
    return "".join(chunks)


def iou(a, b):
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = w * h
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def centre(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def predicted(track, last_frame, frame):
    """The track's box moved on to `frame` at the velocity of its last two boxes (constant velocity)."""
    box = track[last_frame]
    earlier = [f for f in track if f < last_frame]
    if not earlier:
        return box
    prev = track[max(earlier)]
    (cx, cy), (px, py) = centre(box), centre(prev)
    k = (frame - last_frame) / (last_frame - max(earlier))
    dx, dy = (cx - px) * k, (cy - py) * k
    return [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy]


def closeness(expected, box):
    """How well a detection continues a track, given where the track was expected: from IoU, or failing that
    from centre distance in box sizes; None when it is too far to be the same person."""
    overlap = iou(expected, box)
    if overlap >= MATCH_IOU:
        return 1 + overlap
    size = max(expected[2] - expected[0], expected[3] - expected[1], 1.0)
    shift = math.dist(centre(expected), centre(box)) / size
    return 1 - shift / MATCH_SIZES if shift <= MATCH_SIZES else None


def associate(detections, clip_fps):
    """{track id: {frame: box}} from {frame: [box, ...]}: each frame's boxes join the best-matching live track
    (greedy, best match first); a track unseen for MAX_GAP_S ends; unmatched boxes start new tracks."""
    tracks, last = {}, {}  # id -> {frame: box}; id -> last frame seen
    max_gap = round(MAX_GAP_S * clip_fps)
    for frame in sorted(detections):
        boxes = detections[frame]
        live = [tid for tid, seen in last.items() if frame - seen <= max_gap]
        expected = {tid: predicted(tracks[tid], last[tid], frame) for tid in live}
        pairs = sorted(((score, tid, i) for tid in live for i, box in enumerate(boxes)
                        if (score := closeness(expected[tid], box)) is not None), reverse=True)
        used_t, used_b = set(), set()
        for _, tid, i in pairs:
            if tid in used_t or i in used_b:
                continue
            used_t.add(tid)
            used_b.add(i)
            tracks[tid][frame] = boxes[i]
            last[tid] = frame
        for i, box in enumerate(boxes):
            if i not in used_b:
                tid = f"c{len(tracks)}"
                tracks[tid], last[tid] = {frame: box}, frame
    return tracks


def track(clip, total_frames, clip_fps, concept, api_key, cache_dir, sample_fps=CROWD_FPS):
    """Pedestrian tracks for a crowded clip: SAM image detection every 1/sample_fps s, IDs from `associate`."""
    step = max(1, round(clip_fps / sample_fps))
    return associate(detect(clip, range(0, total_frames, step), concept, api_key, cache_dir, clip_fps), clip_fps)
