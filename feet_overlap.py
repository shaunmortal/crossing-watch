"""Feet-overlap share of a cached analyze.py run, at $0: of the person frames left after the rider filter, the share
whose box bottom sits on a vehicle's box (what road.feet_hidden drops at an angle). A proxy for how often a phone at an
angle loses feet behind a vehicle, not ground truth. Nothing is sent to SAM. Run: python3 feet_overlap.py SITE OUT_DIR"""
import json
import sys
from pathlib import Path

import analyze, crowd, road, sam, validate_dut, validate_offline  # noqa: E401


def feet_overlap(person_boxes, vehicle_boxes):
    """(frames whose feet sit on a vehicle's box, person frames after without_riders)."""
    on_frame = road.boxes_by_frame(vehicle_boxes.values())
    walkers = [road.without_riders(t, on_frame) for t in person_boxes.values()]
    return sum(len(t) - len(road.feet_hidden(t, on_frame)) for t in walkers), sum(len(t) for t in walkers)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    site, out_dir = analyze.load_site(sys.argv[1]), Path(sys.argv[2])
    stamp = json.loads((out_dir / "source.json").read_text())
    analyze.CHUNK_FRAMES, analyze.OVERLAP_FRAMES = stamp["chunk_frames"], stamp["overlap_frames"]  # as this run cut
    sam.request = crowd.request = analyze.encode = validate_offline.offline
    sam.RETRY_WAITS_S = ()
    hidden, frames = feet_overlap(*validate_dut.our_tracks(site, out_dir)[:2])
    if not frames:
        raise SystemExit(f"{out_dir}: no person frames after the rider filter")
    print(f"{out_dir}: feet on a vehicle's box in {hidden} of {frames} person frames ({100 * hidden / frames:.1f}%)")
