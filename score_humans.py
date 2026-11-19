"""Scores the blind check (G5 in GATES.md): each rater's answers against the key blind_set.py kept apart, as danger
(serious or close) against none. "Can't tell" and unanswered clips are left out and counted.

Run: python3 score_humans.py OUT_DIR/blind-key.json answers-*.json
"""
import argparse
import json
import math
from pathlib import Path

Z95 = 1.959964             # two-sided 95%
ANSWERS = {"serious": True, "close": True, "none": False, "cant_tell": None}  # the blind page's choices: danger?
KAPPA_PASS = 0.6           # G5: substantial agreement (Landis & Koch 1977)
MAX_CANT_TELL = 0.25       # G5 is not decidable when more of the clips than this get no answer
MIN_PER_KIND = 6           # ...or with fewer near-misses (or decoys) than this in the set


def wilson(k, n, z=Z95):
    """Wilson's 95% score interval for k of n, as shares (0 to 1); (0, 1) when n is 0."""
    if not n:
        return 0.0, 1.0
    p, z2 = k / n, z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def kappa(a, b, c, d):
    """Cohen's kappa for a 2 x 2 table: a both danger, b only the rater, c only the pipeline, d both none. None when
    chance alone explains every answer (all clips on one side)."""
    n = a + b + c + d
    expected = ((a + b) * (a + c) + (c + d) * (b + d)) / n / n if n else 1.0
    return ((a + d) / n - expected) / (1 - expected) if expected < 1 else None


def read_answers(path, clips):
    """(rater, {clip: danger True/False/None}) from a file the blind page downloaded; refuses anything else."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as err:
        raise SystemExit(f"{path}: cannot read it: {err}")
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict) or not all(isinstance(v, str) and v in ANSWERS for v in answers.values()):
        raise SystemExit(f"{path}: not a blind-page download (answers must be one of {', '.join(ANSWERS)})")
    unknown = set(answers) - set(clips)
    if unknown:
        raise SystemExit(f"{path}: clips not in the key: {', '.join(sorted(unknown))}")
    return str(data.get("rater") or Path(path).stem), {clip: ANSWERS[answers.get(clip, "cant_tell")] for clip in clips}


def table(truth, said):
    """(a, b, c, d, left out): the 2 x 2 table of the rater against the pipeline over the clips the rater decided."""
    pairs = [(said[clip], danger) for clip, danger in truth.items() if said[clip] is not None]
    count = lambda rater, pipeline: sum(p == (rater, pipeline) for p in pairs)
    return count(True, True), count(True, False), count(False, True), count(False, False), len(truth) - len(pairs)


def share(k, n):
    lo, hi = wilson(k, n)
    return f"{k} of {n} (Wilson 95% {100 * lo:.0f}-{100 * hi:.0f}%)"


def gate(a, b, c, d, left_out, near_misses, decoys):
    """G5's pre-registered verdict for one rater: PASS, FAIL or NOT DECIDABLE (with the reason)."""
    if min(near_misses, decoys) < MIN_PER_KIND:
        return f"NOT DECIDABLE: fewer than {MIN_PER_KIND} near-misses or decoys in the set"
    if left_out > MAX_CANT_TELL * (a + b + c + d + left_out):
        return f"NOT DECIDABLE: more than {MAX_CANT_TELL:.0%} of the clips were can't tell or unanswered"
    k = kappa(a, b, c, d)
    return "PASS" if k is not None and k >= KAPPA_PASS else "FAIL"


def report(rater, truth, said):
    """Lines for one rater: agreement with its Wilson interval, kappa, positive and negative agreement, G5."""
    a, b, c, d, left_out = table(truth, said)
    near_misses = sum(truth.values())
    k = kappa(a, b, c, d)
    pos = f"{2 * a / (2 * a + b + c):.2f}" if a + b + c else "-"
    neg = f"{2 * d / (2 * d + b + c):.2f}" if d + b + c else "-"
    return [f"{rater}: {len(truth)} clips, {left_out} can't tell or unanswered.",
            f"  Agreed with the pipeline on {share(a + d, a + b + c + d)}; Cohen's kappa "
            f"{'undefined' if k is None else f'{k:.2f}'}.",
            f"  The pipeline's near-misses called danger: {share(a, a + c)}; decoys called none: {share(d, b + d)}.",
            f"  Positive agreement {pos}, negative agreement {neg}.",
            f"  G5 (kappa {KAPPA_PASS} or more): {gate(a, b, c, d, left_out, near_misses, len(truth) - near_misses)}"]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("key", help="blind-key.json, written by blind_set.py")
    parser.add_argument("answers", nargs="+", help="one answers file per rater, downloaded from the blind page")
    args = parser.parse_args()
    truth = {c["clip"]: c["truth"] != "decoy" for c in json.loads(Path(args.key).read_text())["clips"]}
    for path in args.answers:
        rater, said = read_answers(path, truth)
        print("\n".join(report(rater, truth, said)))


if __name__ == "__main__":
    main()
