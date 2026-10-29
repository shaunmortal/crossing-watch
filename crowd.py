"""Crowd mode (opt-in: "person_mode": "crowd" for people, "vehicle_mode": "crowd" for dense traffic). SAM 3.1 video tracking keeps at
most 16 objects per frame, but on a single image it returns every match (71 people on one crowded DUT frame). So in
crowds SAM detects people frame by frame as images, and a small tracker here keeps their IDs.
"""
import base64
import json
import math
import subprocess
import urllib.request

import sam

CROWD_FPS = 5        # people: frames a second sent as images; a walker moves ~30 cm between them
VEHICLE_FPS = 10     # vehicles: a 2 m motorcycle at 60 km/h moves 0.8 of its length between samples (at 5 a
                     # second, anything over ~36 km/h outran the one-body-size match and was lost)
WORKERS = 6          # parallel image requests
MATCH_IOU = 0.3      # a detection continues a track when it overlaps the predicted box this much...
MATCH_SIZES = 1.0    # ...or when its centre is within one box size (the larger side) of the predicted centre:
                     # between samples a walker moves less than their own body width
MAX_GAP_S = 1.0      # a track hidden for up to this long picks up its ID again
MAX_AREA_JUMP = 2.5  # vehicles: a box this many times larger or smaller than the track's last is another vehicle
                     # (a motorcycle went 43x68 to 30x18 px: a phantom 81 km/h); people may just be partly hidden


def detect(clip, frames, concept, api_key, cache_dir, clip_fps):
    """{frame: [box, ...]} from SAM on single images of the clip, every frame in `frames`; replies cached per frame."""
    cache_dir.mkdir(parents=True, exist_ok=True)

    def one(frame):
        jpeg = lambda: subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{frame / clip_fps:.3f}", "-i", str(clip),
                                       "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "-q:v", "3", "-"],
                                      check=True, capture_output=True).stdout
        text = sam.fetch(cache_dir / f"{frame:06d}.sam.txt", lambda: request(jpeg(), concept, api_key),
                         f"SAM {concept} on frame {frame}", "image")
        return frame, [box for track in sam.parse(text).values() for box in track.values()]

    return dict(sam.each(one, frames, WORKERS))


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


def closeness(expected, box, max_area_jump=math.inf):
    """How well a detection continues a track, given where the track was expected: from IoU, or failing that
    from centre distance in box sizes; None when it is too far, or too different in size, to be the same object."""
    jump = (box[2] - box[0]) * (box[3] - box[1]) / ((expected[2] - expected[0]) * (expected[3] - expected[1]))
    if max(jump, 1 / jump) > max_area_jump:
        return None
    overlap = iou(expected, box)
    if overlap >= MATCH_IOU:
        return 1 + overlap
    size = max(expected[2] - expected[0], expected[3] - expected[1], 1.0)
    shift = math.dist(centre(expected), centre(box)) / size
    return 1 - shift / MATCH_SIZES if shift <= MATCH_SIZES else None


def associate(detections, clip_fps, max_area_jump=math.inf):
    """{track id: {frame: box}} from {frame: [box, ...]}: each frame's boxes join the best-matching live track
    (greedy, best match first; never one whose box is over `max_area_jump` times larger or smaller); a track unseen
    for MAX_GAP_S ends; unmatched boxes start new tracks."""
    tracks, last = {}, {}  # id -> {frame: box}; id -> last frame seen
    max_gap = round(MAX_GAP_S * clip_fps)
    for frame in sorted(detections):
        boxes = detections[frame]
        live = [tid for tid, seen in last.items() if frame - seen <= max_gap]
        expected = {tid: predicted(tracks[tid], last[tid], frame) for tid in live}
        pairs = sorted(((score, tid, i) for tid in live for i, box in enumerate(boxes)
                        if (score := closeness(expected[tid], box, max_area_jump)) is not None), reverse=True)
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


def filled(track):
    """The track with a box on every frame between its samples, moved linearly: render blurs and boxes only the
    frames that have one, so a gap would show a face."""
    frames = sorted(track)
    out = dict(track)
    for f, g in zip(frames, frames[1:]):
        for h in range(f + 1, g):
            k = (h - f) / (g - f)
            out[h] = [a + (b - a) * k for a, b in zip(track[f], track[g])]
    return dict(sorted(out.items()))


def cache_dir(out_dir, concept):
    """Where crowd mode keeps its per-frame SAM replies for one concept."""
    return out_dir / f"crowd-{sam.cache_path(out_dir, concept).stem.split('.')[0]}"


def sample_frames(total_frames, clip_fps, sample_fps):
    return range(0, total_frames, max(1, round(clip_fps / sample_fps)))


def track(clip, frames, clip_fps, concept, api_key, cache_dir, max_area_jump=math.inf):
    """Tracks of one concept in a crowded clip, as detected: SAM image detection on `frames` (see sample_frames), IDs
    from `associate` (see its `max_area_jump`). `filled` adds the boxes in between; keeping these apart says which
    positions were seen and which inferred."""
    return associate(detect(clip, frames, concept, api_key, cache_dir, clip_fps), clip_fps, max_area_jump)
