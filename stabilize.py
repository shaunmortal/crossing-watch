"""Lock a hand-held recording to one reference frame, so the tape-mark calibration holds for every frame.
A phone held at one spot only turns in the hand, so each frame maps onto the reference frame by one homography
(SIFT features, RANSAC). Writes OUT (1920x1080, constant 30 fps, the original sound) and OUT.stab.json: per frame the
homography, its inlier count, and whether the previous frame's was reused (too few inliers, e.g. a bus fills the view).
Needs OpenCV, outside the stdlib pipeline: pip install opencv-python-headless numpy.
Run: python stabilize.py IN.mp4 OUT.mp4 --ref-s SECONDS     Self-check: python stabilize.py --selftest
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

SIZE = (1920, 1080)
FPS = 30
FEATURE_WIDTH = 960   # features found at half width: same answer, a quarter of the time
MIN_INLIERS = 40      # fewer: keep the previous frame's homography (the hand moves little in 1/30 s)
RATIO = 0.75          # Lowe's ratio test
RANSAC_PX = 2.0       # at FEATURE_WIDTH


class Locker:
    """Homographies from any frame onto one reference frame (grey, full size)."""

    def __init__(self, ref):
        self.scale = FEATURE_WIDTH / ref.shape[1]
        self.sift, self.matcher = cv2.SIFT_create(4000), cv2.BFMatcher()
        self.kp, self.des = self.sift.detectAndCompute(self.small(ref), None)
        self.S = np.diag([self.scale, self.scale, 1.0])

    def small(self, grey):
        return cv2.resize(grey, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA)

    def to_ref(self, grey):
        """(full-size homography onto the reference, inliers), or (None, inliers) when too few agree."""
        kp, des = self.sift.detectAndCompute(self.small(grey), None)
        if des is None or len(kp) < MIN_INLIERS:
            return None, 0
        pairs = [m for m, n in self.matcher.knnMatch(des, self.des, k=2) if m.distance < RATIO * n.distance]
        if len(pairs) < MIN_INLIERS:
            return None, len(pairs)
        src = np.float32([kp[m.queryIdx].pt for m in pairs])
        dst = np.float32([self.kp[m.trainIdx].pt for m in pairs])
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_PX)
        inliers = int(mask.sum()) if mask is not None else 0
        if H is None or inliers < MIN_INLIERS:
            return None, inliers
        return np.linalg.inv(self.S) @ H @ self.S, inliers


def frames(path, start=0.0):
    """BGR frames at constant FPS from `start` s, as the phone's rotation flag shows them."""
    cmd = ["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(path), "-vf", f"fps={FPS},scale={SIZE[0]}:{SIZE[1]}",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
        n = SIZE[0] * SIZE[1] * 3
        while len(raw := proc.stdout.read(n)) == n:
            yield np.frombuffer(raw, np.uint8).reshape(SIZE[1], SIZE[0], 3)


def stabilize(src, out, ref_s):
    ref = next(frames(src, ref_s))
    locker = Locker(cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY))
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s",
                            f"{SIZE[0]}x{SIZE[1]}", "-r", str(FPS), "-i", "-", "-i", str(src), "-map", "0:v",
                            "-map", "1:a?", "-c:v", "libx264", "-crf", "16", "-preset", "fast", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-shortest", str(out)], stdin=subprocess.PIPE)
    log, last = [], np.eye(3)
    for i, frame in enumerate(frames(src)):
        H, inliers = locker.to_ref(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        reused = H is None
        last = last if reused else H
        enc.stdin.write(cv2.warpPerspective(frame, last, SIZE).tobytes())
        log.append({"frame": i, "inliers": inliers, "reused": reused, "H": np.round(last, 6).tolist()})
        if i % (FPS * 60) == 0:
            print(f"{i / FPS / 60:.0f} min: {inliers} inliers{' (reused)' if reused else ''}", flush=True)
    enc.stdin.close()
    if enc.wait():
        raise SystemExit("stabilize.py: ffmpeg could not write the output")
    Path(f"{out}.stab.json").write_text(json.dumps({"source": str(src), "ref_s": ref_s, "fps": FPS,
                                                     "frames": log}))
    reused = sum(f["reused"] for f in log)
    print(f"wrote {out}: {len(log)} frames, {reused} reused the previous homography")


def selftest():
    """A textured frame turned by a known homography is locked back onto itself within a pixel."""
    rng = np.random.default_rng(0)
    ref = cv2.GaussianBlur((rng.random((SIZE[1], SIZE[0])) * 255).astype(np.uint8), (5, 5), 0)
    turn = np.array([[1.01, 0.02, -25.0], [-0.015, 0.99, 18.0], [1e-6, 2e-6, 1.0]])
    moved = cv2.warpPerspective(ref, turn, SIZE)
    H, inliers = Locker(ref).to_ref(moved)
    corners = np.float32([[400, 300], [1500, 300], [1500, 800], [400, 800]]).reshape(-1, 1, 2)
    back = cv2.perspectiveTransform(cv2.perspectiveTransform(corners, turn), H)
    err = float(np.abs(back - corners).max())
    assert inliers >= MIN_INLIERS and err < 1.0, (inliers, err)
    print(f"selftest ok: {inliers} inliers, worst corner {err:.2f} px")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
        sys.exit(0)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("src", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--ref-s", type=float, required=True, help="the reference frame: every tape mark in view")
    args = parser.parse_args()
    stabilize(args.src, args.out, args.ref_s)
