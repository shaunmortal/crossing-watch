"""People are the clock: pedestrians walk at about 1.2-1.5 m/s, so the median walking speed of the people in a video,
in road metres a second, checks its clock and its calibration at once. In a time-lapse, or with a calibration
rectangle marked too large, everyone walks too fast; then no speed, PET or gap from that video is a measurement.
"""
import statistics

import road

NORMAL_MPS = 1.3  # normal walking, 1.2-1.5 m/s; DUT's and SinD's own pedestrian tracks give medians of 1.22 and 1.13
FAST_MPS = 2.4    # median above this: sped up, or the scale too large (real videos 1.05-1.66; the Indian time-lapse 2.71)
SLOW_MPS = 0.5    # median below this: slowed down, or the scale too small (real videos 0.80 at the lowest)
MIN_PIECES = 10   # fewer walking pieces than this are not judged (the fewest on a real video we measured: 11)


def piece_mps(feet, fps):
    """A pedestrian piece's median speed (road.speeds) over its moving frames, or None for a piece that never crossed
    (road.crossing_cells' rule) or is too short to time."""
    if not road.crossing_cells({"": feet}, fps):
        return None
    moving = road.moving_frames(feet, fps)
    mps = list(road.speeds({f: (p,) for f, p in moving.items()}, fps).values())
    return statistics.median(mps) if mps else None


def walking(people, fps):
    """{"median_mps", "pieces", "flag"} for analyze's pedestrian pieces: the median of their piece_mps, how many had
    one, and "fast" or "slow" when that median is outside FAST_MPS / SLOW_MPS (None when it is not, or when fewer
    than MIN_PIECES pieces walked)."""
    mps = [v for feet in people.values() if (v := piece_mps(feet, fps)) is not None]
    median = statistics.median(mps) if mps else None
    flag = (None if len(mps) < MIN_PIECES else "fast" if median > FAST_MPS else "slow" if median < SLOW_MPS else None)
    return {"median_mps": None if median is None else round(median, 2), "pieces": len(mps), "flag": flag}


def warning(walk):
    """The page's and the agent's sentence for a flagged video, "" otherwise (also for an events.json without it)."""
    if not (walk or {}).get("flag"):
        return ""
    looks = "sped up" if walk["flag"] == "fast" else "slowed down"
    return (f"People here walk at {walk['median_mps']:.1f} m/s, about {walk['median_mps'] / NORMAL_MPS:.1f} times "
            f"normal walking ({NORMAL_MPS:g} m/s, the median of {walk['pieces']} walking tracks): this video looks "
            f"{looks} or the calibration is off, so its speeds, near-miss times and gaps are not trusted.")
