"""Paid test, about $0.15: does SAM's single concept "vehicle" find what "car", "motorcycle" and "auto rickshaw" find?
Frames that crowd mode already sent with those three concepts go to SAM once more as images with the concept
"vehicle", and each frame's "vehicle" boxes are matched against the three concepts' cached boxes. Adopt "vehicle" at
ADOPT_RECALL or better: it cuts vehicle image requests 3x (README "Scale"). Until a run says so, it is not adopted.

  python3 vehicle_test.py out/indian-crowd            # prints what it would cost; sends nothing
  python3 vehicle_test.py out/indian-crowd --spend    # sends the uncached images (at most $0.20)

Replies are cached in OUT_DIR/crowd-vehicle (where crowd mode would keep them), so a re-run costs nothing. The
result goes to OUT_DIR/vehicle-test-result.json.
"""
import argparse
import json
from pathlib import Path

import analyze
import crowd
import sam

CONCEPTS = ("car", "motorcycle", "auto rickshaw")
NEW_CONCEPT = "vehicle"
FRAMES = 60          # frames sent, spread evenly over the frames all three concepts have cached
MATCH_IOU = 0.5      # a "vehicle" box finds a cached box when they overlap this much
ADOPT_RECALL = 0.95  # adopt "vehicle" at this share of the three concepts' vehicles found, or better
MAX_USD = 0.20       # refuse to send more than this (60 images are $0.15 at Meta's list price)


def spread(frames, n):
    """n frames spread evenly over a sorted list (all of them if there are fewer)."""
    if len(frames) <= n:
        return list(frames)
    return [frames[round(i * (len(frames) - 1) / (n - 1))] for i in range(n)]


def known_vehicles(boxes_by_concept):
    """[(concept, box)] of one frame, a box that two concepts both found (IoU >= MATCH_IOU) kept once."""
    kept = []
    for concept, boxes in boxes_by_concept.items():
        for box in boxes:
            if not any(crowd.iou(box, other) >= MATCH_IOU for _, other in kept):
                kept.append((concept, box))
    return kept


def matched(known, found):
    """({concept: [found, of]}, found boxes that matched nothing): each known (concept, box) pair is found by at most
    one distinct `found` box overlapping it by MATCH_IOU, best overlaps first."""
    pairs = sorted(((crowd.iou(box, f), k, j) for k, (_, box) in enumerate(known) for j, f in enumerate(found)
                    if crowd.iou(box, f) >= MATCH_IOU), reverse=True)
    used_k, used_f = set(), set()
    for _, k, j in pairs:
        if k not in used_k and j not in used_f:
            used_k.add(k)
            used_f.add(j)
    hits = {}
    for k, (concept, _) in enumerate(known):
        hits.setdefault(concept, [0, 0])[1] += 1
        hits[concept][0] += k in used_k
    return hits, len(found) - len(used_f)


def cached_boxes(folder, frame):
    return [b for t in sam.parse((folder / f"{frame:06d}.sam.txt").read_text()).values() for b in t.values()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", help="an analyze.py output folder with crowd-car, crowd-motorcycle and "
                                        "crowd-auto_rickshaw replies (e.g. out/indian-crowd)")
    parser.add_argument("--cache", help="where the vehicle replies are kept (default OUT_DIR/crowd-vehicle)")
    parser.add_argument("--spend", action="store_true", help=f"send the uncached images (at most ${MAX_USD:.2f})")
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    cache = Path(args.cache) if args.cache else crowd.cache_dir(out_dir, NEW_CONCEPT)
    dirs = {c: crowd.cache_dir(out_dir, c) for c in CONCEPTS}
    cached = [{int(p.name[:6]) for p in d.glob("*.sam.txt")} for d in dirs.values()]
    frames = spread(sorted(set.intersection(*cached)), FRAMES)
    if not frames:
        raise SystemExit(f"{out_dir} has no frame cached for all of {', '.join(CONCEPTS)}")
    todo = [f for f in frames if not (cache / f"{f:06d}.sam.txt").exists()]
    usd = len(todo) * analyze.SAM_USD_PER_IMAGE
    print(f"{len(frames)} frames, {len(todo)} not cached: about ${usd:.2f} at Meta's list price", flush=True)
    if usd > MAX_USD:
        raise SystemExit(f"${usd:.2f} is over this test's ${MAX_USD:.2f} cap")
    if todo and not args.spend:
        raise SystemExit("nothing sent; add --spend to send them")
    key = sam.load_api_key() if todo else None
    found = crowd.detect(out_dir / "clip.mp4", frames, NEW_CONCEPT, key, cache, analyze.FPS)

    hits, extra = {c: [0, 0] for c in CONCEPTS}, 0
    for f in frames:
        frame_hits, frame_extra = matched(known_vehicles({c: cached_boxes(dirs[c], f) for c in CONCEPTS}), found[f])
        extra += frame_extra
        for c, (got, of) in frame_hits.items():
            hits[c] = [hits[c][0] + got, hits[c][1] + of]
    got, of = sum(h[0] for h in hits.values()), sum(h[1] for h in hits.values())
    recall = got / of if of else 0.0
    result = {"frames": len(frames), "out_dir": str(out_dir), "match_iou": MATCH_IOU, "recall": round(recall, 3),
              "found": got, "of": of, "per_concept": {c: {"found": h[0], "of": h[1]} for c, h in hits.items()},
              "vehicle_boxes_matching_none": extra, "adopt": recall >= ADOPT_RECALL}
    (out_dir / "vehicle-test-result.json").write_text(json.dumps(result, indent=1))
    for c, (g, n) in hits.items():
        print(f"  {c:14s} {g} of {n} found by \"{NEW_CONCEPT}\"")
    print(f"recall {got} of {of} ({100 * recall:.1f}%); {extra} \"{NEW_CONCEPT}\" boxes matched none of the three "
          f"(buses, trucks, bicycles or false hits). {'ADOPT' if result['adopt'] else 'KEEP the three concepts'} "
          f"(bar: {100 * ADOPT_RECALL:.0f}%)")
    return result


if __name__ == "__main__":
    main()
