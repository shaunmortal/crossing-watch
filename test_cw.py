"""Self-check for road geometry, PET and SAM parsing. Run: python3 test_cw.py"""
import html
import json
import math

import listen
import overlay
import pack
import render
import review
import road
import sam

SQUARE_IMG = [[100, 100], [300, 100], [300, 300], [100, 300]]
SQUARE_ROAD = [[0, 0], [10, 0], [10, 10], [0, 10]]


def test_homography_maps_calibration_points_and_midpoint():
    H = road.homography(SQUARE_IMG, SQUARE_ROAD)
    for (x, y), want in zip(SQUARE_IMG, SQUARE_ROAD):
        assert math.dist(road.to_ground(H, x, y), want) < 1e-9
    assert math.dist(road.to_ground(H, 200, 200), (5, 5)) < 1e-9


def test_homography_handles_perspective():
    trapezoid = [[250, 100], [350, 100], [500, 300], [100, 300]]  # a road narrowing towards the horizon
    H = road.homography(trapezoid, SQUARE_ROAD)
    for (x, y), want in zip(trapezoid, SQUARE_ROAD):
        assert math.dist(road.to_ground(H, x, y), want) < 1e-6


def test_road_points_map_back_to_their_pixels():
    trapezoid = [[250, 100], [350, 100], [500, 300], [100, 300]]  # its sides meet at the horizon, y = 33.3
    H = road.homography(trapezoid, SQUARE_ROAD)
    for x, y in trapezoid + [[300, 200], [123, 287], [420, 60]]:
        assert math.dist(road.to_image(H, *road.to_ground(H, x, y)), (x, y)) < 1e-6
    assert 100 / 3 < road.to_image(H, 5, -1000)[1] < 35  # far up the road: just under the horizon
    assert road.to_image(H, 5, 1000) is None  # behind the camera


def raises_value_error(call):
    try:
        call()
    except ValueError:
        return True
    return False


def raises_system_exit(call):
    try:
        call()
    except SystemExit:
        return True
    return False


def test_collinear_or_out_of_order_points_are_rejected():
    assert raises_value_error(lambda: road.homography([[0, 0], [1, 1], [2, 2], [3, 3]], SQUARE_ROAD))
    crossed = [SQUARE_IMG[0], SQUARE_IMG[2], SQUARE_IMG[1], SQUARE_IMG[3]]  # corners not in order round the area
    assert raises_value_error(lambda: road.homography(crossed, SQUARE_ROAD))


def edges_along_x(speed_mps, fps, frames, y=0.0):
    """A 2 m wide vehicle edge driving along x, centred at x=0 on frame frames//2."""
    return {f: ((speed_mps * (f - frames // 2) / fps - 1, y), (speed_mps * (f - frames // 2) / fps + 1, y))
            for f in range(frames)}


def test_vehicle_through_standing_pedestrian_is_a_zero_pet_conflict():
    fps, frames = 10, 40
    feet = {f: (0.0, 0.0) for f in range(frames)}
    hit = road.closest_pass(feet, edges_along_x(8.0, fps, frames), fps)
    assert hit["pet_s"] == 0 and hit["gap_m"] == 0 and abs(hit["vehicle_kmh"] - 28.8) < 0.5


def test_vehicle_passing_after_pedestrian_left_gives_the_time_gap():
    fps, frames = 10, 40
    feet = {f: (0.0, 0.0) for f in range(15)}  # on the spot until 1.4 s; the car's edge is within 1 m from 1.8 s
    hit = road.closest_pass(feet, edges_along_x(8.0, fps, frames), fps)
    assert abs(hit["pet_s"] - 0.4) < 1e-9


def test_zone_and_speed_glitches_are_ignored():
    zone = road.zone_around(SQUARE_ROAD, margin=5)
    assert zone == (-5, -5, 15, 15) and road.in_zone((14, 0), zone) and not road.in_zone((16, 0), zone)
    H = road.homography(SQUARE_IMG, SQUARE_ROAD)
    assert road.person_points({0: [0, 0, 20, 300], 1: [990, 0, 1010, 300]}, H, zone).keys() == {0}
    fps, frames = 10, 40
    feet = {f: (0.0, 0.0) for f in range(frames)}
    assert road.closest_pass(feet, edges_along_x(60.0, fps, frames), fps) is None  # 216 km/h: a glitch


def test_far_or_parked_vehicles_are_not_conflicts():
    fps, frames = 10, 40
    feet = {f: (0.0, 0.0) for f in range(frames)}
    assert road.closest_pass(feet, edges_along_x(8.0, fps, frames, y=5.0), fps) is None  # other lane
    assert road.closest_pass(feet, edges_along_x(0.0, fps, frames), fps) is None  # parked right there


def test_impact_speed_from_reaction_and_braking():
    assert road.impact_mps(10.0, 0.0) == 10.0  # no room at all: full speed
    assert road.impact_mps(10.0, 10.0) == 10.0  # still inside the 15 m reaction distance
    assert abs(road.impact_mps(10.0, 16.0) - math.sqrt(100 - 2 * 7.0 * 1.0)) < 1e-9  # 1 m of braking
    assert road.impact_mps(10.0, 30.0) == 0.0  # stops in time


def test_speed_limit_replay():
    replay = road.with_limits(10.0, 1.0)  # 36 km/h, 10 m away when the pedestrian was on the spot
    assert replay["30"]["impact_kmh"] == 30.0  # 12.5 m reaction distance > 10 m: no braking yet
    assert abs(replay["20"]["impact_kmh"] - 3.6 * math.sqrt((20 / 3.6) ** 2 - 2 * 7.0 * (10 - 20 / 3.6 * 1.5))) < 0.06
    assert road.with_limits(5.0, 0.5)["30"]["impact_kmh"] == 18.0  # already under the limit: unchanged


def test_death_risk_matches_rosen_sander():
    assert road.death_risk(0) == 0.0
    assert abs(100 * road.death_risk(50) - 8.32) < 0.01  # Eq. 2 at 50 km/h
    assert abs(100 * road.death_risk(75) - 46.3) < 0.1   # paper: "approximately 50%" at 75 km/h


def walking_across(frames, until=None):
    """A pedestrian crossing along y at 1.5 m/s, at x=0 on frame 20, who vanishes after frame `until`."""
    return {f: (0.0, 1.5 * (f - 20) / 10) for f in range(frames if until is None else until + 1)}


def test_static_objects_are_not_pedestrians():
    pole = {f: (0.1 * (f % 3), 0.0) for f in range(200)}  # jitters a few cm in place for 20 s
    assert road.moving_frames(pole, 10) == {} and road.moving_frames(walking_across(40), 10) == walking_across(40)
    events = road.conflicts({"pole": pole}, {"car#1": edges_along_x(8.0, 10, 200)}, 10)
    assert events == []
    pause = {f: (0.0, 0.0) for f in range(50)}  # a 5 s pause is kept
    assert road.moving_frames(pause, 10) == pause


def test_waiting_a_minute_then_crossing_keeps_the_crossing():
    waiter = {f: (0.0, -1.5) for f in range(600)} | {600 + i: (0.0, -1.5 + 0.15 * i) for i in range(61)}
    kept = road.moving_frames(waiter, 10)
    assert set(range(600, 661)) <= kept.keys() and 0 not in kept


def test_pole_that_drifts_at_the_end_loses_its_still_frames():
    drifting = {f: (0.0, 0.0) for f in range(450)} | {450 + i: (0.1 * i, 0.0) for i in range(30)}
    assert min(road.moving_frames(drifting, 10)) >= 450


def test_pedestrian_tracks_split_where_the_id_jumps():
    pole_then_person = {f: (0.0, 0.0) for f in range(50)} | {f: (3.0, 0.0) for f in range(50, 60)}
    pieces = road.split_at_jumps(pole_then_person, 10)
    assert [sorted(p)[0] for p in pieces] == [0, 50] and road.split_at_jumps(walking_across(40), 10) == [walking_across(40)]
    after_gap = {f: (0.0, 0.0) for f in range(10)} | {f: (8.0, 0.0) for f in range(40, 50)}  # 8 m after a 3 s gap
    assert len(road.split_at_jumps(after_gap, 10)) == 2


def test_speed_ignores_id_switch_teleports():
    edges = edges_along_x(8.0, 10, 40)
    edges = edges | {20: ((99.0, 99.0), (101.0, 99.0))}  # one frame on a far car
    speed = road.speeds(edges, 10)
    assert abs(speed[19] - 8.0) < 1e-6 and abs(speed[21] - 8.0) < 1e-6 and 20 not in speed


def test_speed_is_true_on_a_24_fps_video_resampled_like_prepare():
    """analyze.prepare's fps filter turns 23.976 fps into steps of 2,2,3,2,3 source frames: a median of steps read
    0.83 x the true speed."""
    import analyze, subprocess
    raw = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "nullsrc=s=16x16:r=24000/1001:d=4,geq=lum=N:cb=128:cr=128",
                          "-vf", f"fps={analyze.FPS}", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
                         check=True, capture_output=True).stdout
    source = raw[::16 * 16 * 3 // 2]  # each frame's first luma byte is the number of the source frame it came from
    edges = {k: ((8.0 * n * 1001 / 24000, 0.0), (8.0 * n * 1001 / 24000 + 2, 0.0)) for k, n in enumerate(source)}
    speed = road.speeds(edges, analyze.FPS)
    assert len(source) == 40 and speed.keys() == edges.keys() and all(abs(v - 8.0) < 0.2 for v in speed.values())


def test_id_switches_and_short_fragments_give_no_vehicle_speed():
    import analyze, crowd
    from pathlib import Path
    switch = {0: [[475, 234, 518, 302]], 6: [[481, 194, 511, 212]]}  # 43x68 px, then 30x18: a phantom 81 km/h
    assert len(crowd.associate(switch, 10)) == 1 and len(crowd.associate(switch, 10, crowd.MAX_AREA_JUMP)) == 2
    jumps, real = {}, crowd.track  # only vehicles: a person may just be partly hidden
    crowd.track = lambda clip, frames, fps, concept, key, cache, jump: jumps.update({concept: jump}) or {}
    try:
        site = {"person": "person", "vehicles": ["motorcycle"], "person_mode": "crowd", "vehicle_mode": "crowd"}
        for concept in ("person", "motorcycle"):
            analyze.concept_tracks(site, concept, None, 20, [], Path("out"), None, None)
    finally:
        crowd.track = real
    assert jumps == {"person": math.inf, "motorcycle": crowd.MAX_AREA_JUMP}
    assert road.speeds(edges_along_x(8.0, 10, 9), 10) == {} and len(road.speeds(edges_along_x(8.0, 10, 10), 10)) == 10
    H = road.homography(SQUARE_IMG, SQUARE_ROAD)  # cut by the right edge of a 640 px frame: not the vehicle's edge
    assert road.vehicle_edges({0: [590, 195, 639, 232], 1: [497, 210, 568, 255]}, H, frame_size=(640, 360)).keys() == {1}


def test_riders_are_not_pedestrians_and_one_jump_is_not_a_speed():
    rider, walker = {0: [110, 10, 130, 60]}, {0: [300, 10, 320, 60]}
    bike = {0: [100, 0, 150, 80]}
    assert road.without_riders(rider, [bike]) == {} and road.without_riders(walker, [bike]) == walker
    bus, in_front = {0: [0, 0, 400, 200]}, {0: [100, 100, 130, 230]}  # overlaps the bus but stands lower: a pedestrian
    assert road.without_riders(in_front, [bus]) == in_front
    two_frames = {0: ((0.0, 0.0), (2.0, 0.0)), 1: ((3.3, 0.0), (5.3, 0.0))}
    assert road.speeds(two_frames, 10) == {}


def test_cut_off_boxes_and_pavement_are_skipped():
    H = road.homography(SQUARE_IMG, SQUARE_ROAD)
    track = {0: [150, 150, 250, 200], 1: [150, 150, 250, 359]}  # frame 1 touches the bottom of a 400x360 frame
    assert road.vehicle_edges(track, H, frame_size=(400, 360)).keys() == {0}
    roadway = [[0, 0], [10, 0], [10, 5], [0, 5]]
    feet = road.person_points({0: [190, 0, 210, 150], 1: [190, 0, 210, 250]}, H, roadway=roadway)
    assert feet.keys() == {0}  # y = 2.5 m on the road, y = 7.5 m on the pavement


def test_conflicts_sorts_most_dangerous_first():
    fps, frames = 10, 40
    people = {"a": walking_across(frames, until=14), "b": walking_across(frames)}
    events = road.conflicts(people, {"car#1": edges_along_x(8.0, fps, frames)}, fps)
    assert [e["person"] for e in events] == ["b", "a"]  # same car and speed: lower PET first
    fast_late = road.conflicts({"a": walking_across(frames, until=14)}, {"fast": edges_along_x(15.0, fps, frames)}, fps)
    slow_now = road.conflicts({"b": walking_across(frames)}, {"slow": edges_along_x(3.0, fps, frames)}, fps)
    both = road.conflicts({"a": walking_across(frames, until=14), "b": walking_across(frames)},
                          {"fast": edges_along_x(15.0, fps, frames), "slow": edges_along_x(3.0, fps, frames)}, fps)
    assert fast_late and slow_now and both[0]["vehicle"] == "fast"  # higher death risk outranks lower PET


def test_box_filters_time_each_box_to_the_cut_clip():
    person, car = {10: [1, 2, 11, 22], 12: [3, 4, 13, 24]}, {11: [0, 0, 50, 30]}
    f = ",".join(render.box_filters([(person, "cyan"), (car, "red")], 10, 12))
    assert f.count("drawbox") == 3 and "eq(n,0)" in f and "eq(n,2)" in f and "w=50:h=30:color=red" in f
    assert render.box_filters([({}, "cyan")], 0, 5) == []


def test_heads_are_blurred_inside_the_frame():
    person = {10: [0, 0, 20, 100], 11: [300, 300, 302, 302]}  # at the frame corner; then too small to matter
    blurs = render.blur_filters([person], 10, 11, (640, 360))
    assert blurs == ["delogo=x=1:y=1:w=19:h=29:enable='eq(n,0)'"]


def test_evidence_clip_runs_until_the_vehicle_arrives():
    late_car = {"t_person_s": 3.0, "t_vehicle_s": 5.5}  # a close pass: the car reached her spot 2.5 s after her
    assert render.window(late_car, 10) == (10, 75)  # 2 s before she was there to 2 s after the car was
    assert render.window({"t_person_s": 0.5, "t_vehicle_s": 0.2}, 10) == (0, 25)  # never before the video starts
    calls, old = [], render.subprocess.run
    render.subprocess.run = lambda args, **kwargs: calls.append(args)
    try:
        render.render("clip.mp4", late_car, {}, {}, 10, "event1.mp4")
    finally:
        render.subprocess.run = old
    assert calls[0][calls[0].index("-ss") + 1] == "1.000" and calls[0][calls[0].index("-frames:v") + 1] == "66"


def test_footsteps_stay_on_screen_and_the_meeting_spot_appears_with_the_first_arrival():
    walker = {f: [100 + 4 * f, 50, 120 + 4 * f, 150] for f in range(10, 16)}  # walking right, feet at y = 150
    car_first = {"t_person_s": 1.4, "t_vehicle_s": 1.2}
    dots = render.trail_filters(walker, car_first, 10, 10, 16)
    assert dots[0] == "drawbox=x=147:y=147:w=6:h=6:color=cyan:t=fill:enable='gte(n,0)'"  # bottom centre, from frame 0
    assert [d.split("enable=")[1] for d in dots] == ["'gte(n,0)'", "'gte(n,2)'", "'gte(n,4)'", "'gte(n,2)'"]
    assert dots[-1] == "drawbox=x=159:y=143:w=14:h=14:color=yellow:t=fill:enable='gte(n,2)'"  # feet at 1.4 s, from 1.2 s
    assert render.foot([0, 0, 10, 20], top_down=True) == (5.0, 10.0) and render.trail_filters({}, car_first, 10, 0, 5) == []
    calls, old = [], render.subprocess.run
    render.subprocess.run = lambda args, **kwargs: calls.append(args)
    try:
        render.render("clip.mp4", car_first, walker, {12: [0, 0, 50, 30]}, 10, "event1.mp4")
    finally:
        render.subprocess.run = old
    filters = calls[0][calls[0].index("-vf") + 1]
    assert filters.count("t=fill") == 4 and filters.index("t=fill") < filters.index("t=3")  # boxes drawn over the dots


SHAPE = ["000000", "011100", "011110", "001110", "000100"]  # a 5 x 6 mask
SHAPE_TEXT = "!!!!)Hl*-9hfWz"  # SHAPE as SAM sends it after "!", made by meta-sam-parser's own encoder


def test_sam_one_bit_masks_decode_and_are_found_under_their_tracked_box():
    import masks, tempfile
    from pathlib import Path
    assert masks.decode(SHAPE_TEXT, 5, 6) == [bytes(int(c) for c in row) for row in SHAPE]
    for broken in (SHAPE_TEXT[:-1], SHAPE_TEXT.replace("z", "}"), ""):  # cut short; a digit outside the 85; empty
        try:
            masks.decode(broken, 5, 6)
            raise AssertionError(broken)
        except ValueError:
            pass
    with tempfile.TemporaryDirectory() as tmp:
        tile = Path(tmp) / "part1" / "tile288_0"  # a crop's reply: its boxes are 288 px left of the clip's
        tile.mkdir(parents=True)
        (tile / "person.sam.txt").write_text(
            f"<3f>0<|box;x1=10;y1=20;x2=15;y2=24;w=352;h=208|><|mask;x=0;y=0;data=5,6,!{SHAPE_TEXT}|>")
        assert masks.find(tmp, [[298.0, 20.0, 303.0, 24.0], [10, 20, 15, 24]]) == {(298, 20, 303, 24): (5, 6, SHAPE_TEXT)}


def test_evidence_clips_draw_sam_silhouettes_instead_of_boxes_where_masks_are_cached():
    import tempfile
    from pathlib import Path
    walker = {10: [100, 50, 105, 54], 11: [102.5, 50.5, 107.5, 54.5], 12: [105, 51, 110, 55], 14: [300, 50, 310, 90]}
    car_first = {"t_person_s": 1.1, "t_vehicle_s": 1.0}  # 11 is filled in between samples; 14 has no mask near
    calls, old = [], render.subprocess.run
    render.subprocess.run = lambda args, **kwargs: calls.append((args, kwargs))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "person.sam.txt").write_text("".join(
                f"<{f}f>0<|box;x1={b[0]};y1={b[1]};x2={b[2]};y2={b[3]};w=640;h=360|><|mask;x=0;y=0;data=5,6,!{SHAPE_TEXT}|>"
                for f, b in walker.items() if f in (10, 12)))
            render.render(Path(tmp) / "clip.mp4", car_first, walker, {}, 10, "event1.mp4", frame_size=(640, 360))
    finally:
        render.subprocess.run = old
    (args, kwargs), size = calls[0], 640 * 360 * 4
    graph, tint = args[args.index("-filter_complex") + 1], kwargs["input"]
    assert "-vf" not in args and "overlay" in graph and len(tint) == 32 * size  # frames 0-31, one RGBA frame each
    pixel = lambda n, x, y: tint[n * size + (y * 640 + x) * 4:n * size + (y * 640 + x) * 4 + 4]
    assert pixel(10, 101, 51) == b"\x00\xff\xff" + bytes([render.TINT]) and pixel(10, 100, 50) == bytes(4)
    assert pixel(11, 103, 51) == pixel(10, 101, 51)  # the frame between borrows a neighbour's mask, at its own box
    assert "eq(n,10)" not in graph and "eq(n,14)" in graph and pixel(14, 301, 51) == bytes(4)  # no mask: its box


def test_stromotion_still_copies_both_at_a_fixed_step_and_skips_piled_up_copies():
    import subprocess, tempfile
    from pathlib import Path
    fast = {f: [10 * f, 100, 20 + 10 * f, 160] for f in range(40)}
    slow = {f: [100 + f, 100, 120 + f, 160] for f in range(40)}  # 5 frames on it still overlaps its copy by 0.6
    assert render.copies(fast, 20, 5, 0, 39) == [0, 5, 10, 15, 20, 25, 30, 35]
    assert render.copies(slow, 20, 5, 0, 39) == [5, 20, 35] and render.copies({20: [0, 0, 9, 9]}, 20, 5, 0, 39) == [20]
    assert render.crop([-5, 10, 30, 400], (640, 360)) == (0, 10, 31, 350) and render.crop([639.6, 0, 700, 9], (640, 360)) is None
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "event1.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=5",
                        "-pix_fmt", "yuv420p", str(clip)], check=True)
        walker = {f: [10 + 5 * f, 40, 30 + 5 * f, 100] for f in range(50)}
        car = {f: [300 - 12 * f, 100, 340 - 12 * f, 140] for f in range(50)}  # off the frame from 3 s
        still = render.strobe(clip, {"vehicle": "car#1", "t_person_s": 2.0, "t_vehicle_s": 2.5}, walker, car, 10,
                              (320, 180), Path(tmp) / "event1-strobe.jpg")
        size = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                               str(Path(tmp) / "event1-strobe.jpg")], check=True, capture_output=True, text=True).stdout
    # cars every 1.0 s from the first arrival at 2.0 s: walker at 0-4 s, car at 0-2 s (then off the frame)
    assert still == {"image": "event1-strobe.jpg", "moments": 5, "step_s": 1.0} and size.strip() == "320,180"


def test_evidence_clips_save_one_road_position_per_clip_frame_for_the_hero_split():
    import analyze, subprocess, tempfile
    from pathlib import Path
    e = {"person": "p/0", "vehicle": "car#1", "t_person_s": 2.0, "t_vehicle_s": 2.4}
    feet = {f: (0.1 * f, 5.0) for f in range(0, 40, 2)}  # crowd mode: people every 2nd frame
    shapes = {f: ((20 - 0.5 * f, 4.0), (20 - 0.5 * f, 6.0)) for f in range(10, 50)}
    boxes = {f: [10 + 2 * f, 40, 30 + 2 * f, 100] for f in feet}
    old = analyze.listen.listen
    analyze.listen.listen = lambda *args: []  # no Wonder call
    try:
        with tempfile.TemporaryDirectory() as tmp:
            clip = Path(tmp) / "clip.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=8",
                            "-pix_fmt", "yuv420p", str(clip)], check=True)
            analyze.add_evidence(clip, clip, Path(tmp), [e], {"p/0": feet}, {"car#1": shapes}, {"p": boxes},
                                 {"car#1": {}}, None, (320, 180), [boxes])
            frames = analyze.frame_count(Path(tmp) / e["clip"])
    finally:
        analyze.listen.listen = old
    assert len(e["replay"]) == frames == 45  # 2 s before she was on the spot to 2 s after the car was
    assert e["replay"][0] == {"frame": 0, "person": [0.0, 5.0], "vehicle": None} and e["replay"][1]["person"] is None
    assert e["replay"][24]["vehicle"] == [[8.0, 4.0], [8.0, 6.0]]


def test_hero_split_steps_one_map_tile_per_clip_frame_beside_the_clip():
    import subprocess, tempfile
    from pathlib import Path
    from video import split
    replay = [{"frame": f, "person": [0.1 * f, 5.0] if f % 2 == 0 and f <= 40 else None,
               "vehicle": [[20 - 0.5 * f, 4.0], [20 - 0.5 * f, 6.0]] if f >= 10 else None} for f in range(45)]
    e = {"vehicle": "car#1", "tier": "serious", "pet_s": 0.4, "t_person_s": 2.0, "t_vehicle_s": 2.4, "where": [2.0, 5.0],
         "replay": replay}
    assert split.clock(e, -0.1) is None and split.clock(e, 0.25) == ("0.2 s", False)
    assert split.clock(e, 0.39) == ("0.4 s, serious near-miss, under 1.5 s", True)  # freezes on the page clock's frame
    tiles = split.page(e, 10).split("<svg")[1:]
    assert len(tiles) == 45 and 'class="ring"' not in tiles[19] and 'class="ring"' in tiles[20]  # from her arrival
    assert "frozen" not in tiles[23] and "0.3 s" in tiles[23] and "frozen" in tiles[24]
    assert 'class="feet"' in tiles[41] and 'class="feet"' not in tiles[42]  # a missing frame borrows one, not two
    with tempfile.TemporaryDirectory() as tmp:
        clip, sheet, hero = (Path(tmp) / name for name in ("event1.mp4", "tiles.png", "hero.mp4"))
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=2",
                        "-pix_fmt", "yuv420p", str(clip)], check=True)
        (w, h), cols, grey = split.TILE, split.COLS, lambda k: f"{20 + 18 * k:02x}" * 3
        shades = ",".join(f"drawbox=x={k % cols * w}:y={k // cols * h}:w={w}:h={h}:color=0x{grey(k)}:t=fill"
                          for k in range(12))  # tile k a flat grey, lighter each frame
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=black:size={cols * w}x{2 * h}",
                        "-vf", shades, "-frames:v", "1", str(sheet)], check=True)
        split.stack(clip, sheet, 12, 10, hero)
        size = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                               str(hero)], check=True, capture_output=True, text=True).stdout.strip()
        levels = subprocess.run(["ffmpeg", "-v", "error", "-i", str(hero), "-vf", f"crop={w}:{h}:{w}:0,scale=1:1,format=gray",
                                 "-f", "rawvideo", "-"], check=True, capture_output=True).stdout
    assert size == f"{2 * w},{h}" and len(levels) == 12 and all(b - a > 10 for a, b in zip(levels, levels[1:]))


def test_spark_verdicts_are_validated():
    ok = review.read_verdict('Sure: {"cyan_is_a_pedestrian": false, "road_user": "not a person", "reason": "a pole"}')
    assert ok == {"is_person": False, "road_user": "not a person", "reason": "a pole"}
    assert review.read_verdict('{"cyan_is_a_pedestrian": "yes", "road_user": "adult"}') is None
    assert review.read_verdict('{"cyan_is_a_pedestrian": true, "road_user": "alien"}') is None
    assert review.read_verdict("no json") is None and review.read_verdict("[1, 2]") is None
    assert review.read_verdict('{"cyan_is_a_pedestrian": true, "road_user": "not a person"}')["is_person"] is False
    # someone on a motorcycle or bicycle is a rider (a vehicle, as in SinD), even if Spark calls them a person
    assert review.read_verdict('{"cyan_is_a_pedestrian": true, "road_user": "rider"}')["is_person"] is False


def test_pack_keeps_people_and_escapes_text():
    base = {"person": "1/0", "vehicle": "car#1", "vehicle_kmh": 30.0, "pet_s": 0.5, "t_person_s": 3.0, "t_vehicle_s": 3.5,
            "gap_m": 0.4, "death_risk_pct": 1.5,
            "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5}, "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    pole = base | {"person": "9/0", "review": {"is_person": False, "road_user": "not a person", "reason": "pole"}}
    pole_again = base | {"person": "9/0", "vehicle": "car#2"}  # same pole, another car, never reviewed
    child = base | {"review": {"is_person": True, "road_user": "child", "reason": "<script>x</script>"}}
    unreviewed = base | {"person": "2/0"}
    assert pack.confirmed([pole, child, pole_again, unreviewed]) == [child, unreviewed]
    card = pack.event_card(1, child, 10)
    assert "&lt;script&gt;" in card and "<script>" not in card and "from a child" in card
    assert "from a pedestrian" in pack.event_card(2, base | {"review": {"is_person": True, "road_user": "unclear"}}, 10)


def test_spark_rider_call_needs_a_bike_under_the_person():
    from pathlib import Path
    import analyze
    rider = {"is_person": False, "road_user": "rider", "reason": "on a bike"}
    person = {f: [100, 100, 110, 130] for f in range(20)}
    bike = {5: [95, 110, 115, 135]}  # 2/3 of the person's box, on one frame
    assert review.gated(rider, person, [bike]) == rider
    assert review.gated(rider, person, [{5: [109, 100, 140, 130]}])["rider_unconfirmed"]  # 10% inside: no bike
    kept = review.gated(rider, person, [], 4.0)
    assert kept == rider | {"is_person": True, "rider_unconfirmed": True, "walk_kmh": 4.0}
    shadow = {"is_person": False, "road_user": "not a person", "reason": "a shadow"}
    assert review.gated(shadow, person, []) == shadow and review.gated(None, person, []) is None
    # analyze: only rideable concepts' boxes count, and the walking speed is measured on the piece
    original = review.review
    review.review = lambda *a, **k: dict(rider)
    try:
        for vehicle, rejected in (("motorcycle#1", True), ("vehicle#1", True), ("car#1", False)):
            events = [{"person": "7/0"}]
            analyze.review_people(None, Path("."), events, {"7/0": {f: (0.14 * f, 0.0) for f in range(20)}},
                                  {"7": person}, {vehicle: bike}, None, (640, 360), False)
            assert (events[0]["review"]["is_person"] is False) == rejected
    finally:
        review.review = original
    assert events[0]["review"]["walk_kmh"] == 5.0  # 1.4 m/s


def test_unconfirmed_rider_stays_a_pedestrian_on_the_card_and_in_the_facts():
    e = {"person": "1/0", "vehicle": "car#1", "tier": "serious", "vehicle_kmh": 30.0, "pet_s": 0.5, "t_person_s": 3.0,
         "t_vehicle_s": 3.5, "gap_m": 0.4, "death_risk_pct": 1.5,
         "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5}, "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}},
         "review": {"is_person": True, "road_user": "rider", "reason": "", "rider_unconfirmed": True, "walk_kmh": 4.0}}
    label = "pedestrian (Spark thought rider; no bike found under them; measured walking 4.0 km/h)"
    assert pack.confirmed([e]) == [e]
    assert html.escape("from a " + label) in pack.event_card(1, e, 10)
    assert json.loads(pack.facts({}, [e], {"minutes": 1}))["worst"][0]["road_user"] == label
    assert review.unconfirmed_rider({"is_person": False, "road_user": "rider"}) is None


def test_dut_score_keeps_review_rejections_apart_from_threshold_misses():
    """A conflict found and then rejected by Spark passed every threshold: it is missed_by_review, not 'at a threshold'."""
    import validate_dut
    truth = [{"person": p, "vehicle": "car#1", "tier": "serious", "pet_s": 0.5, "t_person_s": 1.0, "vehicle_kmh": 12.0}
             for p in ("a", "b", "c")]
    ours = lambda pid, verdict: {**truth[0], "person": pid, "vehicle": "car#x", "review": verdict}
    events = [ours("p1/0", None), ours("p2/0", {"is_person": False, "road_user": "rider", "reason": ""})]
    result = validate_dut.score(truth, events, {}, {}, {}, {}, {"p1/0": "a", "p2/0": "b"}, {"car#x": "car#1"})
    assert (result["matched"], result["missed"], result["missed_by_review"], result["missed_at_threshold"]) == (1, 2, 1, 0)
    assert result["before_review"] == {"matched": 2, "missed": 1, "extra": 0}
    assert [m["by_review"] for m in result["missed_events"]] == [True, False]


def test_offline_dut_check_puts_stored_verdicts_through_todays_rider_gate():
    """validate_offline: a stored rider call with no bike under the person is overruled, one with a motorcycle under
    them stands, "not a person" stands, an old run's "cyclist" kept as a pedestrian is re-read by today's rule, and a
    piece Spark never saw stays unreviewed."""
    import validate_offline
    said = lambda ok, who: {"is_person": ok, "road_user": who, "reason": ""}
    stored = [{"person": "a/0", "review": said(False, "rider")}, {"person": "b/0", "review": said(False, "rider")},
              {"person": "c/0", "review": said(False, "not a person")}, {"person": "d/0", "review": said(True, "cyclist")}]
    verdicts = validate_offline.stored_verdicts(stored)
    assert verdicts["d/0"]["is_person"] is False
    people = {p: {f: (0.0, 0.14 * f) for f in range(20)} for p in ("a/0", "b/0", "c/0", "d/0", "e/0")}
    boxes = {p[0]: {f: [100.0 * i, 0, 100.0 * i + 10, 20] for f in range(20)} for i, p in enumerate(people)}
    bike = {"motorcycle#1": {f: [95, -5, 115, 30] for f in range(20)}}  # under person b only
    events = [{"person": p, "vehicle": "car#1"} for p in people]
    events = validate_offline.with_verdicts(events, verdicts, boxes, bike, people)
    assert [(e.get("review") or {}).get("is_person") for e in events] == [True, False, False, True, None]
    assert events[0]["review"]["rider_unconfirmed"] and events[0]["review"]["walk_kmh"] == 5.0
    assert "review" not in events[4]


def test_offline_speed_check_reads_the_dataset_at_its_own_frame_rate():
    """validate_offline's speed reference: a DUT car at 3 m/s reads 3 m/s on its evenly spaced 23.976 fps frames,
    with no speed where a frame lacks neighbours; the summary counts cars near the 10 km/h bar put on the wrong side."""
    import tempfile
    from pathlib import Path
    import validate_dut, validate_offline
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "data" / "trajectories_filtered"
        folder.mkdir(parents=True)
        rows = "".join(f"1,{s},{3.0 * (s - 1) / validate_dut.SOURCE_FPS},0\n" for s in range(1, 50))
        (folder / "intersection_99_traj_veh_filtered.csv").write_text("id,frame,x_est,y_est\n" + rows)
        native = validate_offline.native_speeds(Path(tmp), "99")["car#1"]
    assert native[0] is None and native[10] is not None
    assert all(abs(v - 3.0) < 1e-9 for v in native.values() if v is not None)
    kmh = lambda ours, ref: (ours / 3.6, ref / 3.6)
    summary = validate_offline.speed_summary([kmh(9.5, 10.5), kmh(12, 12), kmh(20, 21)])
    assert summary == {"frames": 3, "mean_abs_kmh": 0.67, "p95_abs_kmh": 1.0, "near_bar_wrong_side_pct": 50.0}


def test_rebuilt_tracks_follow_auto_modes_switch_to_frame_by_frame():
    """validate_dut.our_tracks (validate_offline, validate_gate) rebuilds an auto-mode run as analyze.py ran it: a
    concept whose cached video reply filled up is read from its frame-by-frame replies."""
    import subprocess, tempfile
    from pathlib import Path
    import crowd, validate_dut
    box = "<|box;x1=1;y1=1;x2=5;y2=5;w=64;h=48|>"
    site = {"image_points": SQUARE_IMG, "world_points": SQUARE_ROAD, "person": "person", "vehicles": ["car"],
            "vehicle_mode": "auto"}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10:duration=2",
                        "-pix_fmt", "yuv420p", str(out / "clip.mp4")], check=True)
        sam.cache_path(out, "person").write_text("")
        sam.cache_path(out, "car").write_text("<5f>" + "".join(f"{i}{box}" for i in range(sam.MAX_OBJECTS)))
        asked, real = [], crowd.track
        crowd.track = lambda clip, frames, fps, concept, *_: asked.append(concept) or {}
        try:
            validate_dut.our_tracks(site, out)
        finally:
            crowd.track = real
    assert asked == ["car"]


def test_gate_speed_trap_checks_each_logged_vehicle_against_its_one_track():
    """validate_gate (G6): the four tape marks make two lines 15 m apart through the calibration; a logged vehicle is
    compared with the one track on both lines at its logged moments, in either direction, and two tracks or none are
    reported, never guessed. G6 needs 20 matched vehicles, 80% within 15% or 2 km/h and a median lean within 10%."""
    import tempfile
    from pathlib import Path
    import analyze, validate_gate
    H = road.homography([[250, 100], [350, 100], [500, 300], [100, 300]], [[0, 0], [20, 0], [20, 8], [0, 8]])
    marks = [list(road.to_image(H, x, y)) for x, y in ((2.5, 0), (17.5, 0), (17.5, 8), (2.5, 8))]
    lines = validate_gate.trap_lines({"trap": {"image_points": marks}}, H)
    assert abs(validate_gate.lines_apart(*lines) - 15) < 1e-6
    fps = analyze.FPS  # a 2 m edge driving along the road; `scale` > 1 reads distances, so speeds, that much long
    drive = lambda kmh, y, x0, scale=1.0: {f: tuple((scale * (x0 + kmh / 3.6 * f / fps) + d, y) for d in (-1, 1))
                                           for f in range(120)}
    vehicles = {"car#1": drive(25, 2, 0), "motorcycle#2": drive(-30, 6, 20, 1.1),
                "car#3": drive(20, 2, -20), "car#4": drive(20, 6, -20)}  # side by side
    rows = validate_gate.check(vehicles, lines, 15, [(0.36, 2.52), (2.1, 0.3), (4.05, 6.75), (10.0, 11.0)])
    assert [(r["vehicle"], r["why"]) for r in rows] == [("car#1", None), ("motorcycle#2", None),
                                                       (None, "2 tracks on both lines"), (None, "no track on both lines")]
    assert [round(r["trap_kmh"], 1) for r in rows[:2]] == [25.0, 30.0]
    assert [round(r["ours_kmh"], 1) for r in rows[:2]] == [25.0, 33.0]
    assert "NOT TESTED: 19 matched" in validate_gate.g6([(25.0, 25.0)] * 19)
    assert validate_gate.g6([(25.0, 26.0)] * 16 + [(25.0, 35.0)] * 4).startswith("G6 PASS: 16 of 20")
    assert validate_gate.g6([(25.0, 26.0)] * 15 + [(25.0, 35.0)] * 5).startswith("G6 FAIL: 15 of 20")
    assert validate_gate.g6([(25.0, 27.6)] * 20).startswith("G6 FAIL: 20 of 20")  # all within 15%, all 10.4% fast
    assert validate_gate.agrees(8.0, 9.9) and not validate_gate.agrees(8.0, 10.1)  # 2 km/h, not 15%, when slow

    def refused(call):
        try:
            call()
        except SystemExit as err:
            return str(err)
        raise AssertionError("accepted")
    with tempfile.TemporaryDirectory() as tmp:
        log, site = Path(tmp) / "trap.csv", Path(tmp) / "site.json"
        log.write_text("line_a_s,line_b_s,note\n0.36,2.52,white car\n2.1,0.3,\n")
        assert validate_gate.read_log(log) == [(0.36, 2.52), (2.1, 0.3)]
        for bad in ("1.0,1.0", "1.0,nan", "1.0,", "-1,2"):
            log.write_text("line_a_s,line_b_s\n" + bad + "\n")
            assert "line 2" in refused(lambda: validate_gate.read_log(log))
        one = {"image_points": SQUARE_IMG, "world_points": SQUARE_ROAD, "vehicles": ["car"]}
        site.write_text(json.dumps(one | {"trap": {"image_points": marks, "distance_m": 15}}))
        assert analyze.load_site(site)["trap"]["distance_m"] == 15
        for trap in ({"image_points": marks[:3], "distance_m": 15}, {"image_points": marks, "distance_m": 0}, marks):
            site.write_text(json.dumps(one | {"trap": trap}))
            assert "trap must be" in refused(lambda: analyze.load_site(site))


def test_page_links_find_an_event_card_and_its_moment():
    """A page link to #event-N finds card N, and data-t is when, in its clip, the near-miss begins."""
    e = {"vehicle": "car#1", "vehicle_kmh": 30.0, "pet_s": 2.5, "t_person_s": 6.0, "t_vehicle_s": 3.5, "gap_m": 0.4,
         "death_risk_pct": 1.5, "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5},
                                               "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    assert '<article class="card" id="event-3" data-t="2.00">' in pack.event_card(3, e, 10)  # clip starts at 1.5 s
    assert 'data-t="1.00"' in pack.event_card(1, e | {"t_vehicle_s": 1.0}, 10)  # clip starts at 0, not -1 s


def test_cards_open_with_their_stromotion_still_only_when_there_is_one():
    e = {"vehicle": "motorcycle#1", "vehicle_kmh": 30.0, "pet_s": 0.5, "t_person_s": 3.0, "t_vehicle_s": 3.5,
         "gap_m": 0.4, "death_risk_pct": 1.5, "clip": "event1.mp4",
         "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5}, "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    assert overlay.strobe(e) == "" and "<figure" not in pack.event_card(1, e, 10)
    card = pack.event_card(1, e | {"strobe": {"image": "event1-strobe.jpg", "moments": 9, "step_s": 0.5}}, 10)
    assert card.index('<img src="event1-strobe.jpg"') < card.index("<video")  # at the top of the card
    assert "Composite of 9 moments, 0.5 s apart" in card and "the motorcycle in red" in card


def test_gap_clock_says_who_came_first_and_freezes_on_the_tier():
    e = {"person": "1/0", "vehicle": "motorcycle#c28", "tier": "serious", "pet_s": 0.8, "t_person_s": 3.0,
         "t_vehicle_s": 3.8, "vehicle_kmh": 30.0, "gap_m": 0.4, "death_risk_pct": 1.5, "clip": "event1.mp4",
         "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5}, "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    assert overlay.clock_text(e) == "The motorcycle reached the pedestrian's spot 0.8 s after they left it."
    assert overlay.clock_text(e | {"t_vehicle_s": 2.4, "pet_s": 0.6000000000000001}) == (
        "The pedestrian stepped where the motorcycle was 0.6 s earlier.")
    assert overlay.clock_text(e | {"t_vehicle_s": 3.0, "pet_s": 0.0}) == (
        "The pedestrian and the motorcycle were on the same spot at once.")
    clock = overlay.clip("<video></video>", e | {"tier": "close pass", "pet_s": 2.0})
    assert 'data-pet="2.0" data-word="close pass, 1.5-3.0 s">2.0 s, close pass, 1.5-3.0 s</span>' in clock  # no JS: final gap
    assert overlay.clip("", e) == '<p class="gap">The motorcycle reached the pedestrian&#x27;s spot 0.8 s after they left it.</p>'
    page = pack.page({"world_points": SQUARE_ROAD}, [e], {"minutes": 0.3}, None, None, 10)
    assert '<div class="clip"><video src="event1.mp4"' in page and 'data-word="serious near-miss, under 1.5 s"' in page
    assert page.count("<script>") == 1 and "requestAnimationFrame" in page and page.index("<script>") > page.index("event-1")


def test_stopping_strip_runs_past_the_spot_only_on_the_worst_fast_person_first_card():
    assert round(overlay.stopping_m(38), 2) == 23.79 and round(overlay.stopping_m(20), 1) == 10.5
    site = {"image_points": SQUARE_IMG, "world_points": SQUARE_ROAD}  # 20 px a metre; zone -10..20 m
    e = {"person": "1/0", "vehicle": "car#1", "tier": "serious", "pet_s": 1.2, "t_person_s": 3.0, "t_vehicle_s": 4.2,
         "vehicle_kmh": 38.0, "gap_m": 0.4, "death_risk_pct": 1.5, "clip": "event1.mp4", "where": [8.0, 5.0],
         "path_vehicle": [[x, 5.0] for x in range(-8, 14)],
         "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5}, "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    drawn = overlay.strip(e, site, [e])
    assert "needed 23.8 m to stop, had 12.7 m" in drawn and "stopped in 10.5 m, short of the spot" in drawn
    assert "Not new evidence" in drawn and all(f'class="{c}"' in drawn for c in ("red", "green", "ring"))
    stop, H, zone = overlay.stopping(e), road.homography(SQUARE_IMG, SQUARE_ROAD), road.zone_around(SQUARE_ROAD)
    red = overlay.strip_pixels(stop, stop["needed_m"], overlay.STRIP_WIDTH_M, zone, H)  # from 12.7 m back to 23.8 m on
    assert math.dist(red[0], (100 + 20 * (8 - 38 / 3.6 * 1.2), 182)) < 1e-6 and abs(red[1][0] - 482.4) < 2
    fast = overlay.stopping(e | {"vehicle_kmh": 60.0})  # 20 m back and 44.8 m long: cut to the zone, -10 to 20 m
    assert [round(p[0]) for p in overlay.strip_pixels(fast, fast["needed_m"], 1.8, zone, H)] == [-100, 500, 500, -100]
    vehicle_first = e | {"t_vehicle_s": 1.8}
    assert overlay.strip(vehicle_first, site, [vehicle_first]) == ""
    for no in ({"vehicle_kmh": 24.9, "pet_s": 2.0, "t_vehicle_s": 5.0},  # slow, though 13.8 m away
               {"pet_s": 0.9, "t_vehicle_s": 3.9},  # 9.5 m away: under 10.5 m, the go/no-go fails
               {"path_vehicle": [[x, 5.0] for x in range(-8, 2)] + [[2.0, y] for y in range(6, 16)]}):  # turns 90 degrees
        assert overlay.strip(e | no, site, [e | no]) == "", no
    second = e | {"person": "2/0"}
    assert overlay.strip(second, site, [e, second]) == "" and overlay.strip(e, site, [vehicle_first, e]) == drawn
    page = pack.page(site, [vehicle_first, e, second], {"minutes": 0.3}, None, None, 10)
    assert page.count('<svg class="strip"') == 1 and page.index('<svg class="strip"') > page.index('id="event-2"')
    assert '<div class="clip"><video' in page and "viewBox" in page
    assert '<svg class="strip"' not in pack.page(site, [e | {"clip": None}], {"minutes": 0.3}, None, None, 10)


def test_long_videos_are_tracked_in_overlapping_parts_and_ids_joined():
    import subprocess, tempfile
    from pathlib import Path
    import analyze
    box = "<|box;x1=10;y1=10;x2=20;y2=30;w=64;h=48|>"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        clip = out / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10:duration=5",
                        "-pix_fmt", "yuv420p", str(clip)], check=True)
        old = analyze.CHUNK_FRAMES, analyze.OVERLAP_FRAMES
        analyze.CHUNK_FRAMES, analyze.OVERLAP_FRAMES = 20, 5
        try:
            pieces = analyze.parts(clip, out, analyze.frame_count(clip))
            # part 0 sees a person on its last 5 frames; part 1 sees the same person on its first 5 (the overlap);
            # part 2 sees someone else, elsewhere
            sam.cache_path(pieces[0][2], "person").write_text("".join(f"<{f}f>0{box}" for f in range(15, 20)))
            sam.cache_path(pieces[1][2], "person").write_text("".join(f"<{f}f>3{box}" for f in range(0, 8)))
            sam.cache_path(pieces[2][2], "person").write_text("<0f>1<|box;x1=40;y1=10;x2=50;y2=30;w=64;h=48|>")
            tracks = analyze.track_all(pieces, "person", "unused-key", (64, 48))
        finally:
            analyze.CHUNK_FRAMES, analyze.OVERLAP_FRAMES = old
    assert [p[0] for p in pieces] == [0, 15, 30]
    assert set(tracks) == {"0.0:0", "2.0:1"} and sorted(tracks["0.0:0"]) == list(range(15, 23))



def test_sam_requests_that_hit_the_object_limit_are_counted():
    import tempfile
    from pathlib import Path
    import analyze
    box = "<|box;x1=1;y1=1;x2=5;y2=5;w=64;h=48|>"
    with tempfile.TemporaryDirectory() as tmp:
        a, b = Path(tmp) / "a", Path(tmp) / "b"
        a.mkdir(), b.mkdir()
        sam.cache_path(a, "car").write_text("<0f>" + "".join(f"{i}{box}" for i in range(sam.MAX_OBJECTS)))
        sam.cache_path(b, "car").write_text("<0f>0" + box)
        pieces = [(0, None, a), (130, None, b)]
        assert analyze.full_requests(pieces, [("car", 1)], (64, 48)) == (1, 2)

def test_budget_is_a_hard_cap_on_new_sam_spending():
    import contextlib, io, tempfile
    from pathlib import Path
    import analyze
    assert analyze.spend_cap(5.0, True) == 5.0  # --allow-cost does not lift a --budget
    assert analyze.spend_cap(None, True) == math.inf and analyze.spend_cap(None, False) == analyze.MAX_COST_USD
    with tempfile.TemporaryDirectory() as tmp:
        pieces = [(first, None, Path(tmp) / name) for first, name in ((0, "a"), (130, "b"), (260, "c"))]
        for _, _, folder in pieces:
            folder.mkdir()
        assert analyze.billed_frames(pieces, 290) == [150, 150, 50]  # overlaps billed; a 30-frame last part bills 50
        sam.cache_path(pieces[0][2], "car").write_text("")  # part a is cached: not paid again
        with contextlib.redirect_stdout(io.StringIO()):
            new, whole = analyze.check_cost(pieces, [("car", 1)], (64, 48), 290, 0.04)
            assert (round(new, 4), round(whole, 4)) == (0.04, 0.07)  # $0.20 per 1,000 frames
            try:
                analyze.check_cost(pieces, [("car", 1)], (64, 48), 290, 0.039)
                raise AssertionError("over the budget accepted")
            except SystemExit as err:
                assert "$0.04 is over the $0.04" in str(err) and "--budget" in str(err)


def test_vehicle_concept_test_matches_vehicle_boxes_to_the_three_concepts_and_never_sends_without_spend():
    """vehicle_test.py: a box two concepts both found counts once, each is found by one "vehicle" box at IoU 0.5,
    and "vehicle" is adopted only at 95% recall. Nothing is sent without --spend."""
    import contextlib, io, tempfile
    from pathlib import Path
    import crowd, vehicle_test
    reply = lambda boxes: "<0f>" + ",".join(f"{i}<|box;x1={b[0]};y1={b[1]};x2={b[2]};y2={b[3]};w=640;h=360|>"
                                            for i, b in enumerate(boxes))
    car, bike, auto, bus = [0, 0, 40, 20], [100, 0, 120, 30], [200, 0, 230, 25], [300, 0, 380, 40]
    cached = {"car": [car], "motorcycle": [bike, [1, 0, 41, 20]], "auto rickshaw": [auto]}  # the motorcycle one boxed the car too
    real = crowd.request
    crowd.request = lambda *a: (_ for _ in ()).throw(AssertionError("sent to SAM"))
    try:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            out = Path(tmp)
            for concept, boxes in cached.items():
                crowd.cache_dir(out, concept).mkdir()
                for f in (0, 2):
                    (crowd.cache_dir(out, concept) / f"{f:06d}.sam.txt").write_text(reply(boxes))
            try:
                vehicle_test.main([tmp])
                raise AssertionError("ran without --spend")
            except SystemExit as err:
                assert "--spend" in str(err)
            crowd.cache_dir(out, "vehicle").mkdir()
            for f, boxes in ((0, [car, bike, auto, bus]), (2, [car, bus])):
                (crowd.cache_dir(out, "vehicle") / f"{f:06d}.sam.txt").write_text(reply(boxes))
            result = vehicle_test.main([tmp])  # all cached: free, no --spend needed
            assert json.loads((out / "vehicle-test-result.json").read_text()) == result
    finally:
        crowd.request = real
    assert result["per_concept"] == {"car": {"found": 2, "of": 2}, "motorcycle": {"found": 1, "of": 2},
                                     "auto rickshaw": {"found": 1, "of": 2}}
    assert result["recall"] == 0.667 and not result["adopt"] and result["vehicle_boxes_matching_none"] == 2  # the bus
    assert vehicle_test.ADOPT_RECALL == 0.95 and vehicle_test.spread(list(range(10)), 3) == [0, 4, 9]


def test_auto_mode_switches_a_concept_whose_video_requests_fill_up():
    import tempfile
    from pathlib import Path
    import analyze, crowd
    box = "<|box;x1=1;y1=1;x2=5;y2=5;w=64;h=48|>"
    fills_at = lambda frame: "<0f>" + "".join(f"{i}{box}" for i in range(sam.MAX_OBJECTS - 1)) + f"<{frame}f>99{box}"
    assert sam.saturation_frame(sam.parse(fills_at(16))) == 16
    assert sam.saturation_frame(sam.parse("<0f>" + "".join(f"{i}{box}" for i in range(15)))) is None
    site = {"person": "person", "vehicles": ["car"], "person_mode": "auto"}
    with tempfile.TemporaryDirectory() as tmp:
        pieces = [(first, None, Path(tmp) / name) for first, name in ((0, "a"), (130, "b"), (260, "c"))]
        for (_, _, folder), frame in zip(pieces, (16, 135, 135)):  # b's late fill is covered by part c; c is last
            folder.mkdir()
            sam.cache_path(folder, "person").write_text(fills_at(frame))
            sam.cache_path(folder, "car").write_text(fills_at(10))  # full too, but cars stay in video mode
        switched = analyze.auto_switch(site, pieces, [("person", 1), ("car", 1)], None, (64, 48))
        assert switched == {"person": [1.6, 13.5]}
        jumps, real = {}, crowd.track
        crowd.track = lambda clip, frames, fps, concept, key, cache, jump: jumps.update({concept: jump}) or {}
        try:
            analyze.concept_tracks(site, "person", None, 20, pieces, Path(tmp), None, (64, 48), 1, switched)
        finally:
            crowd.track = real
        assert jumps == {"person": math.inf}  # detected frame by frame
    note = analyze.switch_note("person", switched["person"], 3)
    assert note == "person: 16 objects taken within 1.6-13.5 s in 2 of 3 parts, so frame-by-frame was used"
    assert "within 1.0 s in 1 of 1 part," in analyze.switch_note("vehicle", [1.0], 1)
    page = pack.limit_note([0, 4, [note]])
    assert "at most 16 objects per request. person: 16 objects taken within 1.6-13.5 s" in page and "minimum" not in page
    assert pack.limit_note([0, 4, []]) == "" and "minimum" in pack.limit_note([1, 4, [note]])


def test_crowds_are_tiled_and_cut_boxes_joined():
    import analyze
    assert analyze.tiles((640, 360), 1) == [(0, 0, 640, 360)]
    assert analyze.tiles((640, 360), 2) == [(0, 0, 368, 206), (272, 0, 368, 206), (0, 154, 368, 206), (272, 154, 368, 206)]
    full, cut = {5: [300, 100, 330, 160]}, {5: [300, 100, 310, 160]}  # the same person, cut by a tile edge
    joined = analyze.link({"a": full}, {"b": cut})
    assert joined == {"a": {5: [300, 100, 330, 160]}}
    apart = analyze.link({"a": full}, {"c": {5: [100, 100, 130, 160]}})
    assert set(apart) == {"a", "c"}


def test_wonder_sounds_are_validated_and_silent_videos_skipped():
    import subprocess, tempfile
    from pathlib import Path
    reply = 'Heard: {"sounds": [{"t_s": 2.6, "sound": "brakes"}, {"t_s": 9, "sound": "horn"}, {"t_s": 1, "sound": "dog"}]}'
    assert listen.read_sounds(reply, 6.0) == [{"t_s": 2.6, "sound": "brakes"}]  # out of range and unknown dropped
    assert listen.read_sounds("nothing", 6.0) is None
    assert "brakes 0.4 s before" in pack.heard_line([{"t_s": -0.4, "sound": "brakes"}])
    with tempfile.TemporaryDirectory() as tmp:
        silent = Path(tmp) / "silent.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10:duration=2",
                        "-pix_fmt", "yuv420p", str(silent)], check=True)
        event = {"t_person_s": 1.0, "t_vehicle_s": 1.0}
        assert listen.listen(silent, event, Path(tmp) / "e.wav", "unused-key") is None  # no audio: no API call


def test_close_passes_and_exposure_never_read_as_safe():
    fps, frames = 10, 60
    late = {f: (0.0, 1.5 * (f - 20) / 10) for f in range(0, 21)}  # leaves the spot 2.0 s before the car arrives
    car = edges_along_x(8.0, fps, frames)  # centred at x=0 on frame 30... shifted below
    car = {f + 10: e for f, e in car.items()}
    events = road.conflicts({"p": late}, {"car#1": car}, fps)
    assert events and events[0]["tier"] == "close pass" and 1.5 <= events[0]["pet_s"] < 3.0
    seen = road.exposure({"p": walking_across(40)}, {"car#1": edges_along_x(8.0, fps, frames)}, fps, 600)
    assert {k: seen[k] for k in ("minutes", "crossings", "vehicles", "speed_85th_kmh")} == {
        "minutes": 1.0, "crossings": 1, "vehicles": 1, "speed_85th_kmh": 28.8}
    tiles = " ".join(pack.stats([], seen))  # the tiles and the line of other counts
    assert "pedestrian crossings watched" in tiles and "85% of vehicles" in tiles and "conflicts per 100" not in tiles
    assert pack.headline([], seen, {})[0] == "0 of 1 crossings had a moving vehicle through the same spot within 3 s " \
                                             "of the person; 0 of 1 within 1.5 s."


def test_exact_ranges_match_published_values():
    """Garwood's exact Poisson range and Clopper-Pearson's for k of n, checked against published tables."""
    assert [round(v, 2) for v in pack.poisson_range(0)] == [0.0, 3.69]  # never "safe": 0 seen, up to 3.7 expected
    assert [round(v, 2) for v in pack.poisson_range(9)] == [4.12, 17.08]
    assert [round(v, 4) for v in pack.share_range(3, 10)] == [0.0667, 0.6525]
    assert [round(v, 4) for v in pack.share_range(0, 10)] == [0.0, round(1 - 0.025 ** 0.1, 4)]
    assert [round(v, 4) for v in pack.share_range(10, 10)] == [round(0.025 ** 0.1, 4), 1.0]
    low, high = pack.share_range(40, 2000)  # large n: logs, not factorials
    assert 0.0143 < low < 0.0144 and 0.0271 < high < 0.0273


def test_headline_counts_each_person_who_crossed_once():
    """k of n: one person in two track pieces passed by two vehicles is one, and someone exposure never counted as
    crossing is not in k, so k never exceeds n. Without exposure's crosser list there is no headline."""
    seen = road.exposure({"p/0": walking_across(40), "p/1": walking_across(40), "q/0": walking_across(40)}, {}, 10, 600)
    assert seen["crossers"] == ["p", "q"] and seen["crossings"] == 2
    hit = lambda person, pet: {"person": person, "vehicle": f"car#{pet}", "pet_s": pet, "vehicle_kmh": 30.0,
                               "t_person_s": 5.0, "t_vehicle_s": 5.0 + pet, "death_risk_pct": 1.5, "with_limit": {"20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}},
                               "tier": "serious" if pet < road.PET_MAX_S else "close pass"}
    events = [hit("c1/0", 0.4), hit("c1/1", 2.0), hit("c1/0", 1.0), hit("c2/0", 2.5), hit("pole/0", 0.1)]
    seen = {"minutes": 1.0, "duration_s": 60.0, "crossings": 9, "crossers": [f"c{i}" for i in range(1, 10)]}
    lines = pack.headline(events, seen, {})
    assert lines[0] == ("2 of 9 crossings (1 in 4.5) had a moving vehicle through the same spot within 3 s of the "
                        "person; 1 of 9 (1 in 9) within 1.5 s.")
    assert "Clopper-Pearson" in lines[1] and "Poisson" in lines[1] and len(lines) == 2
    measured = pack.facts({"name": "gate"}, events, seen)
    assert next(iter(json.loads(measured))) == "headline" and lines[0] in measured and '"c1"' not in measured
    quiet = pack.headline([], seen, {})[0]
    assert quiet.startswith("0 of 9 crossings had") and f'<p class="lead">{quiet}</p>' in pack.page(
        {"name": "gate", "world_points": SQUARE_ROAD}, [], seen, None, None, 10)
    assert pack.headline(events, {"crossings": 9, "minutes": 1.0}, {}) == []  # an older events.json
    assert "headline" not in pack.facts({"name": "gate"}, events, {"crossings": 9, "minutes": 1.0})


def test_headline_leaves_out_crossers_spark_rejected():
    """A crosser Spark called 'not a person' leaves n as well as k; one with any piece still confirmed stays."""
    hit = lambda person, verdict: {"person": person, "vehicle": "car#1", "pet_s": 0.4, "tier": "serious",
                                   **({"review": {"is_person": verdict}} if verdict is not None else {})}
    events = [hit("c1/0", True), hit("rider/0", False), hit("c2/0", False), hit("c2/1", None)]
    seen = {"minutes": 1.0, "crossings": 4, "crossers": ["c1", "c2", "c3", "rider"]}
    kept = pack.real_crossers(events, seen)
    assert kept["crossers"] == ["c1", "c2", "c3"] and seen["crossers"][-1] == "rider" and kept["crossings"] == 4
    assert pack.headline(pack.confirmed(events), kept, {})[0].startswith("2 of 3 crossings")
    assert pack.real_crossers(events, {"minutes": 1.0}) == {"minutes": 1.0}  # an older events.json


def test_school_year_line_needs_both_site_keys_and_15_minutes():
    events = [{"person": "c1/0", "vehicle": "car#1", "pet_s": 0.5, "tier": "serious"}]
    seen = {"minutes": 20.0, "duration_s": 1200.0, "crossings": 40, "crossers": [f"c{i}" for i in range(40)]}
    school = {"school_days": 200, "dismissal_minutes": 30}
    year = pack.headline(events, seen, school)[-1]
    assert year == ("If every dismissal is like this one: about 300 crossings a school year with a moving vehicle "
                    "through the same spot within 3 s, about 300 within 1.5 s (200 school days, 30-minute dismissals).")
    assert "about 300 crossings" in pack.headline(events, seen, {**school, "school_days": 197})[-1]  # not 295.5
    # 0 seen is never "about 0": Poisson's upper bound 3.69, scaled the same way (x 30 / 20 x 200)
    close = [{**events[0], "pet_s": 2.0, "tier": "close"}]
    assert ("about 300 crossings a school year with a moving vehicle through the same spot within 3 s, up to 1,100 "
            "within 1.5 s") in pack.headline(close, seen, school)[-1]
    assert pack.headline([], seen, school)[-1].startswith("If every dismissal is like this one: up to 1,100 crossings")
    assert not any("dismissal" in line for line in pack.headline(events, seen, {"school_days": 200}))
    short = {**seen, "minutes": 14.9, "duration_s": 894.0}
    assert not any("dismissal" in line for line in pack.headline(events, short, school))
    assert not any("dismissal" in line for line in pack.headline(events, seen, {**school, "school_days": "200"}))



def test_traffic_gaps_are_measured_where_people_crossed():
    cells = road.crossing_cells({"p": walking_across(40)}, 10)  # the column of 2 m cells at x = 0..2
    moving = edges_along_x(8.0, 10, 60)  # some point of it in those cells on frames 29-33
    parked = {f: ((-1.0, 2.0), (1.0, 2.0)) for f in range(600)}
    gaps = road.traffic_gaps({"car#1": moving, "car#2": parked}, 10, cells, 600)
    assert [round(g, 1) for g in gaps] == [2.9, 56.6]
    seen = road.exposure({"p": walking_across(40)}, {"car#1": moving}, 10, 600)
    assert seen["gaps_6s"] == 1 and seen["gaps_12s"] == 1 and seen["longest_gap_s"] == 56.6
    assert seen["gap_6s_share_pct"] == 94.3 and seen["duration_s"] == 60.0
    assert "gaps_6s" not in road.exposure({}, {"car#1": moving}, 10, 600)  # nobody crossed: no crossing to time


def test_pv2_and_engineering_numbers_say_when_they_are_scaled():
    assert road.pv2(crossings=100, vehicles=500, minutes=30) == 2e8  # 200/h x 1000/h squared
    seen = {"minutes": 30, "crossings": 100, "vehicles": 500, "gaps_6s": 4, "gaps_12s": 1, "longest_gap_s": 14.0,
            "gap_6s_share_pct": 12.5}
    text = pack.engineering(seen, {"sam_usd": 1.5})
    assert "2.0 x 10^8" in text and "IRC:103-2012" in text and "scaled from 30 minutes" in text
    assert "4 gaps" in text and "12.5% of the time" in text and "about $3.00 per hour" in text
    plain = " ".join(pack.engineering_lines(seen, {"sam_usd": 1.5}))
    assert "at Meta's list prices" in plain and "image detection" not in plain
    exact = pack.engineering_lines({"minutes": 20.2, "duration_s": 1215.0, "crossings": 500, "vehicles": 2000}, None)
    assert f"{road.pv2(500, 2000, 20.25) / 1e8:.1f} x 10^8" in exact[0]  # from the exact 20.25 min, not 20.2
    short = pack.engineering_lines({"minutes": 0.2, "duration_s": 15.0, "crossings": 5, "vehicles": 20}, None)
    assert "x 10^8" not in short[0] and "at least 15 minutes" in short[0]
    crowd = pack.engineering({"minutes": 10}, {"sam_usd": 7.2, "image_usd": 6.0})
    assert "SAM cost for this pack: about $7.20 at Meta&#x27;s list prices (about $6.00 of it image detection)" in crowd
    assert "guess" not in crowd
    import analyze, contextlib, io  # Meta's list price for SAM images is $2.50 per 1,000
    with contextlib.redirect_stdout(io.StringIO()):
        assert analyze.check_cost([(0, None, None)], [], None, 100, analyze.MAX_COST_USD, 1000, 1000) == (2.5, 2.5)
    assert pack.engineering({"minutes": 0}, None) == ""
    assert "2 of 10" in pack.limit_note([2, 10]) and pack.limit_note([0, 10]) == pack.limit_note(None) == ""

def brute_force_pet(feet, shapes, fps, pet_max):
    """Reference: every pedestrian frame against every vehicle frame, no index."""
    speed, reach, best = road.speeds(shapes, fps), round(pet_max * fps), None
    for fp, p in feet.items():
        for fv, shape in shapes.items():
            if abs(fv - fp) >= reach or speed.get(fv, 0.0) < road.MOVING_MPS:
                continue
            gap = road.footprint_distance(p, shape)
            if gap <= road.CONFLICT_RADIUS_M and (best is None or (abs(fv - fp), gap) < best):
                best = (abs(fv - fp), gap)
    return best


def test_grid_index_finds_exactly_what_brute_force_finds():
    import random
    rng = random.Random(7)
    for trial in range(30):
        x0, vx = rng.uniform(-30, 0), rng.uniform(3, 15)
        y = rng.uniform(-3, 3)
        car = {f: ((x0 + vx * f / 10 - 2, y - 1), (x0 + vx * f / 10 + 2, y - 1), (x0 + vx * f / 10 + 2, y + 1),
                   (x0 + vx * f / 10 - 2, y + 1)) for f in range(rng.randint(0, 20), 80)}
        px, start = rng.uniform(-5, 5), rng.randint(0, 40)
        feet = {f: (px, -6 + 1.4 * (f - start) / 10) for f in range(start, start + 90)}
        want = brute_force_pet(feet, car, 10, 3.0)
        got = road.closest_pass(feet, car, 10, pet_max=3.0)
        assert (want is None and got is None) or (got and round(want[0] / 10, 6) == got["pet_s"]
                                                  and round(want[1], 2) == got["gap_m"]), (trial, want, got)


def test_full_footprint_counts_inside_as_zero_gap():
    square = ((0, 0), (4, 0), (4, 2), (0, 2))
    assert road.footprint_distance((2, 1), square) == 0.0 and road.footprint_distance((2, 3), square) == 1.0
    assert road.footprint_distance((2, 1), ((0, 0), (4, 0))) == 1.0  # a lone edge has no inside


def test_top_down_view_uses_box_centre_and_whole_box():
    H = road.homography(SQUARE_IMG, SQUARE_ROAD)  # 20 px per metre
    person = {0: [190, 190, 210, 230]}
    assert math.dist(road.person_points(person, H, top_down=True)[0], (5.0, 5.5)) < 1e-9  # centre (200, 210)
    assert math.dist(road.person_points(person, H)[0], (5.0, 6.5)) < 1e-9                  # feet (200, 230)
    car = {0: [120, 140, 200, 180]}
    assert len(road.vehicle_edges(car, H, top_down=True)[0]) == 4 and len(road.vehicle_edges(car, H)[0]) == 2


def filmed_at_an_angle(centres, heading=0.0, size=(4.6, 1.8)):
    """(SAM-like boxes, H) of a 1.5 m tall vehicle at `centres` ({frame: road point}) seen by a phone 10 m up and
    25 m back, calibrated on the road as calibrate.html would be (validate_sind's simulated camera)."""
    import validate_sind
    project = validate_sind.camera((0.0, 0.0), 10.0, 25.0)
    boxes = {f: validate_sind.box(project, road.rectangle(c, heading, size), 1.5) for f, c in centres.items()}
    return boxes, validate_sind.calibration(project, (0.0, 0.0))


def test_car_shaped_footprint_stands_under_the_box_at_an_angle():
    drive = {f: (-8.0 + 0.8 * f, 1.0) for f in range(20)}  # 8 m/s along x at 10 fps...
    centres = drive | {f: drive[19] for f in range(20, 40)}  # ...then 2 s standing still
    boxes, H = filmed_at_an_angle(centres)
    feet = road.vehicle_footprints(boxes, H, (4.6, 1.8), 10)
    assert feet.keys() == centres.keys() and all(len(s) == 4 for s in feet.values())  # heading carried while still
    assert all(math.dist(road.centroid(feet[f]), c) < 0.25 for f, c in centres.items() if f >= road.SMOOTH_FRAMES)
    assert all(abs(math.dist(s[0], s[1]) - 1.8) < 1e-9 and abs(math.dist(s[1], s[2]) - 4.6) < 1e-9
               for s in feet.values())
    edges = road.vehicle_edges(boxes, H)  # the lower box edge is the near side, about a metre off the middle
    assert all(math.dist(road.centroid(edges[f]), c) > 0.8 for f, c in centres.items())
    parked = {f: boxes[39] for f in range(30)}  # never moved: no heading, so lower edges throughout
    assert road.vehicle_footprints(parked, H, (4.6, 1.8), 10) == road.vehicle_edges(parked, H)


def test_footprint_centre_is_median_smoothed_over_two_frames():
    centres = {f: (-8.0 + 0.8 * f, 1.0) for f in range(20)}
    boxes, H = filmed_at_an_angle(centres)
    boxes[10] = [v + 12 for v in boxes[10]]  # one SAM box 12 px off
    alone = road.fit_centre(road.inverse(H), boxes[10], 0.0, (4.6, 1.8), centres[10])
    smoothed = road.centroid(road.vehicle_footprints(boxes, H, (4.6, 1.8), 10)[10])
    assert math.dist(alone, centres[10]) > 0.5 and math.dist(smoothed, centres[10]) < 0.25


def test_footprints_only_at_an_angle_and_top_down_shapes_unchanged():
    import analyze
    centres = {f: (-8.0 + 0.8 * f, 1.0) for f in range(20)}
    boxes, H = filmed_at_an_angle(centres)
    site = {"image_points": SQUARE_IMG, "world_points": SQUARE_ROAD, "zone_m": [-50, -50, 50, 50],
            "vehicles": ["car", "bus"], "vehicle_sizes_m": {"bus": [10.0, 2.5]}}
    tracks = {"car#1": boxes, "bus#2": boxes, "vehicle#3": boxes}
    _, angled = analyze.road_tracks(site, H, {}, tracks, None)
    car = road.VEHICLE_SIZES_M["car"]
    assert angled["car#1"] == road.vehicle_footprints(boxes, H, car, analyze.FPS, site["zone_m"])
    assert abs(math.dist(*angled["bus#2"][0][:2]) - 2.5) < 1e-9  # the site's tape-measured size
    assert angled["vehicle#3"] == road.vehicle_edges(boxes, H, site["zone_m"])  # no size: the lower box edge
    _, top = analyze.road_tracks({**site, "view": "top-down"}, H, {}, tracks, None)
    assert top == {vid: road.vehicle_edges(t, H, site["zone_m"], None, True) for vid, t in tracks.items()}
    event = {"person": "p/0", "vehicle": "car#1", "t_person_s": 1.0, "t_vehicle_s": 1.0}
    [where] = analyze.placed([event], {"p/0": {10: (0.0, 0.0)}}, angled)
    assert where["footprint"] == [[round(v, 1) for v in q] for q in angled["car#1"][10]]
    import roadmap
    assert roadmap.svg([{**where, "tier": "serious", "vehicle_kmh": 28.8, "pet_s": 0.0}],
                       SQUARE_ROAD).count('<polygon class="foot"') == 1


def test_sind_oblique_table_compares_vehicle_shapes_with_the_truth():
    import validate_sind
    person = {"7": {f: (-1.0 + 0.05 * f, 0.0) for f in range(40)}}  # walking along the road, a car passes 0.1 m away
    car = {"car#1": {f: road.rectangle((-16.0 + 0.8 * f, 1.0), 0.0, (4.6, 1.8)) for f in range(40)}}
    rows = validate_sind.oblique_rows(person, car, 10.0, 25.0)
    table = validate_sind.oblique_table(person, rows)
    assert len(rows) == 5 and table.count("\n") == 6
    assert "| SinD footprints (truth) | 1 | 1 | 0 | 0 | +0.00 s |" in table
    assert "| car-shaped footprint | 1 | 1 | 0 | 0 |" in table


def test_who_reached_the_spot_first_and_the_vehicle_speed_two_seconds_before():
    fps, car = 10, edges_along_x(8.0, 10, 60)  # within 1 m of x = 0 on frames 28-32, at 28.8 km/h throughout
    waited = road.closest_pass({f: (0.0, 0.0) for f in range(15)}, car, fps)  # left the spot 1.4 s before it came
    assert waited["first"] == "person" and waited["kmh_2s_before"] == waited["vehicle_kmh"] == 28.8
    assert road.closest_pass({f: (0.0, 0.0) for f in range(36, 60)}, car, fps)["first"] == "vehicle"
    bare = road.event_fields(((20, 0.5), 0, 20, 0.5, 25 / 3.6), fps)  # no speeds given: nothing from before
    assert bare["first"] == "person" and bare["kmh_2s_before"] is None
    e = {"person": "1/0", "vehicle": "car#1", "tier": "serious", "pet_s": 0.6, "t_person_s": 3.0, "t_vehicle_s": 3.6,
         "gap_m": 0.4, "vehicle_kmh": 31.0, "kmh_2s_before": 32.0, "death_risk_pct": 2.0,
         "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5}, "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    line = ("The person was on the spot first; the car reached it 0.6 s later at 31.0 km/h (32.0 km/h two seconds "
            "earlier: no slowdown measured).")
    assert road.first_note(e) == line and html.escape(line) in pack.event_card(1, e, fps)
    assert road.first_note({**e, "kmh_2s_before": 38.0}).endswith("(38.0 km/h two seconds earlier).")
    assert road.first_note({**e, "kmh_2s_before": None}).endswith("at 31.0 km/h.")
    car_first = {**e, "t_person_s": 4.2}
    assert road.first_note(car_first) == ("The car passed the spot first and the person reached it 0.6 s later: the "
                                          "impact and risk are for someone on the spot 0.6 s before the car came.")
    assert "same moment" in road.first_note({**e, "t_vehicle_s": 3.0})
    assert all("did not slow" not in pack.event_card(1, x, fps) for x in (e, car_first))
    measured = json.loads(pack.facts({}, [e, car_first, car_first], {"minutes": 1}))
    assert (measured["person_first"], measured["vehicle_first"], measured["both_at_once"]) == (1, 2, 0)


def test_events_inside_tracking_gaps_say_their_position_was_inferred():
    import analyze, crowd
    from pathlib import Path
    detected = {0: [0, 0, 10, 30], 2: [4, 0, 14, 30], 10: [20, 0, 30, 30]}  # seen every 0.2 s, then lost for 0.8 s
    assert [road.unseen_s(detected, f, 10) for f in (2, 1, 5)] == [0.0, 0.2, 0.8]
    real = crowd.track  # crowd mode keeps what SAM detected apart from the boxes it fills in between
    crowd.track = lambda clip, frames, fps, concept, key, cache, jump: {"c0": detected}
    try:
        site = {"person": "person", "vehicles": ["car"], "person_mode": "crowd"}
        tracks, seen = analyze.concept_tracks(site, "person", None, 20, [], Path("out"), None, None)
        video = analyze.concept_tracks(site, "car", None, 20, [], Path("out"), None, None)
    finally:
        crowd.track = real
    assert seen == {"c0": detected} and sorted(tracks["c0"]) == list(range(11)) and video == ({}, {})
    event = {"person": "c0/0", "vehicle": "car#1", "t_person_s": 0.5, "t_vehicle_s": 0.6}
    [e] = analyze.with_unseen([event], seen, {"car#1": {f: [0, 0, 9, 9] for f in range(20)}})
    assert e["unseen_s"] == {"person": 0.8, "vehicle": 0.0}
    assert road.seen_note(e) == "Not detected for about 0.8 s (the person); position inferred."
    assert road.seen_note({**e, "unseen_s": {"person": 0.2, "vehicle": 0.0}}) == "Seen at the moment."
    assert road.seen_note(event) == ""  # an events.json from before this was measured


def test_spark_crop_stays_inside_the_frame():
    assert review.crop_window([0, 0, 10, 20], (640, 360)) == (0, 0, 80)          # small box: minimum crop, clamped
    assert review.crop_window([600, 300, 640, 360], (640, 360)) == (460, 180, 180)  # 3 x 60 px, pushed inside
    assert review.crop_window([0, 0, 400, 400], (640, 360))[2] == 360              # never bigger than the frame


def test_review_three_fixes_hold():
    import tempfile
    from pathlib import Path
    fps, frames = 10, 40
    # one person split into two pieces, both meeting the same car: reported once
    pieces = {"7/0": walking_across(frames, until=19), "7/1": {f: p for f, p in walking_across(frames).items() if f >= 20}}
    events = road.conflicts(pieces, {"car#1": edges_along_x(8.0, fps, frames)}, fps)
    assert len(events) == 1
    # a pole whose base is hidden for a frame every 10 s is still dropped when judged before cutting
    pole = {f: ((6.0, 0.0) if f % 100 == 50 else (0.0, 0.0)) for f in range(600)}
    assert road.moving_frames(pole, fps) == {}
    assert len(road.split_at_jumps(pole, fps)) > 1  # cutting first would have hidden it in short pieces
    # close pass: a limit above the real speed changes nothing
    hit = road.event_fields(((20, 0.5), 0, 20, 0.5, 25 / 3.6), fps)
    assert hit["with_limit"]["30"]["impact_kmh"] == hit["impact_kmh"]
    # top-down: a box cut off at the top edge is skipped
    H = road.homography(SQUARE_IMG, SQUARE_ROAD)
    assert road.vehicle_edges({0: [150, 0, 250, 80], 1: [150, 20, 250, 80]}, H, frame_size=(400, 360), top_down=True).keys() == {1}
    # no person tracks: no street photo rather than unblurred faces
    with tempfile.TemporaryDirectory() as tmp:
        try:
            pack.street_photo(Path(tmp) / "clip.mp4", Path(tmp) / "street.jpg")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")


def test_street_photo_blurs_people_a_full_video_reply_missed():
    import subprocess, tempfile
    from pathlib import Path
    import crowd
    box = lambda obj, x: f"{obj}<|box;x1={x};y1=5;x2={x + 10};y2=40;w=64;h=48|>"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10:duration=1",
                        "-pix_fmt", "yuv420p", str(out / "clip.mp4")], check=True)
        # auto mode: the full video reply holds one person, the frame-by-frame reply it switched to holds three
        (out / "part0").mkdir()
        sam.cache_path(out / "part0", "person").write_text("<0f>" + box(0, 5))
        crowd.cache_dir(out, "person").mkdir()
        (crowd.cache_dir(out, "person") / "000000.sam.txt").write_text("<0f>" + "".join(box(i, x) for i, x in
                                                                                       enumerate((5, 25, 45))))
        old, blurred = render.blur_filters, []
        render.blur_filters = lambda *args: blurred.extend(old(*args)) or blurred
        try:
            pack.street_photo(out / "clip.mp4", out / "street.jpg")
        finally:
            render.blur_filters = old
        assert (out / "street.jpg").exists() and all(f"delogo=x={x}:" in "".join(blurred) for x in (5, 25, 45))


def test_street_photo_blurs_plates_and_never_trusts_a_full_video_reply_alone():
    import subprocess, tempfile
    from pathlib import Path
    import crowd
    box = lambda obj, x: f"{obj}<|box;x1={x};y1=5;x2={x + 3};y2=40;w=640;h=360|>"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10:duration=1",
                        "-pix_fmt", "yuv420p", str(out / "clip.mp4")], check=True)
        sam.cache_path(out, "person").write_text("<0f>" + "".join(box(i, 20 * i) for i in range(sam.MAX_OBJECTS)))
        sam.cache_path(out, "car").write_text("<0f>0<|box;x1=400;y1=200;x2=500;y2=280;w=640;h=360|>")
        assert raises_value_error(lambda: pack.street_photo(out / "clip.mp4", out / "street.jpg", "person", ["car"]))
        crowd.cache_dir(out, "person").mkdir()  # analyze searched frame 0 image by image
        (crowd.cache_dir(out, "person") / "000000.sam.txt").write_text("<0f>" + box(0, 600))
        calls, old = [], pack.subprocess.run
        pack.subprocess.run = lambda args, **kwargs: calls.append(args) or old(args, **kwargs)
        try:
            pack.street_photo(out / "clip.mp4", out / "street.jpg", "person", ["car"])
        finally:
            pack.subprocess.run = old
    filters = calls[-1][calls[-1].index("-vf") + 1]
    assert "delogo=x=400:y=260:w=100:h=20:" in filters and "delogo=x=600:" in filters  # the plate; a missed person


def test_number_plates_are_blurred_in_the_bottom_quarter_of_each_vehicle():
    car = {10: [100, 100, 200, 140], 11: [637, 350, 700, 400]}  # then off the frame's corner: nothing left to blur
    assert render.plate_filters([car], 10, 11, (640, 360)) == ["delogo=x=100:y=130:w=100:h=10:enable='eq(n,0)'"]
    calls, old = [], render.subprocess.run
    render.subprocess.run = lambda args, **kwargs: calls.append(args)
    try:
        render.render("clip.mp4", {"t_person_s": 1.0, "t_vehicle_s": 1.0}, {}, {}, 10, "event1.mp4",
                      frame_size=(640, 360), vehicles=[{5: [100, 100, 200, 140]}])
    finally:
        render.subprocess.run = old
    assert "delogo=x=100:y=130:w=100:h=10:enable='eq(n,5)'" in calls[0][calls[0].index("-vf") + 1]


def test_heads_a_full_video_request_missed_are_searched_on_every_published_frame():
    import contextlib, io, tempfile
    from pathlib import Path
    import analyze, crowd
    site = {"person": "person", "vehicles": ["car"]}
    events = [{"t_person_s": 3.0, "t_vehicle_s": 3.5, "review": {"is_person": False}},  # rejected: no clip
              {"t_person_s": 3.0, "t_vehicle_s": 3.5}]
    shown = analyze.shown_frames(events, 100)
    assert shown == {0, *range(10, 56)}  # the one clip, 1-5.5 s, and frame 0 (the street photo)
    asked, real = [], crowd.track
    crowd.track = lambda clip, frames, fps, concept, key, cache: asked.extend(frames) or {"c0": {0: [0, 0, 9, 30]}}
    try:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            pieces = [(0, None, Path(tmp))]
            try:
                analyze.search_heads(site, None, Path(tmp), events, 100, pieces, None, 0.05)
                raise AssertionError("over the budget accepted")
            except SystemExit as err:
                assert "$0.06 is over the $0.05" in str(err)  # 25 images at $0.0025
            found, searched = analyze.search_heads(site, None, Path(tmp), events, 100, pieces, None, 1.0)
    finally:
        crowd.track = real
    assert asked == searched == [0, *range(10, 57, 2)]  # 25 frames: 10 fps clip, 5 fps samples, one past each end
    tracked = {"a": {0: [0, 0, 10, 30]}, "far": {90: [0, 0, 10, 30]}}  # "far" is on no searched frame
    missed = {"c1": {12: [50, 0, 60, 30]}, "c2": {0: [100, 0, 110, 30]}, "c3": {0: [200, 0, 210, 30]}}
    everyone, counts = analyze.heads(tracked, found | missed, searched)  # c0 sits on a; frame 0 has 2 it missed
    assert counts == {"heads_tracked": 1, "heads_found": 2} and len(everyone) == 6
    note = pack.privacy_note(counts)
    assert "up to 1 heads a frame blurred from tracks + up to 2 found by SAM image search" in note
    assert pack.privacy_note(None) == ""


def test_found_heads_cover_the_last_published_frame_and_frames_next_to_a_lone_sample():
    import contextlib, io, tempfile
    from pathlib import Path
    import analyze, crowd
    site = {"person": "person", "vehicles": ["car"]}
    events = [{"t_person_s": 13.0, "t_vehicle_s": 13.5}]  # its clip runs to the end of a 150-frame clip
    shown = analyze.shown_frames(events, 150)
    assert max(shown) == 149  # an odd frame: samples are 0, 2, ..., 148
    real = crowd.track  # the search sees one person on every sample, a new short track each time (it flickers)
    crowd.track = lambda clip, frames, fps, concept, key, cache: {f"c{f}": {f: [0, 0, 9, 30]} for f in frames}
    try:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            found, searched = analyze.search_heads(site, None, Path(tmp), events, 150, [(0, None, Path(tmp))], None, 1.0)
    finally:
        crowd.track = real
    boxed = {f for t in found.values() for f in t}
    assert shown <= boxed and max(boxed) == 149  # every published frame has a box, none past the clip
    assert analyze.heads({}, found, searched)[1] == {"heads_tracked": 0, "heads_found": 1}  # counts on samples only


def test_a_clip_without_near_misses_still_gets_frame_0_searched_for_its_street_photo():
    """With 0 events, a full people reply still gets its search: one image, frame 0, the street photo's frame."""
    import contextlib, io, tempfile
    from pathlib import Path
    import analyze, crowd
    site = {"person": "person", "vehicles": ["car"]}
    real = crowd.track
    crowd.track = lambda clip, frames, fps, concept, key, cache: {"c0": {f: [0, 0, 9, 30] for f in frames}}
    try:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            found, searched = analyze.search_heads(site, None, Path(tmp), [], 100, [(0, None, Path(tmp))], None, 0.01)
    finally:
        crowd.track = real
    assert searched == [0] and 0 in found["c0"]  # $0.0025, inside a $0.01 budget
    source = Path(analyze.__file__).read_text()
    assert "if events and person_concept" not in source  # main no longer skips the search when nothing happened


def test_crowd_tracker_keeps_ids_through_a_short_gap_and_apart_from_neighbours():
    import crowd
    walker = lambda x0: {f: [x0 + 2 * f, 100, x0 + 2 * f + 20, 160] for f in range(0, 40, 2)}
    a, b = walker(0), walker(200)
    detections = {f: [box for box in (a.get(f), b.get(f)) if box] for f in range(0, 40, 2)}
    detections[20] = [b[20]]  # a is hidden for one sample
    tracks = crowd.associate(detections, 10)
    assert len(tracks) == 2 and sorted(len(t) for t in tracks.values()) == [19, 20]
    far = crowd.associate({0: [[0, 0, 10, 40]], 2: [[200, 0, 210, 40]]}, 10)
    assert len(far) == 2  # too far to be the same person
    assert abs(crowd.iou([0, 0, 10, 10], [5, 0, 15, 10]) - 1 / 3) < 1e-9
    # every frame between samples gets a box, so evidence clips blur heads on all frames
    assert crowd.filled({0: [0, 0, 10, 10], 2: [2, 0, 12, 10], 6: [6, 0, 16, 10]}) == {
        0: [0, 0, 10, 10], 1: [1.0, 0.0, 11.0, 10.0], 2: [2, 0, 12, 10], 3: [3.0, 0.0, 13.0, 10.0],
        4: [4.0, 0.0, 14.0, 10.0], 5: [5.0, 0.0, 15.0, 10.0], 6: [6, 0, 16, 10]}


def test_event_cards_do_not_give_a_child_or_non_car_a_car_curve_risk_unqualified():
    e = {"person": "p/0", "vehicle": "motorcycle#3", "tier": "serious", "pet_s": 0.5, "vehicle_kmh": 30.0,
         "impact_kmh": 30.0, "death_risk_pct": 1.5, "t_person_s": 2.0, "t_vehicle_s": 2.5, "gap_m": 0.5,
         "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5}, "20": {"impact_kmh": 20.0, "death_risk_pct": 0.6}},
         "review": {"is_person": True, "road_user": "child", "reason": ""}}
    card = pack.event_card(1, e, 10)
    assert "not a child&#x27;s risk" in card and "car fronts" in card
    assert "never state a death risk for a child" in pack.LETTER_PROMPT
    assert "for an auto rickshaw" in pack.risk_caveat("pedestrian", "auto rickshaw")



def test_letters_quoting_unmeasured_numbers_go_back_to_spark():
    facts = '{"pet_s": 0.4, "vehicle_kmh": 27.3, "at_20_kmh_limit": {"death_risk_pct": 0.6}}'
    assert pack.unmeasured("PET 0.4 s at 27.3 km/h; a 20 km/h limit; 3 times this week", facts) == ["3"]
    good = {"fix": "speed table", "why": "cars at 27.3 km/h", "image_prompt": "add a speed table", "letter": "PET 0.4 s."}
    replies, prompts = [{**good, "letter": "It happened 12 times."}, good], []
    old = pack.model_plan, pack.judge_problems
    pack.model_plan = lambda prompt, key, photo=None, known=None: (prompts.append(prompt), replies.pop(0))[1]
    pack.judge_problems = lambda letter, measured, key: []
    try:
        assert pack.ask_plan("PROMPT", facts, "key") == {**good, "writer": pack.WRITER, "tries": 2,
                                                         "judged_by": pack.JUDGE}  # the receipt's letter tries
        assert "12" in prompts[1] and "not in the measurements" in prompts[1]
        replies[:] = [{**good, "letter": "It happened 12 times."}] * pack.LETTER_TRIES
        stubborn = pack.ask_plan("PROMPT", facts, "key")
    finally:
        pack.model_plan, pack.judge_problems = old
    assert stubborn["unmeasured"] == ["12"] and "12" in pack.letter_section(stubborn)
    assert stubborn["tries"] == pack.LETTER_TRIES


def test_a_second_model_judges_the_letter_and_its_objections_go_back():
    """The workshop's second layer: after the code check, Muse Spark as a separate reviewer (LLM as judge)."""
    good = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "Cars passed close to children."}
    bad = {**good, "letter": "This crossing meets the IRC warrant."}
    replies, prompts, judged = [bad, good], [], []
    def judge(letter, measured, key):
        judged.append(letter)
        return ["Says a warrant is met."] if "warrant" in letter else []
    old = pack.model_plan, pack.judge_problems
    pack.model_plan = lambda prompt, key, photo=None, known=None: (prompts.append(prompt), replies.pop(0))[1]
    pack.judge_problems = judge
    try:
        plan = pack.ask_plan("PROMPT", "{}", "key")
        assert plan["letter"] == good["letter"] and "Says a warrant is met." in prompts[1] and len(judged) == 2
        replies[:] = [bad] * pack.LETTER_TRIES
        stubborn = pack.ask_plan("PROMPT", "{}", "key")
        assert stubborn["unsupported"] == ["Says a warrant is met."] and "warrant is met" in pack.letter_section(stubborn)
        replies[:] = [good]
        assert "judged_by" not in pack.ask_plan("PROMPT", "{}", None)  # no key: no judge, and the page says so
    finally:
        pack.model_plan, pack.judge_problems = old
    assert pack.read_problems('{"problems": ["a", 3, ""]}') == ["a"] and pack.read_problems("nonsense") is None


def test_number_check_flags_words_and_mph_and_reads_the_measurements_only():
    facts = '{"worst": [{"vehicle_kmh": 38.0, "pet_s": 0.2}]}'
    assert pack.unmeasured("The four worst; thirty-eight km/h; 38 mph; dozens of times", facts) == [
        "four", "thirty-eight", "dozens", "38 mph"]
    assert pack.unmeasured("One car and two-wheelers, three wheelers, at 38.0 km/h, 0.2 s, by the Triumph", facts) == []
    letter = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "SAM 3.1 measured 38.0 km/h."}
    old = pack.model_plan
    pack.model_plan = lambda prompt, key, photo=None, known=None: letter
    try:
        assert pack.ask_plan("PROMPT naming SAM 3.1", facts, None)["unmeasured"] == ["3.1"]  # the prompt is no source
    finally:
        pack.model_plan = old
    assert "3.1" not in pack.LETTER_PROMPT and "every number in digits" in pack.LETTER_PROMPT
    assert "in words, not in\ndigits" in pack.JUDGE_PROMPT


def test_a_sentence_never_puts_one_near_miss_speed_beside_another_ones_gap():
    worst = [{"vehicle_kmh": 38.0, "pet_s": 0.2}, {"vehicle_kmh": 20.0, "pet_s": 0.9}, {"vehicle_kmh": 11.2, "pet_s": 0.9}]
    crossed = "A car at 38.0 km/h passed 0.9 s from a child."
    assert pack.mixed(crossed + " Later one at 20.0 km/h came 0.9 s after a man.", worst) == [crossed]
    assert pack.mixed("Cars at 38.0 km/h (0.2 s apart), 20.0 km/h (0.9 s) and 11.2 km/h (0.9 seconds).", worst) == []
    assert pack.mixed("The worst were 0.2 s to 0.9 s apart, with cars at 20.0 km/h to 38.0 km/h.", worst) == []
    assert pack.mixed("In 6.9 s of video the 85th percentile was 18.3 km/h.", worst) == []  # no event's numbers
    good = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "A car at 38.0 km/h, 0.2 s from a child."}
    replies, prompts = [{**good, "letter": crossed}, good], []
    old = pack.model_plan, pack.judge_problems
    pack.model_plan = lambda prompt, key, photo=None, known=None: (prompts.append(prompt), replies.pop(0))[1]
    pack.judge_problems = lambda letter, measured, key: []
    try:
        facts = json.dumps({"worst": worst})
        assert pack.ask_plan("PROMPT", facts, "key")["letter"] == good["letter"]
        assert crossed in prompts[1] and "Keep each near-miss's numbers together" in prompts[1]
        replies[:] = [{**good, "letter": crossed}] * pack.LETTER_TRIES
        stubborn = pack.ask_plan("PROMPT", facts, "key")
    finally:
        pack.model_plan, pack.judge_problems = old
    section = pack.letter_section(stubborn)
    assert stubborn["mixed"] == [crossed] and "mixes two near-misses" in section and "Every number was" not in section


def test_letter_numbers_link_to_the_one_clip_they_measure_and_edits_are_rechecked():
    """Click 38 km/h in the letter and that car's clip plays; printed, it says "(see clip 1)"."""
    shown = [{"vehicle_kmh": 38.0, "pet_s": 0.2, "death_risk_pct": 4.1}, {"vehicle_kmh": 20.0, "pet_s": 0.5,
             "death_risk_pct": 0.6}, {"vehicle_kmh": 20.0, "pet_s": 1.1, "death_risk_pct": 0.6}]
    text = pack.linked("At 38.0 km/h, 0.5 seconds apart; two at 20.0 km/h (0.6%); the driver's 27 s; 12 schools <b>", shown)
    assert '<a class="clip" href="#event-1" data-clip="1" title="Play clip 1">38.0 km/h</a>' in text
    assert '<a class="clip" href="#event-2" data-clip="2" title="Play clip 2">0.5 seconds</a>' in text
    assert text.count("<a ") == 2 and "driver&#x27;s 27 s" in text and "&lt;b&gt;" in text  # 20.0 and 0.6%: two cards
    assert 'a.clip::after { content: " (see clip " attr(data-clip) ")"; }' in pack.STYLE
    e = {"person": "1/0", "vehicle": "car#1", "tier": "serious", "pet_s": 0.2, "vehicle_kmh": 38.0, "death_risk_pct": 4.1,
         "t_person_s": 3.0, "t_vehicle_s": 3.2, "gap_m": 0.4, "clip": "event1.mp4",
         "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5}, "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    plan = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "A car at 38.0 km/h.", "writer": "Muse Spark"}
    page = pack.page({"name": "gate", "world_points": SQUARE_ROAD}, [e], {"minutes": 1}, plan, None, 10)
    assert 'id="event-1"' in page and 'contenteditable="plaintext-only"' in page
    assert 'href="#event-1"' in page.split('id="letter"')[1]  # the letter's own link, not the first screen's
    measured = page.split('data-measured="')[1].split('"')[0].split()
    assert "38.0" in measured and "0.2" in measured and "3.1" not in measured  # the browser checks the same facts
    assert "Edited here: numbers re-checked in your browser." in page and "::highlight(unmeasured)" in page
    assert '<p class="note ok" id="letter-check">Every number was checked' in page


def pack_folder(folder):
    """An analyze.py output folder with one near-miss and its site file, for pack.main()."""
    from pathlib import Path
    e = {"person": "1/0", "vehicle": "car#1", "tier": "serious", "pet_s": 0.5, "vehicle_kmh": 30.0, "death_risk_pct": 1.5,
         "t_person_s": 3.0, "t_vehicle_s": 3.5, "gap_m": 0.4, "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5},
                                                                         "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    out = Path(folder)
    (out / "events.json").write_text(json.dumps({"fps": 10, "exposure": {"minutes": 0.3}, "events": [e]}))
    (out / "site.json").write_text(json.dumps({"name": "gate", "image_points": SQUARE_IMG, "world_points": SQUARE_ROAD}))
    return out


def run_pack(out, *flags, ask=None, key=None, draw=None):
    """pack.main() on `out` with no network: `ask(prompt)` stands in for the letter model, `draw` for Muse Image (and
    with it a street photo). Returns each (prompt, stated notes) the letter step was asked with."""
    import contextlib, io, sys
    calls, old = [], (sys.argv, pack.optional_key, pack.street_photo, pack.ask_plan, pack.draw_fix, pack.photo_people)
    sys.argv = ["pack.py", str(out), str(out / "site.json"), *flags]
    pack.optional_key = lambda: key
    pack.street_photo = (lambda clip, path, *args: (path.write_bytes(b"jpeg"), path)[1]) if draw else lambda *args: None
    pack.ask_plan = lambda prompt, measured, key, photo, stated=(): (calls.append((prompt, stated)), ask(prompt))[1]
    pack.draw_fix, pack.photo_people = draw or pack.draw_fix, lambda *args: []
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            pack.main()
    finally:
        sys.argv, pack.optional_key, pack.street_photo, pack.ask_plan, pack.draw_fix, pack.photo_people = old
    return calls


def exits(call):
    try:
        call()
    except SystemExit:
        return True
    return False


def test_pack_saves_the_letter_plan_and_a_rerun_pays_nothing():
    """plan.json keeps the letter with its prompt's sha256: a re-run from the same measurements asks no model and
    draws no new picture of the same fix; new measurements ask again."""
    import tempfile
    plan = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "PET 0.5 s, स्कूल.", "writer": pack.WRITER}
    drawn = []
    draw = lambda photo, words, key, path: (drawn.append(words), path.write_bytes(b"RIFF"), path)[2]
    with tempfile.TemporaryDirectory() as folder:
        out = pack_folder(folder)
        assert len(run_pack(out, ask=lambda prompt: plan, key="key", draw=draw)) == 1 and len(drawn) == 1
        saved = json.loads((out / "plan.json").read_text())
        assert saved == {**plan, "prompt_sha256": saved["prompt_sha256"]} and len(saved["prompt_sha256"]) == 64
        page = (out / "index.html").read_text()
        assert "speed table" in page and 'src="street-fixed.webp"' in page
        assert (out / "share" / "index.html").read_text() == page
        assert run_pack(out, ask=None, key="key", draw=draw) == [] and len(drawn) == 1  # nothing paid
        assert run_pack(out, ask=None, draw=draw) == [] and (out / "index.html").read_text() == page  # no key either
        data = json.loads((out / "events.json").read_text())
        data["events"][0]["vehicle_kmh"] = 31.0
        (out / "events.json").write_text(json.dumps(data))
        assert len(run_pack(out, ask=lambda prompt: plan)) == 1  # other measurements: a new letter


def test_principal_notes_revise_the_letter_and_reach_the_checks_as_stated_not_measured():
    """Reject with notes (Meta's legal-agent workshop): the notes go back with the letter, "change only the sentences
    the notes ask for", and a number the principal stated passes the code check and reaches the judge labelled."""
    import tempfile
    letter = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "PET 0.4 s. Our 1,200 pupils cross."}
    judged, old = [], (pack.model_plan, pack.judge_problems)
    pack.model_plan = lambda prompt, key, photo=None, known=None: letter
    pack.judge_problems = lambda text, measured, key: (judged.append(measured), [])[1]
    try:
        assert pack.ask_plan("PROMPT", '{"pet_s": 0.4}', "key")["unmeasured"] == ["1,200"] and judged == []
        assert "unmeasured" not in pack.ask_plan("PROMPT", '{"pet_s": 0.4}', "key", stated=["We have 1,200 pupils."])
    finally:
        pack.model_plan, pack.judge_problems = old
    assert judged == ['{"pet_s": 0.4}\n\nSTATED BY THE PRINCIPAL, NOT MEASURED (a letter may give these as the school\'s own '
                      "statements):\nWe have 1,200 pupils."]
    draft = {"fix": "speed table", "why": "w", "image_prompt": "i", "writer": pack.WRITER,
             "letter": "Dear Sir. A car passed 0.5 s from a child. We ask for a speed table."}
    revised = {**draft, "letter": "Dear Sir. A car passed 0.5 s from one of our 1,200 pupils. We ask for a speed table."}
    with tempfile.TemporaryDirectory() as folder:
        out = pack_folder(folder)
        (out / "notes.txt").write_text("Say we have 1,200 pupils.\n")
        assert exits(lambda: run_pack(out, "--notes", str(out / "notes.txt"), ask=lambda p: revised))  # no letter yet
        run_pack(out, ask=lambda prompt: draft)
        [(prompt, stated)] = run_pack(out, "--notes", str(out / "notes.txt"), ask=lambda p: revised)
        assert "change only the sentences the notes ask for" in prompt and draft["letter"] in prompt
        assert prompt.endswith("NOTES:\nSay we have 1,200 pupils.") and stated == ["Say we have 1,200 pupils."]
        saved = json.loads((out / "plan.json").read_text())
        assert saved["letter"] == revised["letter"] and saved["draft_letter"] == draft["letter"] and saved["notes"] == stated
        page = (out / "index.html").read_text()
        assert "from the measurements in this pack and the principal's notes." in page
        assert "1200" in page.split('data-measured="')[1].split('"')[0].split()  # the browser check agrees
        (out / "notes.txt").write_text("Shorter, please.")
        [(prompt, stated)] = run_pack(out, "--notes", str(out / "notes.txt"), ask=lambda p: {**revised, "letter": "Short."})
        assert revised["letter"] in prompt and stated == ["Say we have 1,200 pupils.", "Shorter, please."]
        assert json.loads((out / "plan.json").read_text())["draft_letter"] == draft["letter"]  # the first AI draft


def test_signoff_names_the_signer_only_while_the_letter_is_unchanged():
    import datetime, hashlib, tempfile
    draft = {"fix": "speed table", "why": "w", "image_prompt": "i", "writer": pack.WRITER,
             "letter": "Dear Sir. A car passed 0.5 s from a child. We ask for a speed table."}
    revised = {**draft, "letter": "Dear Sir. A car passed 0.5 s from a pupil. We ask for a speed table."}
    sign = ["--approved-by", "A. Rao, Principal", "--school", "Gate School"]
    with tempfile.TemporaryDirectory() as folder:
        out = pack_folder(folder)
        (out / "notes.txt").write_text("Say pupil, not child.")
        for flags in (sign[:2], sign + ["--notes", str(out / "notes.txt")], sign):  # half a signer; unread; no letter
            assert exits(lambda: run_pack(out, *flags, ask=lambda p: draft))
        run_pack(out, ask=lambda p: draft)
        run_pack(out, "--notes", str(out / "notes.txt"), ask=lambda p: revised)
        assert run_pack(out, *sign) == []  # signing asks no model
        record = json.loads((out / "signoff.json").read_text())
        today = datetime.date.today().isoformat()
        assert record == {"approved_by": "A. Rao, Principal", "school": "Gate School", "date": today,
                          "letter_sha256": hashlib.sha256(revised["letter"].encode()).hexdigest()}
        assert (f"Read and approved by: A. Rao, Principal, Gate School, {today} (1 of 3 sentences changed after the "
                "principal&#x27;s notes).") in (out / "index.html").read_text()
        saved = json.loads((out / "plan.json").read_text())
        (out / "plan.json").write_text(json.dumps({**saved, "letter": saved["letter"] + " One more."}))
        run_pack(out)
        page = (out / "index.html").read_text()
        assert f"Changed after sign-off by A. Rao, Principal on {today}, not signed." in page
        assert "Read and approved by: ____ (name, role, date)." in page and "signoff.json" not in str(list(
            (out / "share").iterdir()))
    assert pack.edits({"letter": "A. B. C.", "draft_letter": "A. B. C. D."}) == (
        "1 of 4 sentences changed after the principal's notes")  # a cut sentence counts
    assert pack.edits({"letter": "A. B."}) == "as drafted, no notes"


def test_filed_reference_under_the_title_tct_steps_and_a_print_view():
    """Filing says only "filed, reference X"; the page places itself in the TCT toolkit; paper is light, holds the 3
    worst cards, and gives the letter its own sheet."""
    import tempfile
    sent = {"to": "City Traffic Police", "channel": "CPGRAMS", "date": "2026-11-03", "reference": "REF/2026/1"}
    page = pack.page({"name": "gate", "world_points": SQUARE_ROAD, "submitted": sent}, [], {"minutes": 1}, None, None, 10)
    line = '<p class="filed">Filed with City Traffic Police on CPGRAMS, 2026-11-03: reference REF/2026/1.</p>'
    assert page.index("</h1>") < page.index(line) < page.index('<div class="stats">') and pack.filed_line({}) == ""
    assert raises_value_error(lambda: pack.filed_line({"submitted": {**sent, "reference": " "}}))
    with tempfile.TemporaryDirectory() as folder:
        out = pack_folder(folder)
        (out / "site.json").write_text(json.dumps({"name": "gate", "world_points": SQUARE_ROAD, "submitted": {"to": "x"}}))
        assert exits(lambda: run_pack(out, ask=lambda p: None))  # refused before any model is asked
    assert "covers steps 5-7 (baseline counts, pre-intervention conflicts, analysis)" in page
    assert "without the trained observers step 3 normally needs" in page and "observer severity scales" in page
    assert "@media screen and (prefers-color-scheme: dark)" in pack.STYLE and "@media (prefers" not in pack.STYLE
    assert "article.card:nth-of-type(n+4) { display: none; }" in pack.STYLE
    assert 'a.clip[data-clip="4"]::after, a.clip[data-clip="5"]::after { content: " (clip " attr(data-clip) ", not ' \
           'printed)"; }' in pack.STYLE
    assert ".letter-sheet { break-before: page; break-after: page; }" in pack.STYLE
    assert ("@media print { h2, h3 { break-after: avoid; } figure, table, blockquote, .pair { break-inside: avoid; }\n"
            "               .letter-sheet:first-child { break-before: auto; } }" in pack.STYLE
            and "document.body.prepend(sheet)" in pack.letter_section({"letter": "x"}))  # on paper the letter is page 1
    assert pack.letter_section({"letter": "x"}).startswith('<section class="letter-sheet" id="letter">')

def test_docs_folder_lets_in_only_blurred_evidence_clips():
    """docs/ is published (GitHub Pages): *.mp4 stays ignored there except eventN.mp4 and eventN-hero.mp4, and the
    unblurred person crops and the blind set never get in. Nor do iPhone originals in either case (a clone on a
    case-sensitive disk), sound, the test clip's frames, notes, raters' answers or a replaced letter."""
    import shutil, subprocess, tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copyfile(Path(__file__).with_name(".gitignore"), Path(tmp) / ".gitignore")
        subprocess.run(["git", "init", "-q", tmp], check=True)
        ignored = lambda name: subprocess.run(["git", "-C", tmp, "-c", "core.ignorecase=false", "check-ignore", "-q",
                                               name]).returncode == 0
        for name in ("docs/event1.mp4", "docs/gate/event12-hero.mp4", "docs/gate/index.html", "docs/gate/street.jpg",
                     "<removed-run-record>", "provenance/spark-open-fireworks-sample.json",
                     "docs/gate/event1-strobe.jpg"):
            assert not ignored(name), name
        for name in ("docs/clip.mp4", "docs/gate/clip.mp4", "docs/gate/part0/clip.mp4", "docs/gate/person-c1-0.jpg",
                     "docs/gate/blind/clip01.mp4", "docs/gate/blind/index.html", "docs/gate/blind-key.json",
                     "out/gate/event1.mp4", ".env", "CLIP.MOV", "TEST.MOV", "first.png", "last.png", "frame.jpg",
                     "notes.txt", "answers-a.json", "docs/gate/event1.wav", "docs/gate/raw.mov", ".env.local",
                     "sample/plan-1a2b3c4d.json", "docs/gate/person-c1.json", "IMG_0001.HEIC", "frame0.jpg",
                     "IMG_0002.JPG", "docs/gate/frame.jpg", "docs/gate/first.png"):
            assert ignored(name), name


def test_share_folder_holds_only_what_the_page_shows_and_never_the_unblurred_files():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder)
        for name in ("clip.mp4", "person-3-0.jpg", "event1.mp4", "event2.mp4", "street.jpg", "street-fixed.webp",
                     "events.json", "plan.json"):
            (out / name).write_bytes(name.encode() + b"\x00RIFF")
        (out / "share").mkdir()
        (out / "share" / "stale.mp4").write_bytes(b"from an earlier run")
        page = ('<video src="event1.mp4#t=2.00"></video><img src="street.jpg"><img src="street-fixed.webp">'
                '<video src="clip.mp4"></video><img src="person-3-0.jpg"><img src="../events.json"><img src="gone.jpg">')
        shared = pack.share(out, page)
        assert sorted(p.name for p in shared.iterdir()) == ["event1.mp4", "index.html", "street-fixed.webp", "street.jpg"]
        assert (shared / "street-fixed.webp").read_bytes() == (out / "street-fixed.webp").read_bytes()  # AI tag kept


def test_shared_folder_gets_sha256sums_and_verify_names_each_changed_file():
    """SHA256SUMS in shasum's own format covers the shared page; --verify says MATCH, CHANGED or MISSING per file and
    exits 1 unless all match. The page gives the original video's SHA-256 and the analysis receipt; the BSA
    certificate pointer only for a site in India."""
    import contextlib, hashlib, io, shutil, subprocess, sys, tempfile
    import seal
    def verify(*args):
        printed, old = io.StringIO(), sys.argv
        sys.argv = ["pack.py", *args]
        try:
            with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(io.StringIO()):
                pack.main()
        except SystemExit as stop:
            return stop.code, printed.getvalue()
        finally:
            sys.argv = old
    with tempfile.TemporaryDirectory() as folder:
        out = pack_folder(folder)
        data = json.loads((out / "events.json").read_text())
        run = {"minutes": 12.3, "sam_requests": 0}
        (out / "events.json").write_text(json.dumps({**data, "source_sha256": "ab" * 32, "run": run}))
        run_pack(out)
        shared = out / "share"
        page = (shared / "index.html").read_bytes()
        assert (shared / "SHA256SUMS").read_text() == f"{hashlib.sha256(page).hexdigest()}  index.html\n"
        if shutil.which("shasum"):
            subprocess.run(["shasum", "-a", "256", "-c", "SHA256SUMS"], cwd=shared, check=True, capture_output=True)
        assert verify("--verify", str(shared)) == (0, "MATCH   index.html\n")
        text = page.decode()
        assert f"The original video's SHA-256 is <code>{'ab' * 32}</code>." in text and "Bharatiya" not in text
        assert "every SAM reply from cache, so it paid nothing new" in text
        (shared / "street.jpg").write_bytes(b"jpeg")
        seal.write_sums(shared)
        (shared / "index.html").write_bytes(page.replace(b"gate", b"gat3"))
        (shared / "street.jpg").unlink()
        assert verify("--verify", str(shared)) == (1, "CHANGED index.html\nMISSING street.jpg\n")
        assert verify("--verify", str(shared), str(out))[0] == 2  # --verify goes alone: argparse refuses
        (shared / "SHA256SUMS").write_text(f"{'0' * 64}  ../events.json\n")
        assert raises_value_error(lambda: seal.verify(shared))  # only files in the folder itself
    law = pack.hash_line(None, {"country": "IN"})
    assert "Schedule to the Bharatiya Sakshya Adhiniyam, 2023 (section 63(4))" in law and "original video" not in law


def test_receipt_counts_what_made_the_pack_and_says_when_sam_came_from_cache():
    import analyze, tempfile, time
    from pathlib import Path
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder)
        for sub in ("part0", "crowd-person"):
            (out / sub).mkdir()
        (out / "part0" / "car.sam.txt").write_text("")
        before = analyze.sam_replies(out)
        (out / "part0" / "person.sam.txt").write_text("")  # a video part's reply and a crowd-mode image's
        (out / "crowd-person" / "000000.sam.txt").write_text("")
        record = analyze.run_record(out, time.monotonic() - 90, before)
    assert before == 1 and record == {"minutes": 1.5, "sam_requests": 2}
    events = [{"person": "1/0", "review": {"is_person": True}, "heard": []}, {"person": "1/0", "review": {"is_person": True}},
              {"person": "2/0", "review": {"is_person": False}, "heard": None}, {"person": "3/0", "review": None}]
    line = pack.receipt_line({"run": record, "events": events}, {"writer": "Muse Spark", "tries": 2}, ("a.jpg", "b.webp"))
    assert line == ("Receipt: the analysis ran 1.5 minutes and sent 2 new SAM requests; Muse Spark looked at 2 people; "
                    "Muse Wonder listened around 1 near-miss; Muse Spark wrote the letter in 2 tries; Muse Image drew 1 "
                    "picture. Dollar costs on this page are for SAM only.")  # rejected people were looked at too
    cached = pack.receipt_line({"run": {"minutes": 0.4, "sam_requests": 0}, "events": []}, None, None)
    assert cached == ("Receipt: the analysis ran 0.4 minutes and took every SAM reply from cache, so it paid nothing "
                      "new. Dollar costs on this page are for SAM only.")
    assert pack.receipt_line({"events": []}, None, None) == ""  # an older events.json and no letter


def test_safety_pyramid_shows_the_headline_people_and_never_reads_as_safe():
    """Not to scale, base to tip: who crossed, within 3 s, within 1.5 s (each person once, as in the headline), and
    collisions, not measured: even 0 of n leaves Clopper-Pearson's upper bound."""
    import re
    hit = lambda person, pet: {"person": person, "vehicle": "car#1", "pet_s": pet,
                               "tier": "serious" if pet < road.PET_MAX_S else "close pass"}
    events = [hit("c1/0", 0.4), hit("c1/1", 2.0), hit("c2/0", 2.5), hit("pole/0", 0.1)]
    seen = {"minutes": 1.0, "crossings": 9, "crossers": [f"c{i}" for i in range(1, 10)]}
    drawn = pack.pyramid(events, seen)
    tip, *labels = re.findall(r"<span>(.*?)</span>", drawn)
    assert labels == ["1 of 9 had a moving vehicle through their spot within 1.5 s", "2 of 9 within 3 s",
                      "9 people crossed"]
    assert tip.startswith("Collisions: not measured.") and f"up to {100 * (1 - 0.025 ** (1 / 9)):.1f}% of crossings" in tip
    assert re.findall(r"width: (\d+)%", drawn) == ["20", "45", "70", "100"] and "Not to scale." in drawn
    assert pack.pyramid(events, {"minutes": 1.0, "crossings": 9}) == ""  # an older events.json: no crosser list
    quiet = pack.pyramid([], seen)
    assert "0 of 9 within 3 s" in quiet and quiet in pack.page({"name": "gate", "world_points": SQUARE_ROAD}, [], seen,
                                                                 None, None, 10)


def test_muse_image_webp_is_kept_untouched_and_shown_as_an_ai_proposal():
    """Converting Muse Image's WebP drops Meta's AI tag, so the page shows the file exactly as it came."""
    import base64, io, tempfile
    from pathlib import Path
    webp = b"RIFF\x00\x00\x00\x00WEBP<x:xmpmeta>trainedAlgorithmicMedia</x:xmpmeta>"
    reply = json.dumps({"data": [{"b64_json": base64.b64encode(webp).decode()}]}).encode()
    old = pack.urllib.request.urlopen, pack.subprocess.run
    pack.urllib.request.urlopen = lambda req, timeout: io.BytesIO(reply)
    pack.subprocess.run = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no re-encode"))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            photo = Path(tmp) / "street.jpg"
            photo.write_bytes(b"\xff\xd8jpeg")
            drawn = pack.draw_fix(photo, "add a zebra crossing", "key", Path(tmp) / "street-fixed.webp")
            assert drawn.name == "street-fixed.webp" and drawn.read_bytes() == webp
    finally:
        pack.urllib.request.urlopen, pack.subprocess.run = old
    shown = pack.fix_section({"fix": "zebra", "why": "w"}, ("street.jpg", "street-fixed.webp"))
    assert "AI-drawn proposal by Muse Image, not a photo" in shown and "AI-generated by Muse Image" in shown


def test_ai_label_is_burned_into_images_made_from_muse_image():
    import ailabel, subprocess, tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        source, labelled = Path(tmp) / "fixed.png", Path(tmp) / "labelled.png"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:size=640x360", "-frames:v", "1",
                        str(source)], check=True)
        ailabel.burn(source, labelled)
        grey = subprocess.run(["ffmpeg", "-v", "error", "-i", str(labelled), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                              check=True, capture_output=True).stdout
    rows = [grey[y * 640:(y + 1) * 640] for y in range(360)]
    label = [v for row in rows[340:358] for v in row[2:316]]  # 157 x 9 dots at 2 px, one dot in from the corner
    dots = sum(glyph.count("#") for glyph in (ailabel.FONT[c] for c in ailabel.LABEL.upper()))
    assert sum(v > 200 for v in label) == 4 * dots and min(label) < 20
    assert max(rows[0]) - min(rows[0]) < 4 and abs(rows[339][100] - rows[0][100]) < 4  # the rest is untouched


def test_letter_ends_with_an_ai_draft_disclosure_outside_the_checked_letter():
    plan = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "PET 0.4 s.", "writer": "Muse Spark",
            "unsupported": ["Says a warrant is met."]}
    section = pack.letter_section(plan)
    assert section.index("Check before sending") < section.index("Drafted by Muse Spark from the measurements")
    assert "Read and approved by: ____ (name, role, date)" in section and plan["letter"] == "PET 0.4 s."
    clean = pack.letter_section({**plan, "unsupported": [], "judged_by": pack.JUDGE})
    assert clean.index("checked against the measurements") < clean.index("Drafted by")


def test_crowd_mode_can_cover_people_vehicles_or_both():
    import analyze
    site = {"person": "person", "vehicles": ["car", "motorcycle"]}
    assert analyze.crowd_concepts(site) == []
    assert analyze.crowd_concepts({**site, "person_mode": "crowd"}) == ["person"]
    assert analyze.crowd_concepts({**site, "person_mode": "crowd", "vehicle_mode": "crowd"}) == ["person", "car", "motorcycle"]


def test_pedestrian_pieces_shorter_than_a_second_are_dropped():
    import analyze
    site = {"image_points": SQUARE_IMG, "world_points": SQUARE_ROAD}
    H = road.homography(SQUARE_IMG, SQUARE_ROAD)
    walk = lambda frames: {f: [190, 100 + 5 * f, 210, 140 + 5 * f] for f in frames}  # 0.25 m a frame
    people, _ = analyze.road_tracks(site, H, {"a": walk(range(20)), "b": walk(range(5))}, {}, (400, 400))
    assert set(people) == {"a/0"}


def fake_open_model(replies):
    """A local stand-in for llama-server: answers each POST with the next reply (an int: that HTTP status) and keeps
    (path, body, headers)."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    seen = []

    class Fake(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))), dict(self.headers)))
            reply = replies.pop(0)
            status = reply if isinstance(reply, int) else 200  # a bare status answers with an error, e.g. 400
            self.send_response(status)
            reply = json.dumps({"error": {"message": "response_format unsupported"}} if status != 200 else reply).encode()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


def test_open_weights_letter_writer_gets_the_prompt_and_street_photo():
    """With LETTER_MODEL_URL set, the plan comes from an OpenAI-compatible server (llama-server running Muse Glimmer),
    and the server's own timings and usage travel with it into plan.json."""
    import contextlib, io, tempfile
    from pathlib import Path
    plan = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "l"}
    timings, usage = {"prompt_ms": 2000.0, "predicted_ms": 410000.0}, {"prompt_tokens": 900, "completion_tokens": 5000}
    server, seen = fake_open_model([{"id": "req-1", "choices": [{"message": {"content": json.dumps(plan)},
                                     "finish_reason": "stop"}], "timings": timings, "usage": usage}])
    old = pack.LETTER_URL
    pack.LETTER_URL = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            photo = Path(tmp) / "street.jpg"
            photo.write_bytes(b"\xff\xd8jpeg")
            with contextlib.redirect_stderr(io.StringIO()):
                written = pack.model_plan("PROMPT", None, photo)
        assert written == {**plan, "timings": timings, "usage": usage, "request_id": "req-1", "wall_s": written["wall_s"],
                           "response_format": "json_schema"} and isinstance(written["wall_s"], float)
    finally:
        pack.LETTER_URL = old
        server.shutdown()
        server.server_close()
    path, body, _ = seen[0]
    content = body["messages"][0]["content"]
    assert path == "/v1/chat/completions" and body["response_format"]["type"] == "json_schema"
    assert content[0] == {"type": "text", "text": "PROMPT"} and content[1]["image_url"]["url"].startswith("data:image/jpeg")
    assert "Muse Glimmer" in pack.letter_section({**plan, "writer": "Muse Glimmer 30B (open weights)"})


def test_open_model_out_of_context_is_a_clear_error_not_an_empty_letter():
    """llama-server says only finish_reason "length" with content "" when thinking fills the context."""
    import contextlib, io
    server, _ = fake_open_model([{"choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                                  "usage": {"completion_tokens": 32000}}])
    old = pack.LETTER_URL
    pack.LETTER_URL = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        with contextlib.redirect_stderr(io.StringIO()) as log:
            pack.open_model_reply("PROMPT", None, {"type": "object"})
        raise AssertionError("an out-of-context reply was accepted")
    except ValueError as err:
        assert "ran out of context after 32000 tokens" in str(err) and "-c" in str(err)
        assert "open model reply: finish_reason length" in log.getvalue()  # still a try in the notebook's count
    finally:
        pack.LETTER_URL = old
        server.shutdown()
        server.server_close()


def test_open_model_footer_uses_the_server_timings_only():
    plan = {"fix": "f", "why": "w", "image_prompt": "i", "letter": "l", "writer": "Muse Glimmer 30B (open weights, self-hosted)",
            "timings": {"prompt_ms": 1500.0, "predicted_ms": 410700.0}}
    old = pack.LETTER_URL, pack.LETTER_HOST
    pack.LETTER_URL, pack.LETTER_HOST = "http://127.0.0.1:8080/v1", "Kaggle 2 x T4"
    try:
        assert f"{pack.LETTER_MODEL} wrote this in 412 s on Kaggle 2 x T4 (open weights)." in pack.letter_section(plan)
        no_numbers = pack.letter_section({**plan, "timings": {"prompt_ms": "1500", "predicted_ms": None}})
        assert "wrote this in" not in no_numbers and "Fix and letter written by Muse Glimmer 30B" in no_numbers
        pack.LETTER_URL = ""  # Spark wrote it: timings in its JSON are never shown as a run time
        assert "wrote this in" not in pack.letter_section(plan)
    finally:
        pack.LETTER_URL, pack.LETTER_HOST = old


def test_open_model_can_write_digits_only_as_measured_numbers():
    """The plan's JSON schema holds every string to a "pattern" that llama-server turns into a grammar. Python's re reads
    the same pattern, so here it stands in for the grammar: every measured number gets through, nothing else does."""
    import re
    e = {"person": "1/0", "vehicle": "car#1", "tier": "serious", "pet_s": 0.4, "vehicle_kmh": 27.3, "death_risk_pct": 1.1,
         "t_person_s": 3.0, "t_vehicle_s": 3.4, "with_limit": {"20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    measured = pack.facts({"name": "स्कूल गेट"}, [e], {"minutes": 2.0, "crossings": 3, "vehicles": 1200})
    known = pack.LETTER_PROMPT.format(facts=measured, language="Hindi") + "\n" + measured
    schema = pack.plan_schema(known)
    pattern = schema["properties"]["letter"]["pattern"]
    assert schema["required"] == list(pack.PLAN_KEYS) and {p["pattern"] for p in schema["properties"].values()} == {pattern}
    written = lambda text: re.fullmatch(pattern, json.dumps(text, ensure_ascii=False)[1:-1])  # as between the quotes
    for n in pack.NUMBER.findall(known):
        assert written(f"{n} km/h, {n}.\nस्कूल के बाहर \"{n}\"") and not pack.unmeasured(n, known), n
    for lie in ("It happened 7 times.", "27.35 km/h", "0.427.3", "27.3.4", "७ बार", "۳0"):  # ۳0 reads as 30
        assert not written(lie) and pack.unmeasured(lie, known), lie
    assert not written("27.3<s>0.4")  # llama.cpp drops a special token's text from the reply: "27.30.4"
    assert not re.fullmatch(pattern, r"\u0032") and re.fullmatch(pattern, r"\n\"\\")  # \u0032 is a hidden 2
    assert pack.number_pattern("no numbers") == pack.number_pattern("") and not re.fullmatch(pack.number_pattern(""), "1")



def test_open_model_grammar_allows_the_measured_numbers_not_the_prompts():
    """The grammar's numbers are the ones the code check accepts, the measurements and the principal's notes, never
    the prompt's wording (its "SAM 3.1" would let 3.1 through)."""
    seen, old = [], pack.model_plan
    pack.model_plan = lambda prompt, key, photo=None, known=None: seen.append(known) or {
        "fix": "f", "why": "w", "image_prompt": "i", "letter": "l"}
    try:
        pack.ask_plan("PROMPT naming SAM 3.1", '{"pet_s": 0.4}', None, stated=["We have 1,200 pupils."])
    finally:
        pack.model_plan = old
    assert "3.1" not in seen[0] and "0.4" in seen[0] and "1,200" in seen[0]

def test_open_model_sends_its_key_only_when_set_and_says_where_it_ran():
    import contextlib, io
    reply = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
    server, seen = fake_open_model([reply, reply])
    old = pack.LETTER_URL, pack.LETTER_KEY
    pack.LETTER_URL = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        with contextlib.redirect_stderr(io.StringIO()) as log:
            for key in ("", "test-key"):
                pack.LETTER_KEY = key
                pack.open_model_reply("PROMPT", None, {"type": "object"})
    finally:
        pack.LETTER_URL, pack.LETTER_KEY = old
        server.shutdown()
        server.server_close()
    assert "Authorization" not in seen[0][2] and seen[1][2]["Authorization"] == "Bearer test-key"
    assert seen[1][1]["response_format"] == {"type": "json_schema", "json_schema": {"name": "plan", "schema": {"type": "object"}}}
    assert log.getvalue().count("open model reply:") == 2 and "test-key" not in log.getvalue()
    assert pack.writer_label("") == "Muse Spark"
    assert pack.writer_label("http://127.0.0.1:8080/v1") == f"{pack.LETTER_MODEL} (open weights, self-hosted)"
    assert pack.writer_label("https://api.example.com/v1") == f"{pack.LETTER_MODEL} (open weights)"  # could be anyone's


def test_open_model_letters_still_face_the_number_check_and_the_judge():
    """The schema is only the first layer: a server that ignores it is still caught by unmeasured(), then the judge.
    The retry note quotes the bad number, so the schema comes from the measurements alone and 12 stays out of it."""
    import contextlib, io, re
    good = {"fix": "speed table", "why": "cars at 27.3 km/h", "image_prompt": "add a speed table", "letter": "PET 0.4 s."}
    as_reply = lambda plan: {"choices": [{"message": {"content": json.dumps(plan)}, "finish_reason": "stop"}]}
    server, seen = fake_open_model([as_reply({**good, "letter": "It happened 12 times."}), as_reply(good)])
    judged, old = [], (pack.LETTER_URL, pack.judge_problems, pack.NUMBER_LOCK)
    pack.LETTER_URL, pack.NUMBER_LOCK = f"http://127.0.0.1:{server.server_port}/v1", True
    pack.judge_problems = lambda letter, measured, key: judged.append(letter) or []
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            plan = pack.ask_plan("PROMPT", '{"pet_s": 0.4, "vehicle_kmh": 27.3}', "key")
    finally:
        pack.LETTER_URL, pack.judge_problems, pack.NUMBER_LOCK = old
        server.shutdown()
        server.server_close()
    first, second = (body for _, body, _ in seen)
    pattern = lambda body: body["response_format"]["json_schema"]["schema"]["properties"]["letter"]["pattern"]
    assert "not in the measurements: 12" in second["messages"][0]["content"][0]["text"]
    assert pattern(second) == pattern(first) and not re.fullmatch(pattern(second), "It happened 12 times.")
    assert plan["letter"] == good["letter"] and judged == [good["letter"]] and plan["judged_by"] == pack.JUDGE


def test_stuck_open_model_text_is_sent_back_and_the_number_lock_is_opt_in():
    """Fireworks, 29 Oct: under the number pattern Muse Spark Open wrote "a0a0a0..." in every field. It held no
    unmeasured number and no claim, so both checks passed it; now it goes back, and the pattern is off by default."""
    import contextlib, io
    real = ("The 2.0 minute video recorded 2 serious near-misses at the crossing outside our gate, with cars at 38.0 "
            "km/h and 29.0 km/h passing the spot where pupils had just stood. We ask for a raised zebra crossing.")
    good = {"fix": "raised zebra crossing", "why": "cars at 38.0 km/h", "image_prompt": "add a raised crossing",
            "letter": real}
    stuck = {k: "a0" * 40 for k in good}
    assert pack.unreadable(stuck) == list(pack.PLAN_KEYS) and pack.unreadable(good) == []
    assert pack.unreadable({**good, "letter": "aa0 " * 80}) == ["letter"]  # words, but one piece repeated
    as_reply = lambda plan: {"choices": [{"message": {"content": json.dumps(plan)}, "finish_reason": "stop"}]}
    server, seen = fake_open_model([as_reply(stuck), as_reply(good)])
    old = pack.LETTER_URL, pack.judge_problems, pack.NUMBER_LOCK
    pack.LETTER_URL, pack.NUMBER_LOCK = f"http://127.0.0.1:{server.server_port}/v1", False
    pack.judge_problems = lambda letter, measured, key: []
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            plan = pack.ask_plan("PROMPT", '{"minutes": 2.0, "serious": 2, "kmh": [38.0, 29.0]}', "key")
    finally:
        pack.LETTER_URL, pack.judge_problems, pack.NUMBER_LOCK = old
        server.shutdown()
        server.server_close()
    first, second = (body for _, body, _ in seen)
    assert first["response_format"]["json_schema"]["schema"] == pack.PLAN_SCHEMA  # no "pattern" unless asked for
    assert "not readable text" in second["messages"][0]["content"][0]["text"]
    assert plan["letter"] == real and plan["tries"] == 2


def test_glimmer_judges_through_its_own_url_and_judged_by_names_only_the_judges_that_ran():
    """JUDGE_MODEL_URL makes the open-weights model a judge, with Spark or alone; its objection goes back like Spark's,
    an unreadable reply is a problem, and the letter server's key never goes to a judge on another server."""
    import contextlib, io
    good = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "Cars passed close to children."}
    as_reply = lambda content: {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    server, seen = fake_open_model([as_reply('{"problems": ["Says a warrant is met."]}'), as_reply('{"problems": []}'),
                                    as_reply('{"problems": []}'), as_reply("no JSON here")])
    url, prompts, sparks = f"http://127.0.0.1:{server.server_port}/v1", [], []
    old = pack.model_plan, pack.spark_reply, pack.JUDGE_URL, pack.LETTER_URL, pack.LETTER_KEY
    pack.model_plan = lambda prompt, key, photo=None, known=None: prompts.append(prompt) or good
    pack.spark_reply = lambda prompt, image, key: sparks.append(prompt) or '{"problems": []}'
    pack.JUDGE_URL, pack.LETTER_URL, pack.LETTER_KEY = url, "http://127.0.0.1:9/v1", "letter-key"  # writer elsewhere
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            alone = pack.ask_plan("PROMPT", "{}", None)  # no Meta key: Glimmer judges alone, objects once, then passes
            both = pack.ask_plan("PROMPT", "{}", "key")
            unreadable = pack.judge_problems("letter", "{}", None)
    finally:
        pack.model_plan, pack.spark_reply, pack.JUDGE_URL, pack.LETTER_URL, pack.LETTER_KEY = old
        server.shutdown()
        server.server_close()
    glimmer = pack.writer_label(url)
    assert alone["judged_by"] == glimmer and "Says a warrant is met." in prompts[1] and len(sparks) == 1
    assert both["judged_by"] == f"{pack.JUDGE} and {glimmer}" and unreadable == ["The reviewer's reply could not be read."]
    assert "and the claims by Muse Spark (a separate reviewer) and Muse Glimmer" in pack.letter_section(both)
    path, body, headers = seen[0]
    assert path == "/v1/chat/completions" and body["response_format"]["json_schema"]["schema"] == pack.PROBLEMS_SCHEMA
    assert good["letter"] in body["messages"][0]["content"][0]["text"] and "Authorization" not in headers


SPARK_OPEN = "accounts/fireworks/models/muse-spark-open"  # Fireworks' API model id for Muse Spark Open
FIREWORKS = "https://api.fireworks.ai/inference/v1"  # never called here: only its host name is read


def test_spark_open_on_fireworks_judges_a_glimmer_letter_with_its_own_model_id_and_key():
    """The API model id is not the name shown, the label says where it ran, and a Glimmer writer and a Spark Open judge
    on two servers each get their own model id and key."""
    import contextlib, io
    good = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "PET 0.4 s."}
    as_reply = lambda content: {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    writer, wrote = fake_open_model([as_reply(json.dumps(good))])
    judge, judged = fake_open_model([as_reply('{"problems": []}')])
    url = lambda server: f"http://127.0.0.1:{server.server_port}/v1"
    names = "LETTER_URL", "LETTER_MODEL", "LETTER_KEY", "JUDGE_URL", "JUDGE_MODEL", "JUDGE_KEY"
    old = [getattr(pack, n) for n in names]
    for n, value in zip(names, (url(writer), "Muse Glimmer 30B", "letter-key", url(judge), SPARK_OPEN, "judge-key")):
        setattr(pack, n, value)
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            plan = pack.ask_plan("PROMPT", '{"pet_s": 0.4}', None)
    finally:
        for n, value in zip(names, old):
            setattr(pack, n, value)
        for server in (writer, judge):
            server.shutdown()
            server.server_close()
    (_, to_writer, writer_headers), (_, to_judge, judge_headers) = wrote[0], judged[0]
    assert to_writer["model"] == "Muse Glimmer 30B" and writer_headers["Authorization"] == "Bearer letter-key"
    assert to_judge["model"] == SPARK_OPEN and judge_headers["Authorization"] == "Bearer judge-key"
    assert plan["judged_by"] == "Muse Spark Open (open weights, self-hosted)"  # this fake judge ran on this machine
    assert pack.writer_label(FIREWORKS, SPARK_OPEN) == "Muse Spark Open (open weights, on Fireworks)"
    assert pack.writer_label("http://127.0.0.1:8080/v1", "Muse Glimmer 30B") == "Muse Glimmer 30B (open weights, self-hosted)"


def test_a_judge_on_the_letter_server_uses_the_letter_key_when_it_has_none():
    """One key-protected server (e.g. vLLM --api-key) as writer and judge: with only LETTER_MODEL_KEY set, the judge
    call is authorised too, as it is the same server."""
    import contextlib, io
    good = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "PET 0.4 s."}
    as_reply = lambda content: {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    server, seen = fake_open_model([as_reply(json.dumps(good)), as_reply('{"problems": []}')])
    url = f"http://127.0.0.1:{server.server_port}/v1"
    names = "LETTER_URL", "LETTER_KEY", "JUDGE_URL", "JUDGE_KEY"
    old = [getattr(pack, n) for n in names]
    for n, value in zip(names, (url, "letter-key", url, "")):
        setattr(pack, n, value)
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            pack.ask_plan("PROMPT", '{"pet_s": 0.4}', None)
    finally:
        for n, value in zip(names, old):
            setattr(pack, n, value)
        server.shutdown()
        server.server_close()
    assert [headers.get("Authorization") for _, _, headers in seen] == ["Bearer letter-key", "Bearer letter-key"]


def test_fireworks_key_comes_from_env_or_dotenv_only_for_fireworks():
    """With no key set for a Fireworks URL, FIREWORKS_API_KEY is read as sam.load_api_key reads MODEL_API_KEY; any
    other server never gets it, and a key set for the server wins."""
    import os, sam, tempfile
    from pathlib import Path
    import openweights
    old = sam.ENV_FILE, {k: os.environ.pop(k, None) for k in ("FIREWORKS_API_KEY", "MODEL_API_KEY")}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            sam.ENV_FILE = Path(tmp) / ".env"
            sam.ENV_FILE.write_text("MODEL_API_KEY=meta-test\nFIREWORKS_API_KEY = fw-file\n")
            assert openweights.server_key(FIREWORKS, "") == "fw-file" and sam.load_api_key() == "meta-test"
            assert openweights.server_key(FIREWORKS, "set-for-it") == "set-for-it"
            assert openweights.server_key("http://127.0.0.1:8080/v1", "") == ""
            assert openweights.server_key("https://api.example.com/v1", "") == ""
            os.environ["FIREWORKS_API_KEY"] = "fw-env"
            assert openweights.server_key(FIREWORKS, "") == "fw-env"
    finally:
        sam.ENV_FILE = old[0]
        for k, value in old[1].items():
            os.environ.pop(k, None)
            if value is not None:
                os.environ[k] = value


def test_rejected_json_schema_retries_once_as_json_object_and_the_run_record_says_so():
    """Fireworks may refuse the schema's patterns: one retry asks for any JSON object, the code check still runs, and
    letter-provenance.json beside plan.json records the run (never the key); the footer shows the measured wall time."""
    import contextlib, io, tempfile, urllib.error
    from pathlib import Path
    good = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "PET 0.4 s."}
    usage = {"prompt_tokens": 900, "completion_tokens": 300, "completion_tokens_details": {"reasoning_tokens": 120}}
    server, seen = fake_open_model([400, {"id": "fw-req-9", "usage": usage, "choices": [
        {"message": {"content": json.dumps(good), "reasoning_content": "..."}, "finish_reason": "stop"}]}, 500])
    names = "LETTER_URL", "LETTER_MODEL", "LETTER_KEY", "LETTER_HOST", "JUDGE_URL"
    old = [getattr(pack, n) for n in names]
    pack.LETTER_URL, pack.LETTER_MODEL, pack.LETTER_KEY, pack.LETTER_HOST, pack.JUDGE_URL = (
        f"http://127.0.0.1:{server.server_port}/v1", SPARK_OPEN, "secret-key-123", "", "")
    try:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()) as log:
            plan = pack.new_plan(Path(tmp), "PROMPT", '{"pet_s": 0.4}', None, None)
            record = (Path(tmp) / pack.PROVENANCE).read_text()
            try:
                pack.open_model_reply("PROMPT", None, {"type": "object"})  # any other error is not retried
                raise AssertionError("HTTP 500 was accepted")
            except urllib.error.HTTPError as err:
                assert err.code == 500
        pack.LETTER_URL = FIREWORKS  # the footer only: nothing is sent
        footer = pack.letter_section({**plan, "wall_s": 1.8})
    finally:
        for n, value in zip(names, old):
            setattr(pack, n, value)
        server.shutdown()
        server.server_close()
    assert [body["response_format"]["type"] for _, body, _ in seen] == ["json_schema", "json_object", "json_schema"]
    assert "rejected json_schema" in log.getvalue() and "secret-key-123" not in log.getvalue() + record
    kept = json.loads(record)
    assert kept == {"model": SPARK_OPEN, "host": "127.0.0.1", "request_id": "fw-req-9", "usage": usage,
                    "wall_s": kept["wall_s"], "timings": None, "response_format": "json_object", "tries": 1,
                    "judged_by": None, "letter_sha256": pack.sha256(good["letter"])} and isinstance(kept["wall_s"], float)
    assert "Muse Spark Open wrote this in 2 s on Fireworks (open weights)." in footer

def test_glimmer_notebook_is_pinned_hash_checked_and_records_its_run():
    """The Kaggle notebook runs unattended for 40 minutes, so its pins and its Python are checked here first."""
    import ast, re
    from pathlib import Path
    notebook = json.loads(Path(__file__).with_name("kaggle").joinpath("<removed-run-record>").read_text())
    code = ["".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code"]
    for cell in code:
        if not cell.startswith("%%"):
            ast.parse("\n".join(line for line in cell.splitlines() if not line.startswith("!")))
    text = "\n".join(code)
    for pin in ("--branch b11976", "revision=REVISION", "b44f1072cf75e918a1b82a3a17b45c4389b076e7",
                "4cc57c0f51040a226e5a72cc47b7613f7772950e460a665f7083de89f183f60e",
                "f48b452316f9b213758e8659444029b961a24a07f99a1abb2a9f88b06f7c00c6", "'-np', '1'", "(32768, 16384)",
                "'reasoning_strength': 'medium'", "'--temp', '1.0', '--top-p', '0.95', '--top-k', '64'",
                "LETTER_MODEL_HOST", "<removed-run-record>", "build_info", "GIT_SHA", "pack_py_sha256",
                "run.stderr.count('open model reply:')", "'tries': tries",  # pack.open_model_reply logs each try
                "os.path.exists(f'{CW}/judge_bench.py')", "'JUDGE_MODEL_URL': 'http://127.0.0.1:8080/v1'",
                "k != 'MODEL_API_KEY'", "<removed-run-record>", "'--out', BENCH_JSON, '--glimmer', '1'",  # the Glimmer-only judge pass, skipped without a bench
                "f'bench: {BENCH_FROM}"):
        assert pin in text, pin
    assert re.search(r"assert sha256\(path\) == SHA256\[name\]", text)
    assert "run by the author" in text  # who ran it, as README says
    assert "/kaggle/input/**/judge-bench.json" not in text  # v3: the public sample/ bench only, never an attached one
    assert "billion" not in Path(__file__).with_name("README.md").read_text()  # the product name, not a parameter count


def test_map_draws_each_event_where_it_happened():
    import roadmap
    walk = {f: (0.0, -3 + 0.15 * f) for f in range(40)}
    path = roadmap.path_around(walk, 20, 10)
    assert path[0] == [0.0, -3.0] and path[-1] == [0.0, 2.7] and len(path) == 20  # 2 s each side (to the track's end), every 2nd frame
    events = [{"tier": "serious", "vehicle": "car#1", "vehicle_kmh": 30.0, "pet_s": 0.4, "where": [0.0, 0.0],
               "path_person": path, "path_vehicle": [[-5.0, 0.0], [5.0, 0.0]]},
              {"tier": "close pass", "vehicle": "bus#2", "vehicle_kmh": 20.0, "pet_s": 2.0, "where": [3.0, 1.0]},
              {"tier": "serious", "vehicle": "car#3", "vehicle_kmh": 9.0, "pet_s": 1.0}]  # no position: left out
    svg = roadmap.svg(events, [[-2, -2], [2, -2], [2, 2], [-2, 2]])
    assert svg.count("<circle") == 2 and svg.count('class="hit"') == 1 and svg.count('class="near"') == 1
    assert "#1" in svg and "#2" in svg and "car at 30.0 km/h" in svg and svg.count("<polyline") == 2
    empty = roadmap.svg([], [[0, 0], [1, 0], [1, 1], [0, 1]])
    assert 'class="area"' in empty and "<circle" not in empty  # never empty: at least the measured area
    site = {"world_points": [[-2, -2], [2, -2], [2, 2], [-2, 2]]}
    assert "Where it happened" in pack.map_section(events, site)
    assert "Where people crossed" in pack.map_section(events[2:], site)  # no near-miss placed: still a map
    unplaced_first = roadmap.svg(events[2:] + events[:1], [[-2, -2], [2, -2], [2, 2], [-2, 2]])
    assert ">#2</text>" in unplaced_first and ">#1</text>" not in unplaced_first  # the dot keeps card #2's number


def test_busy_spans_give_the_gaps_and_the_longest_wait_for_one():
    cells = road.crossing_cells({"p": walking_across(40)}, 10)
    moving, parked = edges_along_x(8.0, 10, 60), {f: ((-1.0, 2.0), (1.0, 2.0)) for f in range(600)}
    assert road.busy_spans({"car#1": moving, "car#2": parked}, 10, cells) == [[2.9, 3.4]]  # frames 29-33
    assert road.gaps_between([[2.9, 3.4]], 60.0) == [[0.0, 2.9], [3.4, 60.0]]
    assert road.gaps_between([], 5.0) == [[0.0, 5.0]]
    line = road.timeline({"p": walking_across(40)}, {"car#1": moving}, 10, 600)
    assert line == {"duration_s": 60.0, "busy_s": [[2.9, 3.4]]}
    assert road.timeline({}, {"car#1": moving}, 10, 600) is None  # nobody crossed: no crossing to time
    assert road.exposure({"p": walking_across(40)}, {"car#1": moving}, 10, 600)["longest_without_6s_gap_s"] == 3.4
    gaps = [[0.0, 2.0], [3.0, 10.0], [11.0, 24.0], [25.0, 52.0], [53.0, 60.0]]  # 2, 7, 13, 27, 7 s
    assert road.longest_without(gaps, 60.0) == 3.0 and road.longest_without(gaps[:1], 60.0) == 60.0
    assert road.longest_without([[2.9, 8.9]], 10.0) == 2.9  # exactly 6 s is a gap of 6 s, float error or not


def test_gap_barcode_colours_every_gap_and_links_the_near_misses():
    import analyze, tempfile
    from pathlib import Path
    import roadmap
    timeline = {"duration_s": 60.0, "busy_s": [[2.0, 3.0], [10.0, 11.0], [24.0, 25.0], [52.0, 53.0]]}
    events = [{"tier": "serious", "vehicle": "car#1", "pet_s": 0.4, "t_person_s": 10.5},
              {"tier": "close pass", "vehicle": "bus#2", "pet_s": 2.0, "t_person_s": 24.2}]
    strip = roadmap.gap_strip(timeline, events, shown=1)
    assert strip.count('class="busy"') == 4 and strip.count('class="gap12"') == 2 and strip.count('class="gap6"') == 2
    assert strip.count('class="cut"') == 2 and 'href="#event-1"' in strip and "#event-2" not in strip  # 1 card shown
    assert strip.index('href="#event-1"') > strip.index("close pass at 24.2 s: bus")  # the linked dot is on top
    assert "Longest stretch with no gap of 6 s: 3 s." in strip and "may be shorter" not in strip
    assert "the whole recording" in roadmap.gap_strip({"duration_s": 39.0, "busy_s": [[0.2, 38.0]]}, [])
    assert "may be shorter" in roadmap.gap_strip(timeline, events, 5, [2, 10])  # missed vehicles make false gaps
    assert roadmap.gap_strip(None, events) == "" and roadmap.time_labels(39.0) == [0, 5, 10, 15, 20, 25, 30, 35]
    page = pack.page({"world_points": SQUARE_ROAD}, [], {"minutes": 1}, None, None, 10, timeline=timeline)
    assert "Gaps in traffic" in page
    with tempfile.TemporaryDirectory() as folder:  # analyze keeps the spans apart from the facts' exposure
        analyze.write_events(Path(folder), {}, [], {"minutes": 1}, None, None, timeline=timeline)
        assert json.loads((Path(folder) / "events.json").read_text())["timeline"] == timeline


def test_map_ground_is_the_photo_seen_from_above():
    """A 320 x 240 photo, 20 px a metre, road (0, 0) at pixel (100, 100): in view -5 to 11 m across, -5 to 7 m down."""
    import contextlib, io, subprocess, tempfile
    from pathlib import Path
    import roadmap
    H = road.homography(SQUARE_IMG, SQUARE_ROAD)
    rect = roadmap.view_rect(H, (-8, -2, 9, 12), (5, 5), (320, 240))
    assert [round(v, 3) for v in rect] == [-5.0, -2.0, 9.0, 7.0]  # the largest part of the map in the photo
    assert roadmap.in_photo(H, (-6, 0, 1, 1), (320, 240)) is None  # a corner left of the photo
    assert roadmap.view_rect(H, (20, 20, 30, 30), (25, 25), (320, 240)) is None  # all of it out of view
    site = {"image_points": SQUARE_IMG, "world_points": SQUARE_ROAD}
    events = [{"tier": "serious", "vehicle": "car#1", "vehicle_kmh": 30.0, "pet_s": 0.4, "where": [5.0, 5.0]}]
    with tempfile.TemporaryDirectory() as folder:
        out, photo = Path(folder), Path(folder) / "street.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=320x240", "-vf",
                        "drawbox=x=100:y=100:w=220:h=140:color=lime:t=fill", "-frames:v", "1", str(photo)], check=True)
        picture, rect = roadmap.ground(photo, site, events, out)
        assert rect == [-2.0, -2.0, 11.0, 7.0] and picture.startswith("data:image/jpeg;base64,")  # map: -2..12 m
        size = (round(13 * 2 * 640 / 14), round(9 * 2 * 640 / 14))  # 2 ground pixels per map pixel
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out / roadmap.GROUND), "-f", "rawvideo", "-pix_fmt",
                              "rgb24", "-"], check=True, capture_output=True).stdout
        rgb = lambda x, y: raw[3 * (round(y) * size[0] + round(x)):3 * (round(y) * size[0] + round(x)) + 3]
        assert len(raw) == 3 * size[0] * size[1]
        px = lambda u, v: rgb((u + 2) * size[0] / 13, (v + 2) * size[1] / 9)  # road metres to ground pixels
        assert px(5, 5)[1] > 200 > 60 > px(5, 5)[0] and px(-1, -1)[0] > 200 > 60 > px(-1, -1)[1]  # lime road, red kerb
        assert px(0.5, 3)[1] > 200 > 60 > px(-0.5, 3)[1]  # the edge stays where it is in metres
        svg = roadmap.svg(events, SQUARE_ROAD, ground=(picture, rect))
        assert '<image class="ground" href="data:image/jpeg;base64,' in svg and 'x="0.0" y="0.0"' in svg
        assert "standing objects lean" in pack.map_section(events, site, (picture, rect))
        assert "standing objects lean" not in pack.map_section(events, site)
        assert roadmap.ground(photo, site | {"view": "top-down"}, events, out) is None  # already seen from above
        assert roadmap.ground(photo, site, [{"tier": "serious"}], out)[1] == rect  # nothing placed: the area's ground
        with contextlib.redirect_stderr(io.StringIO()) as said:
            assert roadmap.ground(out / "missing.jpg", site, events, out) is None
        assert "no street photo under the map" in said.getvalue()


BAND_IMG = [[60, 120], [260, 120], [260, 220], [60, 220]]  # 20 px a metre on a 320 x 240 photo
BAND_ROAD = [[0, 0], [10, 0], [10, 5], [0, 5]]
BAND_EVENTS = [{"tier": "serious", "where": [3.0, 2.5], "path_person": [[3.0, 0.5], [3.0, 4.5]]},
               {"tier": "close pass", "where": [5.0, 2.0], "path_person": [[5.0, 4.5], [5.0, 1.0]]}]  # the other way


def test_fix_band_runs_along_the_walk_over_every_near_miss():
    import fixband
    assert fixband.band(BAND_EVENTS) == [[6.0, -0.5], [6.0, 5.5], [2.0, 5.5], [2.0, -0.5]]  # 1 m past paths and spots
    one = fixband.band(BAND_EVENTS[:1])
    assert math.dist(one[1], one[2]) == fixband.BAND_MIN_WIDTH_M and math.dist(one[0], one[1]) == 6.0
    assert fixband.band([{"where": [3.0, 2.5]}]) is None and fixband.band([]) is None  # no walked path, no band
    quad = fixband.pixels(road.homography(BAND_IMG, BAND_ROAD), fixband.band(BAND_EVENTS))
    assert [tuple(round(v) for v in p) for p in quad] == [(180, 110), (180, 230), (100, 230), (100, 110)]
    for corners in (quad, quad[::-1]):  # either way round
        test = fixband.inside(corners)
        assert [eval(test, {"gte": lambda a, b: a >= b, "X": x, "Y": y}) for x, y in ((140, 170), (90, 170), (140, 240))] == [1, 0, 0]
    assert fixband.place(quad, (320, 240)) == "bottom centre" and fixband.place([(160, 120)] * 4, (320, 240)) == "centre"
    assert fixband.place([(10, 10)] * 4, (320, 240)) == "top left"


def test_fix_is_kept_only_inside_the_band_and_redrawn_once_when_muse_image_strays():
    """Muse Image stubbed by local pictures: a first one flipped (it moved the street), then one that kept it."""
    import contextlib, fixband, io, subprocess, tempfile
    from pathlib import Path

    def rgb(image, x, y):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(image), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             check=True, capture_output=True).stdout
        return raw[3 * (y * 320 + x):3 * (y * 320 + x) + 3]

    with tempfile.TemporaryDirectory() as tmp:
        out, calls = Path(tmp), []
        photo = out / "street.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=320x240", "-frames:v", "1", "-q:v", "2",
                        str(photo)], check=True)

        def muse_image(image, words, path):
            calls.append(words)
            flip = ",hflip" if len(calls) == 1 else ""
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(image), "-vf", f"scale=640:480{flip}", "-f", "image2",
                            "-c:v", "png", str(path)], check=True)
            return path

        site, plan = {"image_points": BAND_IMG, "world_points": BAND_ROAD}, {"fix": "a speed table", "image_prompt": "i"}
        people = [{0: [150, 150, 170, 200]}, {3: [0, 0, 9, 9]}]  # someone in the band; someone seen only later
        with contextlib.redirect_stderr(io.StringIO()) as said:
            images = fixband.draw(photo, plan["fix"], plan["image_prompt"], BAND_EVENTS, site, people, muse_image, out)
        assert "SSIM 0." in said.getvalue() and images == ("street-dots.svg", "street-fixed.webp", "street-band.svg") and len(calls) == 2
        assert "magenta band in the bottom centre of the photo with this fix: a speed table." in calls[0]
        assert calls[1] == calls[0] + fixband.STRONGER and not (out / fixband.RETRY).exists()  # the redraw was kept
        kept, guide = out / fixband.KEPT, out / fixband.GUIDE
        assert abs(rgb(kept, 40, 60)[1] - rgb(photo, 40, 60)[1]) < 30  # outside the band: the photo
        assert abs(rgb(kept, 110, 200)[1] - rgb(guide, 110, 200)[1]) < 30 < abs(rgb(photo, 110, 200)[1] - rgb(guide, 110, 200)[1])
        assert abs(rgb(kept, 160, 175)[1] - rgb(photo, 160, 175)[1]) < 30  # the person in the band: the photo
        assert max(rgb(photo, 4, 231)) < 40 < 200 < min(rgb(kept, 4, 231))  # a dot of the "AI-generated" label's A
        shown, today = (out / images[2]).read_text(), (out / images[0]).read_text()
        assert "6.0 m" in shown and "4.0 m" in shown and fixband.CAPTION in shown and "data:image/jpeg;base64," in shown
        assert shown.count("<circle") == today.count("<circle") == 2 and today.count('fill="#c0392b"') == 1
        assert shown.count("<polyline") == 2 and "<polygon" in shown and "<polygon" not in today
        page = pack.page(site, [], {"minutes": 0.3}, plan | {"why": "w", "letter": "l"}, images, 10)
        assert '<img src="street-band.svg"' in page and fixband.CAPTION in page
        assert fixband.figure(images[:2]) == "" and fixband.figure(None) == ""
        calls.clear()  # no walked path: Muse Image edits the whole photo with Spark's prompt, as before
        assert fixband.draw(photo, "a speed table", "i", [{"where": [3.0, 2.5]}], site, people, muse_image, out) == (
            "street.jpg", "street-fixed.webp") and calls == ["i"]


def test_fast_two_wheelers_keep_one_track_in_vehicle_crowd_mode():
    import crowd, analyze
    site = {"person": "person", "vehicles": ["motorcycle"], "person_mode": "crowd", "vehicle_mode": "crowd"}
    step = analyze.crowd_frames(site, "motorcycle", 60).step
    bike = lambda f: [f * 40 / 3.6 * 2, 100, f * 40 / 3.6 * 2 + 40, 120]  # 2 m long (40 px), 40 km/h at 20 px/m
    tracks = crowd.associate({f: [bike(f)] for f in range(0, 60, step)}, analyze.FPS)
    assert len(tracks) == 1 and analyze.crowd_frames(site, "person", 60).step == 2


def test_site_concepts_must_not_share_a_cache_name():
    import analyze, tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "site.json"
        path.write_text(json.dumps({"image_points": SQUARE_IMG, "world_points": SQUARE_ROAD,
                                    "vehicles": ["auto rickshaw", "Auto-Rickshaw"]}))
        try:
            analyze.load_site(path)
            raise AssertionError("duplicate concepts accepted")
        except SystemExit as err:
            assert "same cache name" in str(err)
        one = {"image_points": SQUARE_IMG, "world_points": SQUARE_ROAD, "vehicles": ["vehicle"]}
        path.write_text(json.dumps(one | {"person_mode": "auto", "vehicle_mode": "auto"}))
        assert analyze.load_site(path)["vehicles"] == ["vehicle"]
        path.write_text(json.dumps(one | {"vehicle_mode": "fast"}))
        try:
            analyze.load_site(path)
            raise AssertionError("unknown mode accepted")
        except SystemExit as err:
            assert "vehicle_mode" in str(err) and '"auto"' in str(err)
        path.write_text(json.dumps(one | {"vehicle_sizes_m": {"vehicle": [4.2, 1.7]}}))
        assert analyze.load_site(path)["vehicle_sizes_m"] == {"vehicle": [4.2, 1.7]}
        for sizes in ({"car": [4.2, 1.7]}, {"vehicle": [1.7, 4.2]}, {"vehicle": [4.2]}, {"vehicle": [4.2, 0]}):
            path.write_text(json.dumps(one | {"vehicle_sizes_m": sizes}))  # not a site concept, width first, ...
            try:
                analyze.load_site(path)
                raise AssertionError(f"bad vehicle_sizes_m accepted: {sizes}")
            except SystemExit as err:
                assert "vehicle_sizes_m" in str(err)
        base = {"image_points": SQUARE_IMG, "world_points": SQUARE_ROAD, "vehicles": ["car"]}
        for extra, ok in (({"zebra_m": []}, True), ({"zebra_m": SQUARE_ROAD, "gate_m": [[0, 0], [2, 0]]}, True),
                          ({"zebra_m": [[0, 0]]}, False), ({"gate_m": [[0, 0], [2, 0], [4, 0]]}, False),
                          ({"gate_m": [[0, "a"], [2, 0]]}, False)):
            path.write_text(json.dumps(base | extra))
            try:
                assert analyze.load_site(path)["vehicles"] == ["car"] and ok, extra
            except SystemExit as err:
                assert not ok and ("zebra_m" in str(err) or "gate_m" in str(err)), extra


def test_number_check_reads_grouped_numbers_and_non_english_facts():
    facts = json.dumps({"vehicles_per_hour": 1200, "site": "स्कूल गेट"}, ensure_ascii=False)
    assert pack.unmeasured("1,200 vehicles an hour", facts) == []
    assert pack.unmeasured("about 2,000 an hour", facts) == ["2,000"]
    assert "0921" not in pack.facts({"name": "स्कूल"}, [], {"minutes": 1})  # no \\u escapes to hide digits in


def test_paths_and_other_arrays_never_reach_the_letter_facts():
    """Every number in the facts counts as measured, so arrays of coordinates would let a letter's numbers through."""
    e = {"person": "1/0", "vehicle": "car#1", "tier": "serious", "pet_s": 0.5, "vehicle_kmh": 30.0, "death_risk_pct": 1.5,
         "t_person_s": 2.0, "t_vehicle_s": 2.5,
         "with_limit": {"20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}, "where": [41.7, 63.2],
         "path_person": [[57.9, 88.4]], "path_vehicle": [[77.3, 12.6]], "replay": [[71.1, 72.2]], "spans": [[13.7, 19.3]]}
    seen = {"minutes": 0.3, "crossings": 4, "spans": [[23.9, 31.7]], "replay": (44.4, 55.5)}
    text = pack.facts({"name": "gate"}, [e], seen)
    array_numbers = "41.7 63.2 57.9 88.4 77.3 12.6 71.1 72.2 13.7 19.3 23.9 31.7 44.4 55.5"
    assert pack.unmeasured(array_numbers, text) == sorted(array_numbers.split(), key=float)
    assert '"crossings": 4' in text and '"vehicle_kmh": 30.0' in text


def test_indian_sites_quote_the_supreme_court_order_in_code_never_in_the_letter():
    """2025 INSC 1189 is an order, para 35.5 says "using accident data", and Annexure 46 is MoRTH's, not the Court's."""
    box = pack.legal_section({"country": "in"})
    assert "Why the authority can act" in box and "reportable order of 7 October 2025, 2025 INSC 1189" in box
    assert "high-risk stretches using accident data" in box and "also suggestions for pedestrian crossing" in box
    assert f'{pack.ORDER_PDF}#page=33">Paragraph 35.5' in box and "not accidents" in box and "judgment" not in box
    assert "35.6" not in box and "Annexure 46" not in box  # no city given: paragraph 35.6 may not bind it
    pune = pack.legal_section({"country": "IN", "city": "Pune"})
    assert "Paragraph 35.6, page 34" in pune and "Pune is one of the 50 million-plus cities in Annexure 46 of MoRTH" in pune
    assert "35.6" not in pack.legal_section({"country": "IN", "city": "Gurugram"})
    assert pack.legal_section({"name": "gate"}) == pack.legal_section({"country": "GB"}) == ""
    assert box in pack.page({"country": "IN", "world_points": SQUARE_ROAD}, [], {"minutes": 1}, None, None, 10)
    measured = pack.facts({"name": "gate", "country": "IN"}, [], {"minutes": 1})
    assert pack.unmeasured("under paragraph 35.5 of 2025 INSC 1189", measured) == ["35.5", "1189", "2025"]


def test_raised_crossing_size_goes_to_muse_image_only():
    """The IRC size of a raised crossing is drawn, never offered to the letter as numbers it could quote."""
    plan = {"fix": "Raised zebra crossing", "image_prompt": "Add the crossing."}
    assert pack.fix_instruction(plan) == "Add the crossing. " + pack.RAISED_SPEC and "4 m wide" in pack.RAISED_SPEC
    assert pack.fix_instruction({**plan, "fix": "20 km/h zone with suitable signs"}) == "Add the crossing."
    assert pack.fix_instruction({**plan, "fix": "a suitable speed table"}).endswith(pack.RAISED_SPEC)
    assert "4 m" not in pack.LETTER_PROMPT and "hump" not in pack.LETTER_PROMPT
    pv2 = pack.engineering_lines({"minutes": 30, "crossings": 100, "vehicles": 500}, None)[0]
    assert "IRC:103-2012 cl. 6.7.4.1.2" in pv2 and "Second Revision, IRC 103-2022" in pv2


def test_filmcheck_flags_settings_that_break_speeds_or_metres():
    import filmcheck
    phone = [{"codec_type": "video", "width": 1920, "height": 1080, "r_frame_rate": "30/1", "avg_frame_rate": "30/1"},
             {"codec_type": "audio"}]

    def shot(**change):
        return [{**phone[0], **change}, phone[1]]
    assert filmcheck.problems(phone) == []
    assert filmcheck.problems(shot(r_frame_rate="30000/1001", avg_frame_rate="315600/10529")) == []  # 29.97 fps
    assert filmcheck.problems(shot(side_data_list=[{"rotation": 180}])) == []  # landscape the other way up
    for bad in (shot(r_frame_rate="24000/1001", avg_frame_rate="24000/1001"),  # Cinematic, Action mode, Auto FPS
                shot(avg_frame_rate="27/1"),                                  # the rate changed while recording
                shot(side_data_list=[{"rotation": -90}]), shot(tags={"rotate": "90"}),  # portrait
                shot(width=848, height=478), shot(width=3840, height=2160),  # a WhatsApp copy, 4K
                phone[:1]):                                                   # no sound
        assert len(filmcheck.problems(bad)) == 1, bad
    assert filmcheck.problems(phone[1:]) == ["no video stream"]


def test_filmcheck_reads_a_real_ffprobe_reply():
    import filmcheck, subprocess, tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "test.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:d=0.5", "-f", "lavfi",
                        "-i", "sine=d=0.5", "-c:v", "libx264", "-preset", "ultrafast", "-shortest", str(clip)], check=True)
        assert filmcheck.problems(filmcheck.probe(clip)) == []
        upright = Path(tmp) / "portrait.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-display_rotation", "90", "-i", str(clip), "-c", "copy", str(upright)],
                       check=True)
        assert filmcheck.problems(filmcheck.probe(upright))[0].startswith("shown 1080x1920")


def test_filmcheck_flags_hdr_and_spatial_audio():
    """iPhone HDR Video (HLG) and Spatial Audio, which ffprobe 9 names apple_apac, each give one thing to change."""
    import filmcheck
    phone = [{"codec_type": "video", "width": 1920, "height": 1080, "r_frame_rate": "30/1", "avg_frame_rate": "30/1",
              "color_transfer": "bt709"}, {"codec_type": "audio", "codec_name": "aac", "codec_tag_string": "mp4a"}]
    assert filmcheck.problems(phone) == []
    for transfer in ("arib-std-b67", "smpte2084"):
        assert filmcheck.problems([{**phone[0], "color_transfer": transfer}, phone[1]])[0].startswith("recorded in HDR")
    for apac in ({"codec_name": "apple_apac", "codec_tag_string": "apac"}, {"codec_name": "apac"},
                 {"codec_tag_string": "apac"}):
        found = filmcheck.problems([*phone, {"codec_type": "audio", **apac}])  # the stereo track is there too
        assert len(found) == 1 and "Spatial Audio" in found[0], apac


def view(dx=0, dy=0, height=200):
    """A 640 px wide grey frame cut from one fixed random street (8 px blobs and fine grain, smooth as a real view is
    at a quarter size), its content moved by (dx, dy) px."""
    import random
    rng, width = random.Random(3), 640 + 80
    blobs = [[rng.randrange(192) for _ in range(width // 8)] for _ in range((height + 80) // 8)]
    street = bytes(blobs[y // 8][x // 8] + rng.randrange(64) for y in range(height + 80) for x in range(width))
    return b"".join(street[(y + 40 - dy) * width + 40 - dx:(y + 40 - dy) * width + 680 - dx] for y in range(height))


def test_filmcheck_shift_reads_small_and_large_moves_past_traffic():
    import filmcheck
    ref = view()
    for move in ((3, -2), (18, -10), (-30, 7)):  # 18 and -10 fall between quarter-size pixels
        img = bytearray(view(*move))
        img[80 * 640:120 * 640] = bytes(40 * 640)  # a dark bus across a fifth of the frame
        assert filmcheck.shift(ref, bytes(img)) == move, move


def test_filmcheck_summary_needs_two_samples_in_a_row():
    import filmcheck
    assert filmcheck.summary([]) == {"max_shift_px": 0, "at_s": None, "moved": False, "dx_dy": None}
    one_sway = [(60, 0, 1), (120, 9, 0), (180, 1, -2), (240, 2, 0)]  # a bus or a gust: back at the next sample
    assert filmcheck.summary(one_sway) == {"max_shift_px": 9, "at_s": 120, "moved": False, "dx_dy": [9, 0]}
    sagged = [(60, 1, 0), (120, 0, 6), (180, 1, 7), (240, 0, 8)]
    assert filmcheck.summary(sagged) == {"max_shift_px": 8, "at_s": 120, "moved": True, "dx_dy": [0, 6]}
    assert not filmcheck.summary([(60, 0, 5), (120, 5, 5)])["moved"]  # 5 px is not over the line
    lines = filmcheck.camera_lines(filmcheck.summary(sagged))
    assert lines[1] == "" and "re-shoot, or set window_s to end before the move" in lines[0][0] and "2:00" in lines[0][0]
    found, note = filmcheck.camera_lines(filmcheck.summary(one_sway))
    assert found == [] and note.startswith("camera: largest shift 9 px (of 640) at 2:00")


def test_filmcheck_steadiness_samples_each_minute_skips_the_end_and_stops_when_dark():
    import filmcheck
    asked, real = [], (filmcheck.gray, filmcheck.shift)
    filmcheck.gray, filmcheck.shift = lambda clip, t: asked.append(t) or b"frame", lambda ref, img: (0, 0)
    try:
        assert not filmcheck.steadiness("clip", 1.0, 901.0)["moved"]
        assert asked == [1.0, *(1.0 + 60 * k for k in range(1, 15)), 900.0]  # every minute and the last second
        asked.clear()
        filmcheck.steadiness("clip", 1.0, 10.0)
        assert asked == [1.0, 3.25, 5.5, 7.75, 9.0]  # a 10 s test clip still gets two samples in a row
        frames = {1.0: view(), 61.0: view(0, 7), 121.0: view(0, 7), 181.0: b"",
                  241.0: bytes(v // 3 for v in view(0, 7))}  # sagged; one frame missing; then dusk
        filmcheck.gray, filmcheck.shift = lambda clip, t: frames[t], real[1]
        held = filmcheck.steadiness("clip", 1.0, 302.0)
    finally:
        filmcheck.gray, filmcheck.shift = real
    assert held == {"max_shift_px": 7, "at_s": 61.0, "moved": True, "dx_dy": [0, 7], "darker_pct": 67,
                    "dark_at_s": 241.0}
    found, _ = filmcheck.camera_lines(held)
    assert len(found) == 2 and found[1].startswith("the picture is 67% darker by 4:01")


def test_filmcheck_finds_a_knocked_phone_in_a_real_clip():
    """One end-to-end clip: the view slides 6 px left at 5 s and stays there."""
    import filmcheck, subprocess, tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "knocked.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=656x360:rate=5:d=12", "-vf",
                        "crop=640:360:x='if(gte(t,5),8,2)':y=0", "-c:v", "libx264", "-preset", "ultrafast", str(clip)],
                       check=True)
        held = filmcheck.steadiness(clip, 1.0, 12.0, every=8)
    assert held["moved"] and held["dx_dy"] == [-6, 0] and 5 <= held["at_s"] <= 8, held


DESIRE = {"a": [[[0.3, -3.7], [0.3, 3.9]]], "b": [[[1.1, -3.7], [1.1, 3.9]]], "c": [[[1.7, 3.9], [1.7, -3.7]]],
          "d": [[[9.4, -3.7], [9.4, 3.9]]]}  # four people across a road along x; a, b and c within 2 m


def test_desire_lines_are_crossings_not_pavement_walks():
    import analyze, tempfile
    from pathlib import Path
    fps, car = 10, edges_along_x(8.0, 10, 60)  # the road runs along x
    people = {"a/0": walking_across(40), "a/1": {f: (4.0, 1.5 * (f - 60) / 10) for f in range(60, 100)},
              "b/0": {f: (-6 + 0.15 * f, -3.0) for f in range(40)},  # 6 m along the pavement
              "c/0": {f: (8.0, 0.01 * (f % 3)) for f in range(40)}}  # waits in one spot
    paths = road.crossing_paths(people, {"car#1": car}, fps)
    assert list(paths) == ["a"] and len(paths["a"]) == 2  # one person, both pieces; the pavement walk is not a crossing
    assert paths["a"][0][:2] == [[0.0, -3.0], [0.0, -2.2]] and len(paths["a"][0]) == 8  # a point every 0.5 s
    assert set(road.crossing_paths(people, {}, fps)) == {"a", "b"}  # no vehicle, no road axis: every crossing stays
    tilt = lambda deg: {f: tuple((x * math.cos(math.radians(deg)), x * math.sin(math.radians(deg))) for x, _ in e)
                        for f, e in car.items()}
    axis = road.road_axis({"car#1": tilt(1), "car#2": tilt(-1)}, fps)  # headings 1 and 179 degrees: the road is x
    assert abs(axis[1]) < 1e-9 and abs(abs(axis[0]) - 1) < 1e-9
    with tempfile.TemporaryDirectory() as folder:  # analyze keeps the paths apart from the facts' exposure
        analyze.write_events(Path(folder), {}, [], {"minutes": 1}, None, None, paths=DESIRE)
        assert json.loads((Path(folder) / "events.json").read_text())["paths"] == DESIRE


def test_desire_lines_count_crossings_against_the_zebra_or_the_gate():
    import roadmap
    zebra, gate = [[8.6, -3.0], [11.2, -3.0], [11.2, 3.0], [8.6, 3.0]], [[-1.0, -3.5], [1.0, -3.5]]
    lines = roadmap.desire_lines(DESIRE, {})
    assert lines[0] == ("Where people crossed: 4 people walked 2 m or more, mostly across the road; 3 of them within "
                        "the busiest 2 m stretch of road.")
    assert len(lines) == 2 and "6.1.9.2 (iii)" in lines[1] and "shortest possible direct route" in lines[1]
    assert "3 of 4 (75%) crossed more than 2 m outside the marked crossing." in roadmap.desire_lines(DESIRE, {"zebra_m": zebra})
    assert "No marked crossing; 3 of 4 crossed straight out of the gate" in roadmap.desire_lines(
        DESIRE, {"zebra_m": [], "gate_m": gate})[1]
    assert len(roadmap.desire_lines(DESIRE, {"gate_m": gate})) == 2  # a zebra not stated either way: no claim
    assert roadmap.desire_lines(None, {}) == [] and roadmap.desire_lines({}, {}) == []
    text = pack.facts({"name": "gate", "zebra_m": zebra}, [], {"minutes": 1}, DESIRE)
    assert '"desire_lines": "Where people crossed: 4 people' in text and "(75%)" in text
    assert pack.unmeasured("9.4 1.7 3.7 3.9", text) == ["1.7", "3.7", "3.9", "9.4"]  # never the paths' coordinates
    svg = roadmap.svg([], SQUARE_ROAD, paths=DESIRE)
    assert svg.count('class="trail"') == 4 and roadmap.extent([], SQUARE_ROAD, DESIRE) == (-2.0, -5.7, 12.0, 12.0)
    section = pack.map_section([], {"world_points": SQUARE_ROAD, "zebra_m": zebra}, paths=DESIRE)
    assert "Where people crossed" in section and "Faint blue" in section and "(75%)" in section


def test_a_clip_without_near_misses_still_gets_its_letter_from_the_desire_lines():
    import contextlib, io, sys, tempfile
    from pathlib import Path
    plan = {"fix": "raised zebra", "why": "w", "image_prompt": "i", "letter": "3 of 4.", "writer": "Muse Spark"}
    asked = []
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder)
        (out / "site.json").write_text(json.dumps({"name": "gate", "world_points": SQUARE_ROAD}))
        old = sys.argv, pack.optional_key, pack.street_photo, pack.ask_plan
        sys.argv = ["pack.py", folder, str(out / "site.json")]
        pack.optional_key, pack.street_photo = lambda: None, lambda *args: None  # no key, no network, no photo
        pack.ask_plan = lambda prompt, measured, key, photo, stated=(): asked.append(measured) or plan
        try:
            for paths in ({}, DESIRE):
                (out / "events.json").write_text(json.dumps({"fps": 10, "exposure": {"minutes": 0.3}, "events": [],
                                                             "paths": paths}))
                with contextlib.redirect_stdout(io.StringIO()):
                    pack.main()
                assert (out / "plan.json").exists() == bool(paths)  # nobody crossed: nothing to write a letter on
        finally:
            sys.argv, pack.optional_key, pack.street_photo, pack.ask_plan = old
        page = (out / "index.html").read_text()
        assert len(asked) == 1 and "desire_lines" in asked[0] and "Where people crossed" in page and "raised zebra" in page


def test_sam_text_parses_into_tracks():
    text = ("<0f>0<|box;x1=1.0;y1=2.0;x2=3.0;y2=4.0;w=640;h=360|><|mask...|>1<|box;x1=5;y1=6;x2=7;y2=8;w=640;h=360|>"
            "<1f>0<|box;x1=1.5;y1=2.5;x2=3.5;y2=4.5;w=640;h=360|>")
    assert sam.parse(text) == {"0": {0: [1.0, 2.0, 3.0, 4.0], 1: [1.5, 2.5, 3.5, 4.5]}, "1": {0: [5.0, 6.0, 7.0, 8.0]}}
    assert sam.parse("<0f>0<|box;x1=5;y1=6;x2=5;y2=8;w=640;h=360|>") == {}  # zero-width box dropped


def test_judge_bench_plants_one_lie_per_copy_and_the_code_check_misses_the_ones_without_digits():
    """Glimmer's v1 letter: 12 single-lie copies, half of kinds JUDGE_PROMPT does not name, and 4 clean controls."""
    import judge_bench
    name, letter, facts = judge_bench.glimmer_base()
    assert name == "glimmer" and letter.startswith("Dear Road Authority") and not judge_bench.code_flags(letter, facts)
    bench = judge_bench.bench_letters([(name, letter, facts)])
    planted = [i for i in bench if i["planted"]]
    assert len(planted) == 12 and sum(i["named"] for i in planted) == 6 and len(bench) == 16
    assert all(i["letter"] != letter for i in planted) and len({i["letter"] for i in bench}) == 16
    assert not any(c.isdigit() for _, _, lie in judge_bench.INSERTED for c in lie)
    caught = {i["kind"] for i in planted if judge_bench.code_flags(i["letter"], i["measured"])}
    assert caught == {"number in words", "km/h written as mph"}
    assert not any(judge_bench.code_flags(i["letter"], i["measured"]) for i in bench if not i["planted"])
    swap = next(i["letter"] for i in planted if i["kind"] == "near-misses swapped")
    assert "a car at 29.0 km/h with adult death risk if hit 3.0% and a car at 38.0 km/h" in swap


def test_judge_bench_counts_unreadable_replies_apart_and_asks_only_for_missing_runs():
    import judge_bench
    item = {"id": "x", "kind": "k", "named": True, "planted": True, "letter": "L", "measured": "{}", "code": [False]}
    replies, prompts = ['{"problems": ["a lie"]}', "no json here"], []
    def ask(prompt):
        prompts.append(prompt)
        if not replies:
            raise OSError("server down")
        return replies.pop(0)
    import contextlib, io
    with contextlib.redirect_stderr(io.StringIO()) as said:
        done = judge_bench.judged(item, "spark", ask, 3)  # the third call fails: not recorded, asked again next run
    assert "asked again next run" in said.getvalue()
    assert done["spark"] == [True, None] and "LETTER:\nL" in prompts[0] and "spark" not in item
    assert judge_bench.judged(done, "spark", ask, 2) is not done and len(prompts) == 3  # 2 runs held: no call
    assert judge_bench.tally([done], "spark") == (1, 1, 1)
    control = {**item, "id": "y", "planted": False, "spark": [False, False]}
    text = "\n".join(judge_bench.table([done, control]))
    assert "| k | yes | 0/1 | 1/1 | - | 1/1 |" in text and "Muse Spark 1 of 4 replies" in text
    assert "| **Clean controls: false alarms** |  | 0/1 (0-79%) | 0/1 (0-79%) | - | 0/1 (0-79%) |" in text
    # two runs on one letter are one trial in the bounded rows, never two
    text = "\n".join(judge_bench.table([done, {**done, "id": "z", "spark": [True, True]}, control]))
    assert "| k | yes | 0/2 | 3/3 | - | 2/2 |" in text and "| **All planted lies** |  | 0/2 (0-66%) | 2/2 (34-100%) |" in text


def test_judge_bench_takes_a_cached_spark_letter_in_todays_form_and_never_a_glimmer_one():
    import judge_bench, shutil, tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "gate"
        folder.mkdir()
        shutil.copyfile(judge_bench.HERE / "sample" / "events.json", folder / "events.json")
        plan = {"writer": pack.LETTER_MODEL, "letter": "SAM 3.1 found two serious near-misses; a car at 38.0 km/h."}
        (folder / "plan.json").write_text(json.dumps(plan))
        assert judge_bench.spark_base(Path(tmp)) is None
        (folder / "plan.json").write_text(json.dumps({**plan, "writer": "Muse Spark"}))
        _, letter, facts = judge_bench.spark_base(Path(tmp))
    assert letter == "SAM found 2 serious near-misses; a car at 38.0 km/h." and '"vehicle_kmh": 38.0' in facts


def test_blind_set_hides_near_misses_among_spark_checked_decoys_in_same_length_clips():
    import blind_set
    near = [{"person": f"{p}/0", "vehicle": "car#1", "tier": "serious", "pet_s": 0.4, "t_person_s": t, "t_vehicle_s": t + 0.4}
            for p, t in (("a", 0.5), ("b", 20.0))]
    candidates = [{"person": p, "vehicle": "car#2", "tier": "close pass", "pet_s": pet, "t_person_s": 30.0, "t_vehicle_s": 30.0 + pet}
                  for p, pet in (("pole/0", 5.1), ("c/0", 2.0), ("d/0", 7.9), ("e/0", 6.0), ("f/0", 5.5))]
    verdicts = {"pole/0": {"is_person": False}, "d/0": {"is_person": True}, "e/0": {"is_person": True}, "f/0": None}
    asked = []
    fakes = blind_set.decoys(candidates, lambda pid: (asked.append(pid), verdicts.get(pid))[1], 2, 1000)
    assert [e["person"] for e in fakes] == ["e/0", "d/0"] and "c/0" not in asked  # a near-miss is never a decoy
    for e in near + fakes:
        first, last = render.window(blind_set.blind_window(e, 1000), 10)
        assert last - first == 120 and first == max(0, round((min(e["t_person_s"], e["t_vehicle_s"]) - 2) * 10))
    # e's person nearly hit by a bus inside e's clip (on another piece): the rater would see danger, so not a decoy
    bus = {"person": "e/1", "vehicle": "bus#3", "pet_s": 1.0, "t_person_s": 39.0, "t_vehicle_s": 40.0}
    assert [e["person"] for e in blind_set.decoys(candidates + [bus], verdicts.get, 2, 1000)] == ["d/0"]
    later = {**bus, "t_person_s": 45.0, "t_vehicle_s": 46.0}  # after e's clip ends at 40.0 s
    assert [e["person"] for e in blind_set.decoys(candidates + [later], verdicts.get, 2, 1000)] == ["e/0", "d/0"]
    # near the end of a 39 s video the clip starts earlier and still ends on its last frame, 121 frames long
    end = {**near[0], "t_person_s": 30.8, "t_vehicle_s": 31.2}
    assert render.window(blind_set.blind_window(end, 390), 10) == (269, 389) and exits(
        lambda: blind_set.blind_window(end, 120))  # a video shorter than a clip stops the run
    import analyze, subprocess, tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        clip, cut = Path(tmp) / "clip.mp4", Path(tmp) / "cut.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10:duration=13",
                        "-pix_fmt", "yuv420p", str(clip)], check=True)
        render.render(clip, blind_set.blind_window({**end, "t_person_s": 12.5, "t_vehicle_s": 12.9}, 130), {}, {}, 10, cut)
        assert analyze.frame_count(cut) == 121
    clips = blind_set.shuffled(near, fakes)
    assert clips == blind_set.shuffled(near, fakes) and [c[0] for c in clips] == [f"clip0{k}.mp4" for k in range(1, 5)]
    key = blind_set.key_record(clips)
    assert sorted(c["truth"] for c in key["clips"]) == ["decoy", "decoy", "serious", "serious"]
    page = blind_set.page([c[0] for c in clips])
    assert page.count('type="radio"') == 16 and "new Blob" in page and "localStorage" in page
    assert not any(word in page for word in ("decoy", "pet_s", "car#", "e/0"))  # nothing on the page gives a clip away



def test_blind_set_rebuilds_tracks_from_cache_with_auto_modes_switch():
    """blind_set's tracks are analyze's: concept_tracks gives (tracks, detected), and an auto-mode concept that
    filled its SAM video requests is read frame by frame, as analyze.py read it. A full people video request left
    alone stops it: those faces have no track to blur."""
    import analyze, blind_set
    from pathlib import Path
    site = {"person": "person", "vehicles": ["car"], "image_points": SQUARE_IMG, "world_points": SQUARE_ROAD}
    calls, saved = [], {n: getattr(analyze, n) for n in ("probe", "frame_count", "parts", "auto_switch",
                                                         "concept_tracks", "road_tracks", "full_requests")}
    try:
        analyze.probe, analyze.frame_count, analyze.parts = (lambda *a: "64,48"), (lambda clip: 50), (lambda *a: [])
        analyze.auto_switch = lambda *a: {"person": 1.6}
        analyze.full_requests = lambda *a: (1, 4)  # full, but auto mode switched people to frame by frame
        analyze.concept_tracks = lambda site, concept, *a: (calls.append((concept, a[-1])) or
                                                             ({0: {1: [0, 0, 1, 1]}}, {0: {1: [0, 0, 1, 1]}}))
        analyze.road_tracks = lambda site, H, people, vehicles, size: ({"0/0": people[0]}, vehicles)
        people, vehicles, pieces, shapes, size, total = blind_set.load_tracks(site, Path("x"))
        analyze.auto_switch = lambda *a: {}  # people left in video mode with a full request
        try:
            blind_set.load_tracks(site, Path("x"))
            raise AssertionError("a full people request was not refused")
        except SystemExit as err:
            assert "16-object limit" in str(err) and '"person_mode": "crowd"' in str(err)
        blind_set.load_tracks({**site, "person_mode": "crowd"}, Path("x"))  # crowd mode: every frame searched
    finally:
        for n, f in saved.items():
            setattr(analyze, n, f)
    assert people == {0: {1: [0, 0, 1, 1]}} and vehicles == {"car#0": {1: [0, 0, 1, 1]}} and (size, total) == ((64, 48), 50)
    assert calls[:2] == [("person", {"person": 1.6}), ("car", {"person": 1.6})]
    assert "the faces SAM found are\nblurred" in blind_set.page(["clip01.mp4"])  # never "faces are blurred"

def test_score_humans_scores_danger_against_none_with_kappa_and_wilson():
    import score_humans, tempfile
    from pathlib import Path
    assert score_humans.kappa(20, 5, 10, 15) == 0.3999999999999999 and score_humans.kappa(5, 0, 0, 0) is None
    lo, hi = score_humans.wilson(0, 10)
    assert lo == 0 and abs(hi - 0.2775) < 1e-4 and abs(score_humans.wilson(20, 24)[0] - 0.6415) < 1e-4
    truth = {f"clip{k:02d}.mp4": k <= 6 for k in range(1, 13)}  # 6 near-misses, 6 decoys
    said = {**{c: "serious" for c, d in truth.items() if d}, **{c: "none" for c, d in truth.items() if not d},
            "clip01.mp4": "close", "clip07.mp4": "close", "clip12.mp4": "cant_tell"}
    with tempfile.TemporaryDirectory() as tmp:
        good, bad = Path(tmp) / "good.json", Path(tmp) / "bad.json"
        good.write_text(json.dumps({"rater": "A. Rao, lecturer", "answers": said}))
        rater, read = score_humans.read_answers(good, truth)
        for wrong in ({"answers": {"clip99.mp4": "none"}}, {"answers": {"clip01.mp4": ["none"]}}, "not json {"):
            bad.write_text(wrong if isinstance(wrong, str) else json.dumps(wrong))
            assert exits(lambda: score_humans.read_answers(bad, truth))
    assert rater == "A. Rao, lecturer" and read["clip12.mp4"] is None and score_humans.table(truth, read) == (6, 1, 0, 4, 1)
    lines = score_humans.report(rater, truth, read)
    assert "Agreed with the pipeline on 10 of 11" in lines[1] and "kappa 0.81" in lines[1] and lines[-1].endswith("PASS")
    assert "NOT DECIDABLE" in score_humans.report(rater, dict(list(truth.items())[3:9]), read)[-1]



def test_judge_bench_asks_glimmer_through_judge_model_url_with_the_problems_schema():
    """The Kaggle cell sets only JUDGE_MODEL_URL; the bench's Glimmer column must reach that server, held to the
    judge's schema, and read the reply's text."""
    import judge_bench
    calls, old = [], (pack.open_model_reply, pack.JUDGE_URL, pack.LETTER_URL)
    pack.open_model_reply = lambda prompt, image, schema, judge=False: (calls.append((schema, judge)), ('{"problems": []}', {}))[1]
    pack.JUDGE_URL, pack.LETTER_URL = "http://127.0.0.1:8080/v1", ""
    try:
        reply = judge_bench.asker("glimmer")("JUDGE")
        pack.JUDGE_URL = ""
        assert exits(lambda: judge_bench.asker("glimmer"))  # no server named: no Glimmer column
    finally:
        pack.open_model_reply, pack.JUDGE_URL, pack.LETTER_URL = old
    assert reply == '{"problems": []}' and calls == [(pack.PROBLEMS_SCHEMA, True)]  # the judge server, its own model

def agent_case(folder):
    """A case folder for the agent: one measured near-miss, and a site whose check distance reads 7.0 m in the video."""
    from pathlib import Path
    out = Path(folder)
    e = {"person": "1/0", "vehicle": "car#1", "tier": "serious", "pet_s": 0.5, "vehicle_kmh": 30.0, "death_risk_pct": 1.5,
         "t_person_s": 3.0, "t_vehicle_s": 3.5, "gap_m": 0.4, "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5},
                                                                         "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    (out / "events.json").write_text(json.dumps({"fps": 10, "exposure": {"minutes": 0.3}, "events": [e]}))
    site = {"name": "gate", "image_points": SQUARE_IMG, "world_points": SQUARE_ROAD, "vehicles": ["car"],
            "check": {"what": "line A to line B along the near kerb", "points": [[100, 200], [240, 200]]}}  # 140 px at 20 px/m
    (out / "site.json").write_text(json.dumps(site))
    return out, site, e


def scripted_spark(script, bodies):
    """A fake Muse Spark: each turn calls the next scripted (tool, arguments), or answers in plain text for None."""
    def turn(body, key):
        bodies.append(json.loads(json.dumps(body)))  # a copy: the agent keeps adding to its messages
        step = script.pop(0)
        said = ({"type": "function_call", "call_id": f"call-{len(bodies)}", "name": step[0], "arguments": json.dumps(step[1])}
                if step else {"type": "message", "content": [{"type": "output_text", "text": "Done."}]})
        return {"output": [{"type": "reasoning", "id": "rs_1", "summary": []}, said],
                "usage": {"input_tokens": 2000, "output_tokens": 100}}
    return turn


def test_case_agent_stops_for_a_tape_measure_and_files_the_letter_only_when_it_agrees():
    """The workshop's loop with a scripted Muse Spark (no network): one tool per turn, plain text sent back, SAM's
    16-object limit switching people to crowd mode, three refused letters escalating to a person, a stop for a tape
    measure, resume with the answer, notes from the head, the sign-off, and the page section."""
    import agent, contextlib, io, re, seal, tempfile
    submit = ("submit_letter", {"notes": ""})
    script = [("track", {"people": "video", "vehicles": "video"}), ("track", {"people": "crowd", "vehicles": "video"}),
              None, submit, submit, submit, ("measure", {}), ("request_measurement", {}), submit,
              ("submit_letter", {"notes": "Name the school gate."})]
    bodies, tracked, prompts = [], [], []
    plan = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "PET 0.5 s.", "writer": "Muse Spark",
            "tries": 1}
    def tracker(p, site):
        tracked.append(site["person_mode"])
        return {"car": [0, 1]} if site["person_mode"] == "crowd" else {"person": [3, 3], "car": [0, 1]}
    old = agent.spark_turn, agent.run_tracker, pack.ask_plan
    agent.spark_turn, agent.run_tracker = scripted_spark(script, bodies), tracker
    pack.ask_plan = lambda prompt, measured, key, photo: prompts.append(prompt) or plan
    try:
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            out, site, e = agent_case(folder)
            run = lambda **person: agent.work(out / "video.mp4", out / "site.json", out, "key", **person)
            assert run() == "needs_input" and tracked == ["video", "crowd"]  # 3 refusals: R1 asks a person
            assert raises_system_exit(run)  # waiting for the answer: no model call
            assert run(answer=("R1", "Ask for the tape first.")) == "needs_input"  # measure, then R2 asks for the tape
            assert raises_system_exit(lambda: run(answer=("R2", "about a car length")))
            assert run(answer=("R2", "7.2 m")) == "needs_review"
            assert run(notes="Name the school gate.") == "needs_review" and "Name the school gate." in prompts[-1]
            assert run(approve=("A. Rao, Principal", "LNCT")) == "done"
            assert raises_system_exit(lambda: run(approve=("A. Rao, Principal", "LNCT")))  # signed once
            (out / "index.html").unlink()
            assert run() == "done"  # a page fix after sign-off: the page and share/ written again, no turn
            progress = json.loads((out / "case" / "progress.json").read_text())
            log = (out / "case" / "agent_log.jsonl").read_text().splitlines()
            page = (out / "index.html").read_text()
            shared = sorted(f.name for f in (out / "share").iterdir())
            sealed = seal.verify(out / "share")
    finally:
        agent.spark_turn, agent.run_tracker, pack.ask_plan = old
    assert script == [] and len(bodies) == progress["turn"] == 10 and len(log) == 14  # 10 turns, 4 person steps
    assert all(b["parallel_tool_calls"] is False and b["store"] is False for b in bodies)
    assert {t["name"] for t in bodies[0]["tools"]} == set(agent.RUNNERS)
    assert "Start with the modes the case names" in bodies[0]["instructions"]
    assert 'names people "video" and vehicles "video" for tracking' in bodies[0]["input"][0]["content"]  # the site's
    assert bodies[3]["input"][-1] == {"role": "user", "content": agent.NUDGE}
    assert not any(item.get("type") == "reasoning" for b in bodies for item in b["input"])
    assert [r["kind"] for r in progress["requests"]] == ["letter_refused", "measurement"] and progress["tape_m"] == 7.2
    assert abs(progress["usd"] - 10 * (2000 * 1.25 + 100 * 4.25) / 1e6) < 1e-9
    assert '"tape_m": 7.2' in prompts[0] and '"video_m": 7.0' in prompts[0]  # measured, so the letter may quote it
    assert "How the agent worked this case" in page and "Video 7.0 m, tape 7.2 m, 3% off: proven" in page
    assert "Person: R2 answered: 7.2 m" in page and "Person: A. Rao, Principal, LNCT, approved the letter." in page
    assert "Read and approved by: A. Rao, Principal, LNCT, " in page and "____" not in page
    assert "0 of 1 sentences changed after the principal&#x27;s notes" in page  # the head sent it back once
    assert "Receipt: " in page and "Muse Spark wrote the letter in 1 try" in page
    assert shared == ["SHA256SUMS", "index.html"] and sealed == {"index.html": "MATCH"}
    assert len(re.findall(r"<li>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d\d:\d\d ", page)) == 14  # every step timed
    known = re.search(r'data-measured="([^"]*)"', page)[1].split()
    assert {"7.2", "7.0", "3"} <= set(known)  # the tape check the letter may quote passes the in-browser check
    assert "off" in agent.letter_blocker({"tape_m": 9.0}, site, [e], "")  # 22% off: mark the calibration again
    assert "numbers" in agent.letter_blocker({"tape_m": 7.2, "tracked_with": agent.calibration(site)}, site, [e], "3")
    assert agent.tape_metres("720 cm") == agent.tape_metres(" 7.2M ") == 7.2
    assert all(raises_system_exit(lambda t=t: agent.tape_metres(t))
               for t in ("7 ft", "24 feet", "7,2 m", "1,200 cm", "2 m 20 cm", "720", "7.2 mm"))  # never read as metres



def test_case_agent_page_is_the_pack_page_with_its_privacy_note_and_gap_barcode():
    import agent, tempfile
    with tempfile.TemporaryDirectory() as folder:
        out, site, e = agent_case(folder)
        data = json.loads((out / "events.json").read_text())
        data |= {"privacy": {"heads_tracked": 4, "heads_found": 2}, "timeline": {"duration_s": 18.0, "busy_s": [[2.0, 3.0]]}}
        (out / "events.json").write_text(json.dumps(data))
        agent.write_page({"site": str(out / "site.json"), "out": str(out), "letter": None})
        page = (out / "index.html").read_text()
    assert "up to 2 found by SAM image search" in page and "Gaps in traffic" in page


def test_case_agent_page_names_the_tracks_spark_removed():
    """The agent's page gets pack's note on the tracks Spark's review removed, from events.json's unfiltered events
    (the page's cards show only the kept ones), with no digit-bearing reason."""
    import agent, html, tempfile
    with tempfile.TemporaryDirectory() as folder:
        out, site, e = agent_case(folder)
        pole = {**e, "person": "2/0", "review": {"is_person": False, "road_user": "not a person", "reason": "a pole"}}
        plate = {**e, "person": "3/0", "review": {"is_person": False, "road_user": "rider", "reason": "plate MP04 AB"}}
        data = {"fps": 10, "exposure": {"minutes": 0.3}, "events": [e, pole, plate]}
        (out / "events.json").write_text(json.dumps(data))
        agent.write_page({"site": str(out / "site.json"), "out": str(out), "letter": None})
        page = (out / "index.html").read_text()
    note = 'Removed by Muse Spark: 2 tracks (track 2/0, not a person ("a pole"); track 3/0, rider). Spark can be wrong.'
    assert html.escape(note) in page and "MP04" not in page


def test_case_agent_sign_off_draws_the_fix_in_the_measured_band_once():
    """--approve: Muse Image (stubbed) draws only inside the measured band, as pack.main does, the share/ folder holds
    the band picture under SHA256SUMS, and writing the page again after sign-off pays for no new picture."""
    import agent, contextlib, io, seal, subprocess, tempfile
    calls, old = [], (pack.draw_fix, pack.photo_people)

    def muse_image(image, words, key, path):
        calls.append(words)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(image), "-f", "image2", "-c:v", "png", str(path)],
                       check=True)
        return path

    pack.draw_fix, pack.photo_people = muse_image, lambda clip, concept="person": []
    try:
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            out, site, e = agent_case(folder)
            walked = {**e, "where": [3.0, 5.0], "path_person": [[3.0, 1.0], [3.0, 9.0]]}  # road metres
            (out / "events.json").write_text(json.dumps({"fps": 10, "exposure": {"minutes": 0.3}, "events": [walked]}))
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=400x400", "-frames:v", "1",
                            str(out / "street.jpg")], check=True)
            (out / "case").mkdir()
            letter = {"fix": "a speed table", "why": "w", "image_prompt": "i", "letter": "PET 0.5 s.",
                      "writer": "Muse Spark"}
            p = {"out": str(out), "site": str(out / "site.json"), "status": "needs_review", "letter": letter,
                 "requests": []}
            assert agent.person_step(p, "key", approve=("A. Rao, Principal", "LNCT")) is None and p["status"] == "done"
            drawn = len(calls)
            assert agent.person_step(p, "key") is None and len(calls) == drawn == 1  # the page again, no new picture
            page = (out / "index.html").read_text()
            shared = sorted(f.name for f in (out / "share").iterdir())
            sealed = seal.verify(out / "share")
    finally:
        pack.draw_fix, pack.photo_people = old
    assert "magenta band" in calls[0] and "Where the fix goes" in page and 'src="street-band.svg"' in page
    assert "Read and approved by: A. Rao, Principal, LNCT, " in page and "as drafted, no notes" in page
    assert shared == ["SHA256SUMS", "index.html", "street-band.svg", "street-dots.svg", "street-fixed.webp"]
    assert set(sealed.values()) == {"MATCH"} and len(sealed) == 4

def test_case_agent_refuses_a_letter_tracked_before_the_calibration_points_were_marked_again():
    """The check distance is re-read from the site file, but the near-misses come from the last track: after the
    points are marked again the check agrees with the tape, yet the letter waits for a new track."""
    import agent, contextlib, io, tempfile
    old = agent.run_tracker, pack.ask_plan
    agent.run_tracker = lambda p, site: {}
    pack.ask_plan = lambda prompt, measured, key, photo: {"fix": "f", "letter": "l", "writer": "w"}  # never the network
    try:
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            out, site, e = agent_case(folder)
            p = {"out": str(out), "site": str(out / "site.json"), "tape_m": 7.2, "refusals": 0}
            letter = lambda: agent.submit_letter(p, {"notes": ""}, "key")["summary"]
            assert "call track" in letter()  # events.json from a run outside this case: not proven
            agent.track(p, {"people": "video", "vehicles": "video"}, "key")
            assert agent.letter_blocker(p, agent.case_site(p), [e], "") == ""
            moved = {**site, "image_points": [[x + 5, y] for x, y in SQUARE_IMG]}  # still reads 7.0 m
            (out / "site.json").write_text(json.dumps(moved))
            assert "call track" in letter() and p["refusals"] == 2
            agent.track(p, {"people": "video", "vehicles": "video"}, "key")
            assert agent.letter_blocker(p, agent.case_site(p), [e], "") == ""
    finally:
        agent.run_tracker, pack.ask_plan = old


def test_case_agent_stops_at_its_turn_and_dollar_caps():
    import agent, contextlib, io, tempfile
    bodies = []
    old = agent.spark_turn, agent.MAX_TURNS, agent.MAX_USD
    agent.spark_turn, agent.MAX_TURNS = scripted_spark([None] * 3, bodies), 3
    try:
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            out, _, _ = agent_case(folder)
            run = lambda: agent.work(out / "video.mp4", out / "site.json", out, "key")
            assert run() == "paused" and len(bodies) == 3
            agent.MAX_USD, agent.spark_turn = 0.01, scripted_spark([None], bodies)  # a turn costs $0.0029
            assert run() == "over_budget" and len(bodies) == 4 and raises_system_exit(run)
    finally:
        agent.spark_turn, agent.MAX_TURNS, agent.MAX_USD = old


def test_case_agent_tracks_from_the_sam_cache_only():
    """The agent's track tool runs analyze.py with --budget 0, so a request SAM has not answered before stops the run
    with its cost, which goes back to the model, instead of paying."""
    import agent, subprocess, tempfile
    calls, old = [], agent.subprocess.run
    agent.subprocess.run = lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 1, stderr="over")
    try:
        with tempfile.TemporaryDirectory() as folder:
            out, site, _ = agent_case(folder)
            (out / "case").mkdir()
            p = {"out": str(out), "video": str(out / "video.mp4")}
            assert raises_value_error(lambda: agent.run_tracker(p, {**site, "person_mode": "crowd", "vehicle_mode": "video"}))
    finally:
        agent.subprocess.run = old
    assert calls[0][-2:] == ["--budget", "0"] and calls[0][1].endswith("analyze.py")


def test_case_agent_never_replaces_a_signed_letter_silently():
    """A folder where pack.py signed a letter: a new case there stops before any model call or write, since its
    tracking rewrites events.json and its letter plan.json. A letter the case replaces itself (one the head sent
    back) is kept as plan-<sha8>.json, as pack's are."""
    import agent, contextlib, hashlib, io, tempfile
    bodies, old = [], (agent.spark_turn, pack.ask_plan)
    agent.spark_turn = scripted_spark([], bodies)
    pack.ask_plan = lambda prompt, measured, key, photo: {"fix": "f", "letter": "Revised.", "writer": "Muse Spark"}
    plan = {"fix": "f", "letter": "Signed text.", "writer": "Muse Spark"}
    try:
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            out, site, _ = agent_case(folder)
            (out / "plan.json").write_text(json.dumps(plan))
            pack.sign(out, plan, "A. Rao, Principal", "Gate School")
            message = stopped(lambda: agent.work(out / "video.mp4", out / "site.json", out, "key"))
            untouched = not (out / "case").exists() and json.loads((out / "plan.json").read_text()) == plan
            (out / "signoff.json").unlink()  # unsigned: the case's own draft, revised after the head's notes
            p = {"out": str(out), "site": str(out / "site.json"), "tape_m": 7.2, "refusals": 0, "letter": plan,
                 "tracked_with": agent.calibration(site)}
            agent.submit_letter(p, {"notes": ""}, "key")
            kept = json.loads((out / f"plan-{hashlib.sha256(b'Signed text.').hexdigest()[:8]}.json").read_text())
            now = json.loads((out / "plan.json").read_text())
    finally:
        agent.spark_turn, pack.ask_plan = old
    assert "A. Rao, Principal signed" in message and "--out" in message and bodies == [] and untouched
    assert kept == plan and now["letter"] == "Revised."


def test_guesses_keep_5_to_150_kmh_and_the_chart_draws_the_measured_speed_in_red():
    import contextlib, guess, io, sys, tempfile
    from pathlib import Path
    replies = "40 🏍️\n@ravi99 about 25 km/h\nlol no way\n2\n500 kmph\n30-35\n\n150\n४५\n"
    assert guess.guesses(replies) == [40, 25, 30, 150, 45]  # handle, joke, 2, 500 and the blank line dropped
    chart = guess.svg([40, 25, 30, 150, 45], 34.0)
    x = f"{guess.LEFT_PX + 34 / guess.MAX_KMH * (guess.WIDTH_PX - guess.LEFT_PX - guess.RIGHT_PX):.1f}"
    assert f'<line class="measured" x1="{x}"' in chart and f'x2="{x}"' in chart and guess.RED in chart
    assert chart.count('<rect class="bar"') == 4 and "median 40 km/h" in chart  # 40 and 45 share one; 150 is in 140-150
    edge = f'x1="{guess.WIDTH_PX - guess.RIGHT_PX:.1f}"'
    assert edge in guess.svg([5], 200.0).split('class="measured"')[1]  # a pass over 150 km/h widens the axis
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder)
        (out / "replies.txt").write_text(replies, encoding="utf-8")
        rejected = {"person": "7/0", "vehicle_kmh": 61.0, "review": {"is_person": False}}  # Spark: a pole
        pole = [rejected, {"person": "7/0", "vehicle_kmh": 50.0}]  # its unreviewed pairing goes too
        cards = [{"person": "3/0", "vehicle_kmh": 87.9}, {"person": "4/0", "vehicle_kmh": 34.0}]
        (out / "events.json").write_text(json.dumps({"events": pole[:1] + cards[:1] + pole[1:] + cards[1:]}))
        (out / "jokes.txt").write_text("lol\n2\n500\n")
        old = sys.argv
        try:
            sys.argv = ["guess.py", str(out / "replies.txt"), str(out / "events.json"), "--event", "2"]
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                guess.main()
            assert "5 guesses, median 40 km/h. Measured: 34 km/h." in printed.getvalue()
            assert (out / "guess.svg").read_text() == chart
            sys.argv[-1] = "1"
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                guess.main()
            assert "Measured: 87.9 km/h." in printed.getvalue()  # card #1 is the first event Spark did not reject
            sys.argv[-1] = "3"
            assert raises_system_exit(guess.main)  # the pole's two events are no cards, so there is no card #3
            many = [{"person": f"{i}/0", "vehicle_kmh": 30.0} for i in range(pack.SHOWN_EVENTS + 1)]
            (out / "events.json").write_text(json.dumps({"events": many}))
            sys.argv[-1] = str(pack.SHOWN_EVENTS + 1)
            assert raises_system_exit(guess.main)  # the page shows only SHOWN_EVENTS cards
            sys.argv[1:] = [str(out / "jokes.txt"), str(out / "events.json")]
            assert raises_system_exit(guess.main)  # no guesses at all
        finally:
            sys.argv = old



def walkers(count, mps, seconds=10, fps=10):
    """`count` pedestrian pieces, as analyze.road_tracks makes them, each walking straight across at `mps`."""
    return {f"{i}/0": {f: (mps * f / fps, 3.0 * i) for f in range(seconds * fps)} for i in range(count)}


def test_people_walking_too_fast_or_slow_flag_the_video_and_no_letter_is_asked_for():
    """A time-lapse (or a scale too large) makes people walk too fast: events.json says so, the page shows the warning
    instead of the headline and near-miss counts, and pack asks no model for a letter, nor the case agent."""
    import agent, analyze, pace, tempfile
    fast, slow = pace.walking(walkers(pace.MIN_PIECES, 3.0), 10), pace.walking(walkers(pace.MIN_PIECES, 0.3), 10)
    assert fast == {"median_mps": 3.0, "pieces": pace.MIN_PIECES, "flag": "fast"} and slow["flag"] == "slow"
    assert "3.0 m/s (the median of 10 walking pieces), about 2.3 times a normal walking pace of 1.3 m/s" in (
        pace.warning(fast)) and "slowed down" in pace.warning(slow)
    with tempfile.TemporaryDirectory() as folder:
        out = pack_folder(folder)
        data = json.loads((out / "events.json").read_text())
        analyze.write_events(out, {}, data["events"], data["exposure"], None, None, walking=fast)
        assert run_pack(out, ask=lambda prompt: 1 / 0, key="key") == [] and not (out / "plan.json").exists()
        page = (out / "index.html").read_text()
        assert "this video looks sped up or the calibration is off" in page and "No letter was asked for." in page
        assert "serious near-misses" not in page and "Worst moments" not in page and "pedestrian crossings" in page
        assert "tracked moment &middot; car and a pedestrian" in page and "At 3.0 s in the video." in page
        assert not any(n in page for n in ("30.0 km/h", "0.5 s from", "Adult death risk", "Gap 0.4 m", "serious &"))
        assert "walk at 3.0 m/s" in agent.letter_blocker({}, {}, data["events"], "", fast)
    placed = [{"where": [5.0, 3.0], "tier": "serious", "vehicle": "car#1", "vehicle_kmh": 30.0, "pet_s": 0.5}]
    shown, flagged = (pack.map_section(placed, {"world_points": SQUARE_ROAD}, measured=m) for m in (True, False))
    assert "Filled dots" in shown and "30.0 km/h" in shown and 'class="hit"' in shown
    assert "Filled dots" not in flagged and "km/h" not in flagged and 'class="hit"' not in flagged


def test_a_site_marked_not_measurements_gets_no_letter_whatever_its_walkers_show():
    """The Indian time-lapse's site file says so: an events.json from before pace.py (no "walking") or with too few
    walkers to judge still gets the warning, no letter and no paid call, from pack and the case agent."""
    import agent, pace, tempfile
    from pathlib import Path
    site = json.loads((Path(__file__).parent / "sites" / "indian-intersection.json").read_text())
    few = pace.walking(walkers(pace.MIN_PIECES - 1, 1.3), 10)
    assert pace.warning(None) == pace.warning(few) == "" and "time-lapse" in pace.warning(None, site)
    assert pace.warning(few, site) == pace.warning(None, site) and "time-lapse" in agent.letter_blocker({}, site, [1], "")
    with tempfile.TemporaryDirectory() as folder:
        out = pack_folder(folder)
        (out / "site.json").write_text(json.dumps({**json.loads((out / "site.json").read_text()),
                                                   "not_measurements": "This clip is a time-lapse"}))
        assert run_pack(out, ask=lambda prompt: 1 / 0, key="key") == [] and not (out / "plan.json").exists()
        page = (out / "index.html").read_text()
        assert "This clip is a time-lapse: its speeds, near-miss times and gaps are not trusted." in page
        assert "30.0 km/h" not in page and "Worst moments" not in page


def test_people_walking_normally_leave_the_numbers_and_the_page_unchanged():
    import pace, tempfile
    walk = pace.walking(walkers(pace.MIN_PIECES, 1.3), 10)
    assert walk == {"median_mps": 1.3, "pieces": pace.MIN_PIECES, "flag": None} and pace.warning(walk) == ""
    with tempfile.TemporaryDirectory() as folder:
        events = json.loads((pack_folder(folder) / "events.json").read_text())["events"]
    seen = {"minutes": 0.5, "crossings": 3, "vehicles": 2, "speed_85th_kmh": 30.0, "crossers": ["1", "2", "3"]}
    site = {"world_points": SQUARE_ROAD}
    page = pack.page(site, events, seen, None, None, 10, walking=walk)
    assert page == pack.page(site, events, seen, None, None, 10) and "Worst moments" in page and "1 of 3" in page


def test_too_few_walking_pieces_are_not_judged():
    """Fewer than pace.MIN_PIECES people crossed (the Indian time-lapse in SAM video mode kept none): their pace is
    reported, never judged."""
    import pace
    assert pace.walking(walkers(pace.MIN_PIECES - 1, 3.0), 10) == {"median_mps": 3.0, "pieces": pace.MIN_PIECES - 1,
                                                                   "flag": None}
    standing = {"1/0": {f: (0.0, 0.0) for f in range(100)}}  # a piece that never crossed is not a walker
    assert pace.walking(standing, 10) == {"median_mps": None, "pieces": 0, "flag": None}


def test_a_dropped_request_is_sent_again_and_a_refusal_is_not():
    """sam.fetch: a wifi drop or a 503 is sent again (after the server's Retry-After when longer), a 401 never; a
    reply is written whole under its name, and a cached one is never sent again."""
    import tempfile, time, urllib.error
    from pathlib import Path
    waits, real_sleep, real_waits = [], time.sleep, sam.RETRY_WAITS_S
    time.sleep, sam.RETRY_WAITS_S = waits.append, (10, 30, 90)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def flaky():
                calls.append(1)
                if len(calls) == 1:
                    raise urllib.error.URLError("wifi dropped")
                if len(calls) == 2:
                    raise RuntimeError("SAM busy") from urllib.error.HTTPError("u", 503, "busy", {"Retry-After": "60"}, None)
                return "<0f>"
            assert sam.fetch(Path(tmp, "person.sam.txt"), flaky, "test") == "<0f>" and len(calls) == 3
            assert waits == [10, 60] and not list(Path(tmp).glob("*.part"))
            assert sam.fetch(Path(tmp, "person.sam.txt"), lambda: 1 / 0, "test") == "<0f>"  # cached: never sent again

            def refused():
                calls.append(1)
                raise RuntimeError("SAM request failed: 401") from urllib.error.HTTPError("u", 401, "no", {}, None)
            calls.clear()
            try:
                sam.fetch(Path(tmp, "car.sam.txt"), refused, "test")
                raise AssertionError("a 401 was not raised")
            except RuntimeError:
                assert len(calls) == 1 and not Path(tmp, "car.sam.txt").exists()
            def down():
                raise urllib.error.URLError("down")
            try:
                sam.fetch(Path(tmp, "bus.sam.txt"), down, "test")
                raise AssertionError("a long dropout did not end the run")
            except urllib.error.URLError:
                assert waits[-3:] == [10, 30, 90] and not Path(tmp, "bus.sam.txt").exists()
    finally:
        time.sleep, sam.RETRY_WAITS_S = real_sleep, real_waits



def test_a_moved_video_keeps_its_paid_folder_but_another_video_is_refused():
    import analyze, seal, tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        a, b, out = Path(tmp, "a.MOV"), Path(tmp, "moved.MOV"), Path(tmp, "out")
        out.mkdir()
        a.write_bytes(b"x" * 10)
        analyze.check_source(a, out, "", seal.file_sha256(a))
        a.rename(b)
        analyze.check_source(b, out, "", seal.file_sha256(b))  # same bytes, new path: accepted
        b.write_bytes(b"y" * 10)
        try:
            analyze.check_source(b, out, "", seal.file_sha256(b))
            raise AssertionError("a different video of the same size was accepted")
        except SystemExit:
            pass
        stamp = json.loads((out / "source.json").read_text())
        del stamp["sha256"]  # a folder stamped before the SHA-256 was kept
        (out / "source.json").write_text(json.dumps(stamp))
        analyze.check_source(b, out, "", seal.file_sha256(b))


def test_video_requests_go_out_together_once_and_the_auto_bill_is_shown_first():
    import analyze, tempfile, threading, time
    from pathlib import Path
    sent, lock = [], threading.Lock()

    def fake(video, concept, key):
        time.sleep(0.2)
        with lock:
            sent.append((str(video), concept))
        return "<0f>1<|box;x1=1;y1=1;x2=5;y2=9|>"
    old, sam.request = sam.request, fake
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pieces = []
            for k in range(8):
                folder = Path(tmp, f"part{k}")
                folder.mkdir()
                Path(folder, "clip.mp4").write_bytes(b"")
                pieces.append((k * 130, folder / "clip.mp4", folder))
            start = time.monotonic()
            analyze.prefetch(pieces, [("person", 1), ("car", 1)], "key", (640, 360))
            took = time.monotonic() - start
            assert len(sent) == 16 and len(set(sent)) == 16 and took < 16 * 0.2 / 2, took
            analyze.track_all(pieces, "person", "key", (640, 360))
            assert len(sent) == 16  # nothing sent twice
            site = {"vehicles": ["car"], "vehicle_mode": "auto"}
            assert analyze.auto_bill({"vehicles": ["car"]}, 600, Path(tmp), 10.0) == ""
            assert analyze.auto_bill(site, 600, Path(tmp), 10.0) == (
                "auto mode may add up to $1.50 of SAM images (car frame by frame); the run stops before sending them "
                "if they would pass the $10.00 cap")
            assert "cap" not in analyze.auto_bill(site, 600, Path(tmp), math.inf)  # --allow-cost: no "$inf cap"
    finally:
        sam.request = old



def test_window_s_prepares_only_those_seconds_of_the_recording():
    import analyze, contextlib, io, subprocess, tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp, "rec.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30", "-t", "40",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
        clip = analyze.prepare(video, Path(tmp), "", [10, 25])
        assert analyze.frame_count(clip) == 15 * analyze.FPS
        site = Path(tmp, "site.json")
        square = [[0, 0], [1, 0], [1, 1], [0, 1]]
        for bad in ([25, 10], [-1, 5], [5], "10-25"):
            site.write_text(json.dumps({"image_points": square, "world_points": square, "vehicles": ["car"],
                                        "window_s": bad}))
            try:
                analyze.load_site(site)
                raise AssertionError(f"window_s {bad} accepted")
            except SystemExit:
                pass
        site.write_text(json.dumps({"image_points": square, "world_points": square, "vehicles": ["car"],
                                    "window_s": [10, 25]}))
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            assert analyze.load_site(site)["window_s"] == [10, 25]
        assert "under 15 minutes" in printed.getvalue()  # the page will give no hourly rates
        analyze.write_events(Path(tmp), {}, [], {"minutes": 0.3, "window_s": [10, 25]}, None, None, recording_s=40.0)
        assert json.loads(Path(tmp, "events.json").read_text())["recording_s"] == 40.0  # the page's "of a 40 s recording"
        analyze.write_events(Path(tmp), {}, [], {"minutes": 0.7}, None, None)
        assert "recording_s" not in json.loads(Path(tmp, "events.json").read_text())  # no window: events.json as before


def stopped(call):
    """The message of the SystemExit `call` raises, or None."""
    try:
        call()
    except SystemExit as stop:
        return str(stop)
    return None


def test_a_signed_letter_is_never_replaced_by_a_rerun_from_other_measurements():
    """Signed, then a fact or the writer changes: the re-run asks no model, writes nothing and exits; --new-letter
    pays for a new letter and keeps the signed one as plan-<sha8>.json, and the page says it is not signed."""
    import hashlib, tempfile
    draft = {"fix": "speed table", "why": "w", "image_prompt": "i", "writer": pack.WRITER, "letter": "Signed text."}
    new = lambda prompt: {**draft, "letter": "New."}
    with tempfile.TemporaryDirectory() as folder:
        out = pack_folder(folder)
        run_pack(out, ask=lambda prompt: draft)
        run_pack(out, "--approved-by", "A. Rao, Principal", "--school", "Gate School")
        page, plan = (out / "index.html").read_text(), (out / "plan.json").read_text()
        data = json.loads((out / "events.json").read_text())
        (out / "events.json").write_text(json.dumps({**data, "exposure": {"minutes": 0.31}}))
        calls = []
        message = stopped(lambda: calls.extend(run_pack(out, ask=new, key="key")))
        assert "A. Rao, Principal signed on" in message and "other measurements" in message and calls == []
        assert (out / "plan.json").read_text() == plan and (out / "index.html").read_text() == page
        (out / "events.json").write_text(json.dumps(data))  # the same measurements, another writer
        old, pack.WRITER = pack.WRITER, "Muse Spark Open (open weights)"
        try:
            assert "another writer" in stopped(lambda: calls.extend(run_pack(out, ask=new, key="key")))
        finally:
            pack.WRITER = old
        assert calls == [] and (out / "index.html").read_text() == page
        (out / "events.json").write_text(json.dumps({**data, "exposure": {"minutes": 0.31}}))
        assert len(run_pack(out, "--new-letter", ask=new, key="key")) == 1
        sha8 = hashlib.sha256(b"Signed text.").hexdigest()[:8]
        assert json.loads((out / f"plan-{sha8}.json").read_text())["letter"] == "Signed text."
        assert json.loads((out / "plan.json").read_text())["letter"] == "New."
        assert "not signed." in (out / "index.html").read_text()
        assert not any(f.name.startswith("plan") for f in (out / "share").iterdir())  # never published


def test_pack_never_overwrites_the_case_agents_letter_or_page():
    """agent.py's case folder: its letter comes from another prompt, so a pack.py run there would pay for a new one
    and overwrite plan.json and index.html. It stops first and says to sign with agent.py --approve."""
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        out = pack_folder(folder)
        (out / "case").mkdir()
        (out / "case" / "progress.json").write_text("{}")
        calls = []
        assert "agent.py --approve" in stopped(lambda: calls.extend(run_pack(out, ask=lambda p: 1 / 0, key="key")))
        assert calls == [] and not (out / "index.html").exists() and not (out / "plan.json").exists()


def first_screen(page):
    """The page above its jump bar."""
    return page.split('<nav class="jump"')[0]


def test_first_screen_plays_the_first_shown_clip_beside_the_counts_and_the_ask():
    """Summary first: what was filmed, the site's name, the headline, then the first shown near-miss with a clip of
    its own (eventN.mp4, the only autoplay, its strobe the poster, its card's title as caption) beside the tiles and
    the fix; a jump bar links only the sections the page has."""
    import summary
    e = {"person": "1/0", "vehicle": "car#1", "tier": "serious", "pet_s": 0.5, "vehicle_kmh": 30.0, "death_risk_pct": 1.5,
         "t_person_s": 3.0, "t_vehicle_s": 3.5, "gap_m": 0.4, "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5},
                                                                         "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    strobe = {"image": "event2-strobe.jpg", "moments": 9, "step_s": 0.5}
    events = [e, e | {"clip": "event2.mp4", "strobe": strobe, "tier": "close pass", "pet_s": 2.0}, e | {"clip": "event3.mp4"}]
    site = {"name": "Gate School", "world_points": SQUARE_ROAD, "dismissal_minutes": 20}
    seen = {"minutes": 12.5, "crossings": 40, "vehicles": 90, "speed_85th_kmh": 31.0}
    plan = {"fix": "raised zebra crossing", "why": "w", "image_prompt": "i", "letter": "Dear Sir.", "writer": "Muse Spark"}
    page = pack.page(site, events, seen, plan, ("today.svg", "street-fixed.webp", "street-band.svg"), 10)
    top = first_screen(page)
    assert "Crossing Watch &middot; near-miss evidence &middot; 12.5 minutes of video of one school dismissal" in top
    assert "<h1>Gate School</h1>" in top and page.count("autoplay") == 1 and 'class="letter"' not in top
    assert '<video src="event2.mp4" poster="event2-strobe.jpg" autoplay muted loop playsinline controls>' in top
    assert f'<a href="#event-2">{pack.card_title(2, events[1])}</a>. The car reached the pedestrian&#x27;s spot 2.0 s' in top
    assert f"<h3>{pack.card_title(2, events[1])}</h3>" in page and pack.first_clip(events[:1]) is None
    assert pack.first_clip([e | {"clip": "clip.mp4"}, *events[1:]])[0] == 2  # never the unblurred video
    assert ('<div class="serious"><b>2</b>serious near-misses (under 1.5 s)</div><div class="close"><b>1</b>close '
            'passes (1.5-3.0 s)</div><div class="watched"><b>40</b>pedestrian crossings watched</div>') in top
    assert "90 moving vehicles · 12.5 minutes of video · 31.0 km/h, 85% of vehicles at or below" in top
    assert 'src="street-band.svg"' in top and pack.fixband.CAPTION in top and "AI draft" in top
    assert '<a class="btn" href="#letter">Read the letter</a>' in top
    bar = page.split('<nav class="jump"')[1].split("</nav>")[0]
    assert [t for k, t in summary.SECTIONS if f'href="#{k}"' in bar] == ["Clips", "Map", "Fix", "Letter", "Method"]
    assert "@media print { .hero video, nav.jump { display: none; } }" in page
    whole = first_screen(pack.page({**site, "country": "IN"}, events[:1], seen, plan, ("street.jpg", "street-fixed.webp"), 10))
    assert "<video" not in whole and "dismissal" in whole and summary.AI_DRAWN in whole and 'class="ai-label"' in whole
    assert 'href="#law"' in pack.page({**site, "country": "IN"}, [], seen, None, None, 10)
    assert "school dismissal" not in first_screen(pack.page({"world_points": SQUARE_ROAD}, [], seen, None, None, 10))
    assert pack.SHOWN_FILE.findall('<video src="event2.mp4" poster="event2-strobe.jpg">') == ["event2.mp4",
                                                                                              "event2-strobe.jpg"]


def test_first_screen_says_the_school_asks_only_while_the_letter_is_the_signed_one():
    """Draft, approved, changed after sign-off, filed: the status line under the fix, and "The school asks for" only
    while signoff.json's sha256 is the letter's. Under the pace warning: no clip and no ask, only the watched counts."""
    import hashlib, pace
    plan = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "Dear Sir.", "writer": "Muse Spark"}
    signed = {"approved_by": "A. Rao, Principal", "school": "Gate School", "date": "2026-11-03",
              "letter_sha256": hashlib.sha256(b"Dear Sir.").hexdigest()}
    sent = {"to": "City Traffic Police", "channel": "CPGRAMS", "date": "2026-11-03", "reference": "REF/2026/1"}
    site, seen = {"name": "gate", "world_points": SQUARE_ROAD}, {"minutes": 1, "crossings": 3}
    top = lambda signoff=None, at=site: first_screen(pack.page(at, [], seen, plan, None, 10, signoff=signoff))
    assert "Proposed fix (AI draft)" in top() and "Draft, not yet approved." in top() and "asks for" not in top()
    assert "The school asks for" in top(signed) and "Approved by A. Rao, Principal, Gate School, 2026-11-03." in top(signed)
    stale = top({**signed, "letter_sha256": "0" * 64})
    assert "AI draft" in stale and "Changed after sign-off by A. Rao, Principal on 2026-11-03, not signed." in stale
    filed = top(signed, {**site, "submitted": sent})
    assert "The school asks for" in filed and filed.count("reference REF/2026/1") == 1 and "Approved by" not in filed
    e = {"person": "1/0", "vehicle": "car#1", "tier": "serious", "pet_s": 0.5, "vehicle_kmh": 30.0, "death_risk_pct": 1.5,
         "t_person_s": 3.0, "t_vehicle_s": 3.5, "gap_m": 0.4, "clip": "event1.mp4",
         "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5}, "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    warned = first_screen(pack.page(site, [e], seen, plan, None, 10, signoff=signed,
                                    walking=pace.walking(walkers(pace.MIN_PIECES, 3.0), 10)))
    assert "<video" not in warned and 'class="ask"' not in warned and "Not measurements." in warned
    assert "pedestrian crossings watched" in warned and "serious near-misses" not in warned and "km/h" not in warned


def test_first_screen_keeps_the_filing_line_when_the_filed_letter_changed_after_sign_off():
    """A filed pack whose letter changed after its sign-off says both: not signed, and filed with its reference."""
    import hashlib
    plan = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "Dear Sir, edited.", "writer": "Muse Spark"}
    signoff = {"approved_by": "A. Rao, Principal", "school": "Gate School", "date": "2026-11-03",
               "letter_sha256": hashlib.sha256(b"Dear Sir.").hexdigest()}
    sent = {"to": "City Traffic Police", "channel": "CPGRAMS", "date": "2026-11-03", "reference": "REF/2026/1"}
    site = {"name": "gate", "world_points": SQUARE_ROAD, "submitted": sent}
    top = first_screen(pack.page(site, [], {"minutes": 1, "crossings": 3}, plan, None, 10, signoff=signoff))
    assert "Changed after sign-off by A. Rao, Principal on 2026-11-03, not signed." in top and "AI draft" in top
    assert top.count("reference REF/2026/1") == 1 and "The school asks for" not in top


def test_case_agent_page_keeps_the_heads_notes_out():
    """A letter sent back shows on the public page without its notes, which may name a pupil or a teacher; the case
    log keeps them."""
    import agent, html, tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as folder:
        log = Path(folder) / "case" / agent.LOG
        log.parent.mkdir()
        log.write_text(json.dumps({"person": "reject", "summary": "The head of the school sent the letter back: "
                                                                 "Ravi of class 5B was nearly hit."}) + "\n")
        section = agent.case_section(folder)
    assert f"Person: {html.escape(agent.NOTES_HIDDEN)}" in section and "Ravi" not in section

def test_share_folder_holds_the_first_clips_poster_and_never_clip_mp4():
    import tempfile
    from pathlib import Path
    e = {"person": "1/0", "vehicle": "car#1", "tier": "serious", "pet_s": 0.5, "vehicle_kmh": 30.0, "death_risk_pct": 1.5,
         "t_person_s": 3.0, "t_vehicle_s": 3.5, "gap_m": 0.4, "clip": "event1.mp4",
         "strobe": {"image": "event1-strobe.jpg", "moments": 9, "step_s": 0.5},
         "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5}, "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder)
        for name in ("event1.mp4", "event1-strobe.jpg", "clip.mp4"):
            (out / name).write_bytes(b"x")
        page = pack.page({"name": "gate", "world_points": SQUARE_ROAD}, [e], {"minutes": 1}, None, None, 10)
        shared = sorted(f.name for f in pack.share(out, page).iterdir())
    assert 'poster="event1-strobe.jpg"' in page and shared == ["event1-strobe.jpg", "event1.mp4", "index.html"]

def test_page_reads_without_colour_and_on_a_phone():
    """The gap strip tells busy from gap by height as well as colour, long gaps blue like the map's people; its labels
    and the map's card numbers are 18 px on phones, the numbers drawn over every dot; minutes read 22, not 22.0."""
    import roadmap, summary
    strip = roadmap.gap_strip({"duration_s": 60.0, "busy_s": [[2.0, 3.0], [24.0, 25.0]]}, [])
    assert f'class="busy" x="21.3" y="{roadmap.DOTS_PX}" height="{roadmap.BAR_PX}"' in strip
    assert (f'class="gap12" x="32.0" y="{roadmap.DOTS_PX + roadmap.GAP_INSET_PX}" '
            f'height="{roadmap.BAR_PX - 2 * roadmap.GAP_INSET_PX}"') in strip
    assert "Blue: a gap of 12 s or more" in strip and "Green" not in strip
    assert ".gaps .gap12 { fill: #2f7de1; }" in roadmap.STYLE and ".gaps .near { fill: none; stroke: #c27a00;" in roadmap.STYLE
    assert "@media (max-width: 600px) { .gaps text, .map text { font-size: 18px; } }" in roadmap.STYLE
    near = {"tier": "serious", "vehicle": "car#1", "vehicle_kmh": 30.0, "pet_s": 0.4, "where": [0.0, 0.0]}
    svg = roadmap.svg([near, near | {"where": [0.5, -0.4]}], [[-2, -2], [2, -2], [2, 2], [-2, 2]])
    assert svg.rindex("<circle") < svg.index(">#1</text>")  # card 2's dot never covers card 1's number
    assert pack.article("auto rickshaw") == "an auto rickshaw" and pack.article("motorcycle") == "a motorcycle"
    assert [summary.minutes(seen) for seen in ({"minutes": 22.0}, {"minutes": 12.5}, {})] == ["22", "12.5", "?"]
    assert "22 minutes of video" in pack.stats([], {"minutes": 22.0, "vehicles": 3})[1]


def test_a_saved_verdict_is_reused_until_its_inputs_change_and_a_failure_is_not_saved():
    """Spark's and Wonder's raw replies are kept by the SHA-256 of each input and parsed again on every read; a failed
    call or an unreadable reply is not kept. analyze counts the verdicts it reused; Wonder's go to event<N>-heard.json."""
    import analyze, seal, subprocess, tempfile
    from pathlib import Path
    adult = '{"cyan_is_a_pedestrian": true, "road_user": "adult", "reason": "walking"}'
    with tempfile.TemporaryDirectory() as tmp:
        path, asked = Path(tmp, "person-1.json"), []
        ask = lambda *_: asked.append(1) or adult
        assert seal.reused(path, [b"crop", "model"], ask, review.read_verdict)["road_user"] == "adult"
        assert seal.reused(path, [b"crop", "model"], ask, review.read_verdict)["road_user"] == "adult"
        fixed = lambda text: {**review.read_verdict(text), "fixed": True}  # a later parser fix reads the saved reply
        assert seal.reused(path, [b"crop", "model"], ask, fixed)["fixed"] and len(asked) == 1
        assert seal.reused(path, [b"other crop", "model"], ask, review.read_verdict) and len(asked) == 2
        assert seal.inputs_sha256([b"ab", b"c"]) != seal.inputs_sha256([b"a", b"bc"])
        for failed in (lambda: None, lambda: "no json"):  # a dropped call, an unreadable reply: asked again next run
            assert seal.reused(Path(tmp, "x.json"), [b"crop"], failed, review.read_verdict) is None
            assert not Path(tmp, "x.json").exists()

        def crop(clip, track, size, out):
            out.write_bytes(b"the same crop")
            return out
        video = Path(tmp, "v.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:a", "aac",
                        str(video)], check=True)
        old = review.person_crop, review.ask, listen.hear
        review.person_crop, review.ask = crop, ask
        listen.hear = lambda *_: asked.append(1) or '{"sounds": [{"t_s": 3.0, "sound": "horn"}]}'
        try:
            runs = [analyze.review_people(None, Path(tmp), [{"person": "7/0"}], {"7/0": {f: (0.14 * f, 0.0)
                                          for f in range(20)}}, {"7": {5: [100, 100, 120, 140]}}, {}, None,
                                          (640, 360), False) for _ in range(2)]
            heard = [listen.listen(video, {"t_person_s": 2.0, "t_vehicle_s": 2.5}, Path(tmp, "event1.wav"), "key")
                     for _ in range(2)]
        finally:
            review.person_crop, review.ask, listen.hear = old
        assert runs == [(0, 1), (1, 1)] and Path(tmp, "person-7-0.json").exists()
        assert heard[0] == heard[1] == [{"t_s": 1.0, "sound": "horn"}] and Path(tmp, "event1-heard.json").exists()
        assert len(asked) == 4  # one Spark look and one Wonder listen for the two runs


def test_feet_on_a_vehicle_box_are_not_on_the_road_at_an_angle():
    """road.feet_hidden drops a scooter rider whose box only sits on the bike's (too little inside for without_riders)
    and keeps a walker in front of the bike and a pedestrian in front of a bus; analyze uses it at an angle only."""
    import analyze
    bike, bus = {0: [100, 100, 160, 200]}, {0: [0, 0, 400, 300]}
    rider, walker, in_front = {0: [115, 20, 145, 110]}, {0: [120, 90, 140, 215]}, {0: [200, 150, 240, 310]}
    assert road.without_riders(rider, [bike]) == rider  # 0.11 of its box inside the bike's: today's filter keeps it
    assert road.feet_hidden(rider, road.boxes_by_frame([bike])) == {}
    assert road.feet_hidden(walker, road.boxes_by_frame([bike])) == walker
    assert road.feet_hidden(in_front, road.boxes_by_frame([bus])) == in_front
    site, H = {"image_points": SQUARE_IMG, "world_points": SQUARE_ROAD}, road.homography(SQUARE_IMG, SQUARE_ROAD)
    riding = {"r": {f: [190, 100 + 5 * f, 210, 140 + 5 * f] for f in range(20)}}  # 0.25 m a frame, 2 s
    scooter = {"motorcycle#1": {f: [180, 130 + 5 * f, 220, 200 + 5 * f] for f in range(20)}}
    pieces = lambda s: set(analyze.road_tracks(s, H, riding, scooter, (400, 400))[0])
    assert pieces(site) == set() and pieces({**site, "feet_hidden": False}) == {"r/0"}
    assert pieces({**site, "view": "top-down"}) == {"r/0"}  # a drone sees box centres: untouched


def test_spark_unclear_keeps_the_person_and_is_never_a_decoy():
    """Only a sure "no" rejects: "unclear" with the cyan box called not a pedestrian keeps the person, marked
    review_unclear, while "not a person" still rejects; a blind-set decoy is never someone Spark was unsure of."""
    import blind_set
    kept = review.gated({"is_person": False, "road_user": "unclear", "reason": "too small to tell"}, {}, [])
    assert kept["is_person"] is True and kept["review_unclear"] is True
    pole = {"is_person": False, "road_user": "not a person", "reason": "a pole"}
    assert review.gated(pole, {}, []) == pole
    sure = {"is_person": True, "road_user": "unclear", "reason": ""}
    assert review.gated(sure, {}, []) == sure  # a pedestrian, only not which kind: nothing overturned
    assert pack.confirmed([{"person": "1/0", "review": kept}, {"person": "2/0", "review": pole}]) == [
        {"person": "1/0", "review": kept}]
    pair = {"person": "1/0", "vehicle": "car#1", "pet_s": 6.0, "t_person_s": 1.0, "t_vehicle_s": 7.0}
    assert blind_set.decoys([pair], lambda pid: kept, 1, 200) == []
    assert blind_set.decoys([pair], lambda pid: {"is_person": True, "road_user": "adult"}, 1, 200) == [pair]


def test_spark_crop_draws_its_box_after_upscaling_outside_the_person():
    """The cyan box is drawn on the upscaled crop, BOX_PAD_PX outside the person's box, so no cyan lies on them."""
    import subprocess, tempfile
    from pathlib import Path
    box = [100, 100, 110, 130]  # 10 x 30 px: a 90 px crop at (60, 70), upscaled 4.27x
    assert review.outline(box, *review.crop_window(box, (640, 360))) == "drawbox=x=167:y=124:w=51:h=136:color=cyan:t=2"
    with tempfile.TemporaryDirectory() as tmp:
        clip, crop = Path(tmp, "clip.mp4"), Path(tmp, "person.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=gray:size=640x360:rate=10:duration=1",
                        "-vf", "drawbox=x=100:y=100:w=10:h=30:color=white:t=fill", "-pix_fmt", "yuv420p", str(clip)],
                       check=True)
        review.person_crop(clip, {3: box}, (640, 360), crop)
        rgb = subprocess.run(["ffmpeg", "-v", "error", "-i", str(crop), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             check=True, capture_output=True).stdout
    pixel = lambda x, y: rgb[3 * (review.CROP_OUT_PX * y + x):3 * (review.CROP_OUT_PX * y + x) + 3]
    assert len(rgb) == 3 * review.CROP_OUT_PX ** 2
    r, g, b = pixel(188, 124)  # on the box's top line
    assert r < 60 and g > 200 and b > 200
    assert min(pixel(172, 192)) > 220  # just inside the person's left edge: white, where a 1 px box drawn first was cyan


def test_spark_removals_are_printed_without_digits_or_crop_paths():
    """One terminal line per track Spark's gated verdict removed (review.said), at most LINE_COLS wide, its reason
    dropped when it holds a digit (a number plate could be in it); kept, unsure or unreviewed people print nothing."""
    import contextlib, io
    from pathlib import Path
    import analyze
    rider = {"is_person": False, "road_user": "rider", "reason": "seated on a motorcycle"}
    assert review.said("c84/0", rider) == \
        'Muse Spark: track c84/0 removed: rider, bike box under them ("seated on a motorcycle")'
    pole = {"is_person": False, "road_user": "not a person", "reason": "rear of an auto-rickshaw"}
    assert review.said("7/0", pole) == 'Muse Spark: track 7/0 removed: not a pedestrian ("rear of an auto-rickshaw")'
    assert review.said("7/0", pole | {"reason": "plate MP04 AB"}) == "Muse Spark: track 7/0 removed: not a pedestrian"
    long = review.said("c84/0", rider | {"reason": "a person " * 20})
    assert len(long) <= review.LINE_COLS and long.endswith('...")')
    assert len(review.public_reason("a person " * 20)) == review.REASON_CHARS
    unsure = review.gated({"is_person": False, "road_user": "unclear"}, {}, [])
    for kept in (None, {"is_person": True, "road_user": "adult"}, unsure):
        assert review.said("7/0", kept) is None
    original, out = review.review, io.StringIO()
    review.review = lambda *a, **k: dict(pole)
    try:
        with contextlib.redirect_stdout(out):
            analyze.review_people(None, Path("."), [{"person": "7/0"}, {"person": "7/0"}],
                                  {"7/0": {f: (0.0, 0.0) for f in range(20)}}, {"7": {5: [100, 100, 110, 130]}},
                                  {}, None, (640, 360), False)
    finally:
        review.review = original
    assert out.getvalue() == review.said("7/0", pole) + "\n" and ".jpg" not in out.getvalue()  # once per track


def test_exposure_counts_vehicles_over_indias_school_zone_speed():
    """over_25_kmh: the moving vehicles whose median speed is over road.IN_SCHOOL_KMH (reg. 16(5)), 0 included."""
    fps, frames = 10, 60
    fast, slow = edges_along_x(8.0, fps, frames), edges_along_x(6.0, fps, frames, y=5.0)  # 28.8 and 21.6 km/h
    seen = road.exposure({}, {"car#1": fast, "car#2": slow}, fps, 600)
    assert seen["vehicles"] == 2 and seen["over_25_kmh"] == 1
    assert road.exposure({}, {"car#2": slow}, fps, 600)["over_25_kmh"] == 0
    assert road.exposure({}, {}, fps, 600)["over_25_kmh"] == 0


def test_analyze_keeps_the_camera_check_and_maps_hdr_to_sdr():
    """events.json's camera: filmcheck.steadiness against the frame the calibration was clicked on (clip time 0 with
    window_s, else filmcheck.REF_S), none for a clip too short; prepare maps an HDR (HLG) source to BT.709."""
    import subprocess, tempfile
    from pathlib import Path
    import analyze, filmcheck
    asked, real = [], filmcheck.steadiness
    filmcheck.steadiness = lambda clip, start, end: asked.append((start, end)) or {"max_shift_px": 2}
    try:
        assert analyze.camera_check("clip", 9000) == analyze.camera_check("clip", 9000, [45, 945]) == {"max_shift_px": 2}
        assert analyze.camera_check("clip", 25) is None  # 2.5 s: under STEADY_MIN_S after the 1 s reference
    finally:
        filmcheck.steadiness = real
    assert asked == [(filmcheck.REF_S, 900.0), (0.0, 900.0)]
    with tempfile.TemporaryDirectory() as tmp:
        hlg = Path(tmp, "hlg.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=1", "-vf",
                        "setparams=color_trc=arib-std-b67:color_primaries=bt2020:colorspace=bt2020nc",
                        "-pix_fmt", "yuv420p", str(hlg)], check=True)
        assert analyze.probe(hlg, "stream=color_transfer") == "arib-std-b67"
        assert analyze.probe(analyze.prepare(hlg, Path(tmp)), "stream=color_transfer") == "bt709"


def test_every_default_model_id_is_standard_mode():
    """No model id is a Contributor-mode one (Meta trains on Contributor-mode content). Contributor variants exist
    only for Muse Spark 1.3 and 1.2, so in practice this guards the Spark ids. It checks the defaults only: a
    LETTER_MODEL or JUDGE_MODEL set in the environment is not covered."""
    for model in (sam.MODEL, review.MODEL, listen.MODEL, pack.IMAGE_MODEL, pack.LETTER_MODEL, pack.JUDGE_MODEL):
        assert "contributor" not in model.lower(), model


def test_after_fix_pass_mark_is_a_one_sided_fisher_exact_test():
    """G7's numbers (GATES.md): one-sided [[3,0],[0,3]] is exactly 0.05 (0.1 is the two-sided value), so 0 of 3 after
    3 of 3 passes and 1 of 3 does not; the plan's prototypes: 25 of 63 passes at 15 or fewer (83% if the share halved),
    10 of 300 at 3 or fewer (26% with one after-film, 33% with two), 20 of 150 at 10 or fewer (58%); 4 of 63 has no
    mark at all."""
    import passmark
    assert passmark.fisher_drop_p(3, 3, 0, 3) == 0.05 and passmark.fisher_drop_p(3, 3, 1, 3) == 0.2
    assert passmark.mark(3, 3, 3) == 0
    assert (passmark.mark(25, 63, 63), round(100 * passmark.chance(25, 63, 63))) == (15, 83)
    assert (passmark.mark(10, 300, 300), round(100 * passmark.chance(10, 300, 300)),
            round(100 * passmark.chance(10, 300, 600))) == (3, 26, 33)
    assert (passmark.mark(20, 150, 150), round(100 * passmark.chance(20, 150, 150))) == (10, 58)
    assert [passmark.mark(k, 63, 63) for k in (4, 5)] == [None, 0] and passmark.chance(4, 63, 63) == 0.0


def test_page_shows_the_pre_registered_after_fix_pass_mark():
    """G7 on the page from the headline's own k and n: the mark for an after-film as long and its power for one and
    two after-films; a group passed by one bus is one vehicle in V, so V = 1 asks for 19 after-films; nothing without
    the crosser list or under the pace warning, and never in the letter's facts."""
    import pace, passmark
    limits = {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5}, "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}
    hit = lambda i, vehicle: {"person": f"c{i}/0", "vehicle": vehicle, "tier": "close pass", "pet_s": 2.0,
                              "vehicle_kmh": 30.0, "death_risk_pct": 1.5, "t_person_s": float(i), "t_vehicle_s": i + 2.0,
                              "gap_m": 0.4, "with_limit": limits}
    crossers = [f"c{i}" for i in range(63)]
    seen = {"minutes": 15.0, "duration_s": 900.0, "crossings": 63, "crossers": crossers}
    spread = [hit(i, f"car#{i}") for i in range(25)]
    mark = passmark.after_mark(spread, seen)
    assert ("15 or fewer of about 63 crossings have a moving vehicle through the same spot within 3 s (now 25 of 63) "
            "and 15 or fewer distinct vehicles do (now 25)") in mark and "83% chance" in mark and "together 97%" in mark
    site = {"name": "gate", "world_points": SQUARE_ROAD}
    assert html.escape(mark) in pack.page(site, spread, seen, None, None, 10)
    assert "Fisher" not in pack.facts(site, spread, seen)
    fast = pace.walking(walkers(pace.MIN_PIECES, 3.0), 10)
    assert "Fisher" not in pack.page(site, spread, seen, None, None, 10, walking=fast)
    group = [hit(i, "bus#1") for i in range(25)] + [{**hit(0, "car#9"), "t_person_s": 99.0}]
    assert passmark.counts(group, set(crossers)) == (25, 1)
    assert ("no after-film this long can show a drop" in passmark.after_mark(group, seen)
            and "film 19 dismissals after the fix" in passmark.after_mark(group, seen))
    assert "film 2 dismissals" in passmark.after_mark([hit(i, f"car#{i}") for i in range(3)], seen)
    assert passmark.after_mark([], seen).startswith("None of the 63 crossings had")
    assert passmark.after_mark(spread, {"minutes": 15.0, "crossings": 63}) == ""


def test_method_says_sam_and_spark_made_the_tracks_only_when_sam_ran():
    """sample/'s made-up tracks have no SAM request counts, so the method never says SAM tracked them or Spark checked
    them; a SAM run's says SAM tracked what it found, at most MAX_OBJECTS a request, never 'every' person."""
    site, seen = {"name": "gate", "world_points": SQUARE_ROAD}, {"minutes": 1.0, "crossings": 3}
    made_up = pack.page(site, [], seen, None, None, 10)
    assert "No SAM tracking run is recorded for these tracks" in made_up
    assert "SAM 3.1 tracked" not in made_up and "Muse Spark looked" not in made_up
    tracked = pack.page(site, [], seen, None, None, 10, full=(0, 4, []))
    assert (f"SAM 3.1 tracked the pedestrians and vehicles it found, at most {sam.MAX_OBJECTS} objects per video "
            "request") in tracked and "Muse Spark looked at the person in each near-miss" in tracked
    assert "every pedestrian" not in made_up + tracked


def test_a_window_page_says_which_minutes_were_analysed_and_caps_the_school_year_line():
    """window_s (in events.json's exposure) and recording_s: the method says minutes S-E of an M-minute recording and
    that times count from second S; the school-year line scales no further than the analysed minutes."""
    site = {"name": "gate", "world_points": SQUARE_ROAD}
    seen = {"minutes": 15.0, "duration_s": 900.0, "crossings": 40, "crossers": [f"c{i}" for i in range(40)],
            "window_s": [130, 1030]}
    assert ("Only minutes 2.2-17.2 of this 25-minute recording were analysed (seconds 130-1030); times on this page "
            "count from second 130.") in pack.page(site, [], seen, None, None, 10, recording_s=1500.0)
    assert "Only minutes 2.2-17.2 of the recording were analysed" in pack.page(site, [], seen, None, None, 10)
    whole = {k: v for k, v in seen.items() if k != "window_s"}
    assert "were analysed" not in pack.page(site, [], whole, None, None, 10)
    events = [{"person": "c1/0", "vehicle": "car#1", "pet_s": 0.5, "tier": "serious"}]
    school = {"school_days": 200, "dismissal_minutes": 30}
    assert pack.headline(events, seen, school)[-1].endswith(
        "about 200 within 1.5 s (200 school days, the 15 analysed minutes of each dismissal).")
    assert pack.headline(events, whole, school)[-1].endswith("(200 school days, 30-minute dismissals).")
    assert pack.headline(events, seen, {**school, "dismissal_minutes": 10})[-1].endswith("10-minute dismissals).")


def test_page_names_spark_removals_unsure_people_the_25_kmh_count_and_the_camera_check():
    """A track Spark's review removed is named in a page note (its reason cut, never one with a digit, no crop path);
    someone Spark was unsure of is "pedestrian (Spark unsure; kept)"; an Indian site's engineering numbers count the
    vehicles over 25 km/h, 0 included, and an older events.json keeps the same facts; the receipt says how many Spark
    verdicts were reused and what the camera check found, in the recording's time."""
    unsure = review.gated({"is_person": False, "road_user": "unclear", "reason": "too small"}, {}, [])
    assert pack.passed({"review": unsure})[0] == "pedestrian (Spark unsure; kept)"
    assert pack.passed({"review": {"is_person": True, "road_user": "unclear"}})[0] == "pedestrian"
    pole = {"is_person": False, "road_user": "not a person", "reason": "a pole"}
    events = [{"person": "c1/0", "review": pole}, {"person": "c1/0", "review": pole},
              {"person": "c2/0", "review": {"is_person": False, "road_user": "rider", "reason": "plate MP04 AB"}},
              {"person": "c3/0", "review": unsure}, {"person": "c4/0"}]
    note = pack.removed_note(events)
    assert note == ('Removed by Muse Spark: 2 tracks (track c1/0, not a person ("a pole"); track c2/0, rider). '
                    "Spark can be wrong.")
    assert pack.removed_note(events[3:]) == ""
    page = pack.page({"name": "gate", "world_points": SQUARE_ROAD}, [], {"minutes": 15.0}, None, None, 10, removed=note)
    assert html.escape(note) in page and "MP04" not in page and "person-" not in page
    seen = {"minutes": 20.0, "crossings": 100, "vehicles": 5, "over_25_kmh": 0}
    india = pack.engineering_lines(seen, None, {"country": "IN"})
    assert india[-1] == ("0 of 5 moving vehicles passed faster than 25 km/h, the speed India's Motor Vehicles "
                         "(Driving) Regulations 2017 (reg. 16(5)) set past schools and hospitals where signed.")
    assert pack.engineering_lines(seen, None, {"country": "GB"}) == india[:-1]
    older = {k: v for k, v in seen.items() if k != "over_25_kmh"}
    assert pack.engineering_lines(older, None, {"country": "IN"}) == india[:-1]
    run = {"minutes": 1.0, "sam_requests": 0, "spark_reviewed": 4, "spark_reused": 3}
    looked = [{"person": f"c{i}/0", "review": {"is_person": True, "road_user": "adult"}} for i in range(4)]
    moved = {"max_shift_px": 9, "at_s": 120.0, "moved": True, "dx_dy": [-7, 2]}
    line = pack.receipt_line({"run": run, "events": looked, "camera": moved, "exposure": {"window_s": [130, 1030]}},
                             None, None)
    assert "Muse Spark looked at 4 people (3 of 4 verdicts reused from an earlier run: same crops, same replies)" in line
    assert "the camera moved 7 px (of 640) at 4:10 into the recording, so positions after that are off" in line
    dark = {"max_shift_px": 2, "at_s": 60.0, "moved": False, "dx_dy": [2, 0], "darker_pct": 45, "dark_at_s": 300.0}
    assert pack.camera_note(dark) == ("the largest camera shift was 2 px (of 640), at 1:00; the picture was 45% "
                                      "darker by 5:00, where the camera check stopped")
    assert pack.camera_note(None) == "" and "camera" not in pack.receipt_line({"run": run, "events": []}, None, None)


def test_indian_legal_box_quotes_the_driving_regulations_word_for_word_without_the_count():
    """reg. 16(5) as the Gazette prints it, with its PDF page and the fixed sign-only sentence; reg. 39(1) only with a
    marked crossing; the Gazette cited as itself; never the 25 km/h count, the site's name or a broken rule."""
    site = {"name": "LNCT gate", "country": "IN", "city": "Bhopal", "world_points": SQUARE_ROAD}
    box = pack.legal_section(site)
    assert ("No driver shall drive at a speed exceeding twenty-five kilometre per hour or such lower speed as may be "
            "specified on the road signage while passing by a construction site or a school or a hospital, wherever "
            "indicated by signage, or on roads without footpaths and soft shoulders where pedestrians use a part of "
            "the carriageway to walk.") in box
    assert f'{pack.gazette.PDF}#page=10">Regulation 16(5), PDF page 10' in box
    assert "This rule applies where signs show it; we do not say any driver broke it." in box
    assert "India's limit past a school or hospital where signs show it" in box
    assert "Gazette of India Extraordinary No. 525, 23 June 2017, G.S.R. 634(E)" in box
    assert "39(1)" not in box and "39(1)" not in pack.legal_section({**site, "zebra_m": []})
    zebra = pack.legal_section({**site, "zebra_m": [[0, 0], [4, 0], [4, 8], [0, 8]]})
    assert f'{pack.gazette.PDF}#page=15">Regulation 39(1), PDF page 15' in zebra
    assert ("While approaching an uncontrolled pedestrian crossing, the driver shall slowdown, stop and give way to "
            "pedestrians, users of invalid carriages and wheelchairs.") in zebra
    assert pack.legal_section({"country": "GB", "zebra_m": [[0, 0], [4, 0], [4, 8]]}) == ""
    seen = {"minutes": 20.0, "crossings": 100, "vehicles": 5, "over_25_kmh": 2}
    page = pack.page(site, [], seen, None, None, 10)
    law = page.split('<section id="law">')[1].split("</section>")[0]
    assert "2 of 5 moving vehicles passed faster than 25 km/h" in page and "moving vehicles" not in law
    assert "LNCT" not in law and "illegal" not in law and "No driver shall" not in pack.facts(site, [], seen)
    stopped = pack.engineering_lines({**seen, "vehicles": 0, "over_25_kmh": 0}, None, site)
    assert not [line for line in stopped if "faster than 25 km/h" in line]  # never "0 of 0 moving vehicles"


def test_a_letter_saying_a_driver_broke_a_rule_goes_back_and_is_flagged_if_kept():
    """Code, at no cost, sends back a letter or fix reason that says someone broke a law or rule; a video cannot
    show a limit applied. "broken" (a broken footpath) is no accusation."""
    assert pack.accusing("Cars passed at 30 km/h. That is illegal here.\nDrivers violated the limit.") == [
        "That is illegal here.", "Drivers violated the limit."]
    assert pack.accusing("The footpath is broken. Drivers braked late. Unlawfully fast; a breach.") == [
        "Unlawfully fast; a breach."]
    good = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "Cars passed close to people."}
    bad = {**good, "letter": "Drivers broke the 25 km/h limit."}
    replies, prompts, judged = [bad, good], [], []
    old = pack.model_plan, pack.judge_problems
    pack.model_plan = lambda prompt, key, photo=None, known=None: (prompts.append(prompt), replies.pop(0))[1]
    pack.judge_problems = lambda letter, measured, key: judged.append(letter) or []
    try:
        plan = pack.ask_plan("PROMPT", '{"limit_kmh": 25}', "key")
        assert plan["letter"] == good["letter"] and plan["tries"] == 2 and judged == [good["letter"]]
        assert "says someone broke a rule" in prompts[1] and bad["letter"] in prompts[1]
        replies[:] = [{**good, "why": "It is illegal to speed here."}] * pack.LETTER_TRIES
        stubborn = pack.ask_plan("PROMPT", '{"limit_kmh": 25}', "key")
    finally:
        pack.model_plan, pack.judge_problems = old
    assert stubborn["accuses"] == ["It is illegal to speed here."] and stubborn["tries"] == pack.LETTER_TRIES
    section = pack.letter_section(stubborn)
    assert "says someone broke a rule, which a video cannot show: It is illegal to speed here." in section
    assert 'id="letter-check" hidden' in section


def test_filmcheck_help_prints_its_usage_and_a_non_video_file_is_refused_cleanly():
    """`python3 filmcheck.py --help` prints the module's usage and exits 0 (it used to be read as a clip and crash in
    ffprobe's JSON); a file that is not a video stops with one clear line, no traceback."""
    import subprocess, sys
    from pathlib import Path
    here = Path(__file__).parent
    helped = subprocess.run([sys.executable, "filmcheck.py", "--help"], cwd=here, capture_output=True, text=True)
    assert helped.returncode == 0 and "Run: python3 filmcheck.py CLIP" in helped.stdout
    refused = subprocess.run([sys.executable, "filmcheck.py", "README.md"], cwd=here, capture_output=True, text=True)
    assert refused.returncode == 1 and "could not read it" in refused.stderr and "Traceback" not in refused.stderr



def test_a_judge_that_errors_or_a_writer_blip_never_loses_the_paid_letter():
    """T3: a judge's URLError or HTTP 503 is the "could not be read" problem, so the letter comes back with that point
    to check; one failed judge never drops the other's review; a writer failure after a paid letter keeps it."""
    import io
    import urllib.error
    good = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "Cars passed close to children."}
    calls = []
    def writer(prompt, key, photo=None, known=None):
        calls.append(prompt)
        if len(calls) > 1 and blip:
            raise urllib.error.URLError("network is unreachable")
        return good
    def spark_down(prompt, image, key):
        raise urllib.error.HTTPError("https://example.invalid", 503, "Service Unavailable", {}, io.BytesIO())
    old = pack.model_plan, pack.spark_reply, pack.open_model_reply, pack.JUDGE_URL
    pack.model_plan, pack.spark_reply = writer, spark_down
    try:
        blip = False
        plan = pack.ask_plan("PROMPT", "{}", "key")
        assert plan["letter"] == good["letter"] and plan["unsupported"] == [pack.JUDGE_FAILED]
        assert plan["tries"] == 1 and html.escape("the reviewer says: " + pack.JUDGE_FAILED) in pack.letter_section(plan)
        pack.JUDGE_URL = "http://127.0.0.1:8080/v1"  # the open judge answers while Spark is down
        pack.open_model_reply = lambda prompt, image, schema, judge=False: ('{"problems": ["Too long."]}', {})
        assert pack.judge_problems("letter", "{}", "key") == [pack.JUDGE_FAILED, "Too long."]
        pack.JUDGE_URL = ""
        calls.clear()
        blip = True
        kept = pack.ask_plan("PROMPT", "{}", "key")
        assert kept["letter"] == good["letter"] and kept["tries"] == 1 and kept["unsupported"] == [pack.JUDGE_FAILED]
        calls.append("a paid call that failed")
        try:
            pack.ask_plan("PROMPT", "{}", "key")  # the very first call fails: nothing to keep, so it is not hidden
            raise AssertionError("a first-call network error must reach main")
        except urllib.error.URLError:
            pass
    finally:
        pack.model_plan, pack.spark_reply, pack.open_model_reply, pack.JUDGE_URL = old
    err = OSError("boom")
    assert "nothing was saved" in pack.failure_line(None, None, "", err)
    assert "nothing was saved" not in pack.failure_line(good, None, "", err)
    assert "unchanged" in pack.failure_line(good, good, "shorter please", err)


def test_letter_and_judge_servers_are_read_from_dot_env_when_not_exported():
    """T3: a forgotten export on Monday still finds JUDGE_MODEL_URL and LETTER_MODEL_URL in .env (sam.env_value)."""
    import importlib
    import os
    import tempfile
    from pathlib import Path
    names = ("LETTER_MODEL_URL", "JUDGE_MODEL_URL", "JUDGE_MODEL")
    old_file, old_env = sam.ENV_FILE, {k: os.environ.pop(k, None) for k in names}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            sam.ENV_FILE = Path(tmp) / ".env"
            sam.ENV_FILE.write_text("MODEL_API_KEY=x\nJUDGE_MODEL_URL=https://api.fireworks.ai/inference/v1\n"
                                    "JUDGE_MODEL = accounts/fireworks/models/muse-spark-open\n")
            importlib.reload(pack)
            assert pack.JUDGE_URL == "https://api.fireworks.ai/inference/v1" and pack.LETTER_URL == ""
            assert pack.JUDGE_MODEL == "accounts/fireworks/models/muse-spark-open"
            os.environ["JUDGE_MODEL_URL"] = "http://127.0.0.1:8080/v1"  # an export wins over .env
            assert importlib.reload(pack).JUDGE_URL == "http://127.0.0.1:8080/v1"
    finally:
        sam.ENV_FILE = old_file
        for k, value in old_env.items():
            os.environ.pop(k, None)
            if value is not None:
                os.environ[k] = value
        importlib.reload(pack)


def test_a_letter_with_a_blank_is_flagged_and_never_signed():
    """T6: "[School name]", "[Date]" or "____" left in the letter shows under "Check before sending", and sign-off
    (pack.py --approved-by and agent.py --approve, both through pack.sign) refuses it and writes no signoff.json."""
    import tempfile
    from pathlib import Path
    assert "[School name]" not in pack.LETTER_PROMPT and "nothing in square brackets" in pack.LETTER_PROMPT
    blank = {"fix": "speed table", "why": "w", "image_prompt": "i", "writer": "Muse Spark",
             "letter": "[Date]\nDear Sir,\nCars passed close.\nThe Principal, [School name]\nSigned: ____ [Date]"}
    assert pack.placeholders(blank["letter"]) == ["[Date]", "[School name]", "____"]
    section = pack.letter_section(blank)
    assert "Check before sending: fill in [Date], [School name], ____ before signing." in section
    assert 'id="letter-check" hidden' in section
    with tempfile.TemporaryDirectory() as tmp:
        try:
            pack.sign(Path(tmp), blank, "A. Rao, Principal", "Gate School")
            raise AssertionError("a letter with blanks was signed")
        except SystemExit as stop:
            assert "[School name]" in str(stop) and "--notes" in str(stop)
        assert not (Path(tmp) / "signoff.json").exists()
        filled = {**blank, "letter": "Dear Sir,\nCars passed close (PET < 1 s, speeds > 30 km/h).\nThe Principal"}
        assert pack.placeholders(filled["letter"]) == []
        assert pack.sign(Path(tmp), filled, "A. Rao, Principal", "Gate School")["school"] == "Gate School"


def test_case_agent_starts_from_the_modes_the_paid_run_cached():
    """A crowd-mode paid run: the first message names its modes, and a track call in another mode, which --budget 0
    refuses with its cost, tells the model which modes are cached instead of dead-ending; "auto" is a mode too."""
    import agent, contextlib, io, tempfile
    bodies, old = [], (agent.spark_turn, agent.run_tracker, agent.MAX_TURNS)
    def tracker(p, site):
        if site["person_mode"] != "crowd":
            raise ValueError("estimated SAM cost $2.08 is over the $0.00 this run may still spend")
        return {"car": [0, 1]}
    agent.spark_turn, agent.run_tracker, agent.MAX_TURNS = scripted_spark([None], bodies), tracker, 1
    try:
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            out, site, _ = agent_case(folder)
            (out / "site.json").write_text(json.dumps({**site, "person_mode": "crowd"}))
            agent.work(out / "video.mp4", out / "site.json", out, "key")
            p = {"out": str(out), "site": str(out / "site.json"), "video": str(out / "video.mp4")}
            failed = agent.run_tool(p, {"name": "track", "arguments": '{"people": "video", "vehicles": "video"}'}, "key")
            tracked = agent.run_tool(p, {"name": "track", "arguments": '{"people": "crowd", "vehicles": "video"}'}, "key")
            auto = agent.track(p, {"people": "auto", "vehicles": "lorry"}, "key")
    finally:
        agent.spark_turn, agent.run_tracker, agent.MAX_TURNS = old
    assert 'names people "crowd" and vehicles "video" for tracking' in bodies[0]["input"][0]["content"]
    assert failed["summary"].startswith('track failed: the site file names people "crowd" and vehicles "video"')
    assert "$2.08" in failed["summary"] and tracked["summary"].startswith("Tracked people in crowd mode")
    assert "auto" in agent.MODE["enum"] and '"auto"' in auto["summary"]  # refused for "lorry", not for "auto"


def test_a_bad_site_file_stops_before_any_re_encoding():
    """Points on one line, or a check mark above the horizon, stop analyze.py with a message (no traceback) before
    the video is hashed or re-encoded, so no output folder is made."""
    import subprocess, sys, tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        line = {"image_points": [[0, 0], [1, 1], [2, 2], [3, 3]], "world_points": SQUARE_ROAD, "vehicles": ["car"]}
        sky = {"image_points": [[250, 100], [350, 100], [500, 300], [100, 300]], "world_points": SQUARE_ROAD,
               "vehicles": ["car"],  # the horizon is at y = 33.3
               "check": {"what": "line A to line B along the near kerb", "points": [[300, 200], [300, 20]]}}
        for site, said in ((line, "click them again"), (sky, "below the horizon")):
            Path(tmp, "site.json").write_text(json.dumps(site))
            run = subprocess.run([sys.executable, "analyze.py", "missing.mp4", str(Path(tmp, "site.json")), "--out",
                                  str(Path(tmp, "out"))], capture_output=True, text=True, cwd=Path(__file__).parent)
            assert run.returncode == 1 and said in run.stderr and "Traceback" not in run.stderr, run.stderr
            assert not Path(tmp, "out").exists()


def test_the_free_estimate_shows_auto_modes_worst_case_and_the_recording_date():
    """--budget 0 on a first run: the auto-mode line prints before the cost refusal, after the recording date read
    from the file's creation time in IST (or NOT RECORDED)."""
    import analyze, contextlib, io, subprocess, sys, tempfile
    from pathlib import Path
    old = sam.load_api_key, sys.argv
    sam.load_api_key = lambda: "key"  # never used: the run stops at the estimate
    try:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp, "rec.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10", "-t", "2",
                            "-metadata", "creation_time=2026-11-02T10:28:30Z", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            str(video)], check=True)
            Path(tmp, "site.json").write_text(json.dumps({"image_points": SQUARE_IMG, "world_points": SQUARE_ROAD,
                                                          "vehicles": ["car"], "vehicle_mode": "auto"}))
            sys.argv = ["analyze.py", str(video), str(Path(tmp, "site.json")), "--out", str(Path(tmp, "out")),
                        "--budget", "0"]
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                assert exits(analyze.main)
    finally:
        sam.load_api_key, sys.argv = old
    lines = printed.getvalue().splitlines()
    assert lines[0] == "recorded 2026-11-02 15:58:30 IST"
    assert lines[1].startswith("auto mode may add up to $") and "SAM cost about" in lines[2], lines


def test_a_folder_is_refused_after_a_crowd_sampling_rate_changes_but_not_for_the_recording_date():
    import analyze, crowd, seal, tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        video, out = Path(tmp, "a.MOV"), Path(tmp, "out")
        out.mkdir()
        video.write_bytes(b"x" * 10)
        sha = seal.file_sha256(video)
        assert analyze.check_source(video, out, "", sha) is None  # no creation time in these bytes
        stamp = json.loads((out / "source.json").read_text())
        assert stamp["vehicle_fps"] == crowd.VEHICLE_FPS and stamp["recorded"] is None
        (out / "source.json").write_text(json.dumps({k: v for k, v in stamp.items()
                                                     if k not in ("crowd_fps", "vehicle_fps", "recorded")}))
        analyze.check_source(video, out, "", sha)  # stamped before these keys: today's rates assumed
        (out / "source.json").write_text(json.dumps({**stamp, "recorded": "2026-10-31 10:00:00 IST"}))
        analyze.check_source(video, out, "", sha)  # the date is kept, never compared
        old = crowd.VEHICLE_FPS
        crowd.VEHICLE_FPS = old // 2
        try:
            assert exits(lambda: analyze.check_source(video, out, "", sha))  # every cached image would be paid again
        finally:
            crowd.VEHICLE_FPS = old


def test_spark_rider_call_needs_the_feet_no_lower_than_the_bike():
    """review.gated uses road's feet rule: a walker passing in front of a parked bike has feet below its box."""
    rider = {"is_person": False, "road_user": "rider", "reason": "on a bike"}
    person = {5: [100, 100, 110, 130]}
    assert review.gated(rider, person, [{5: [95, 110, 115, 130 - road.RIDER_FEET_PX]}]) == rider  # feet at the limit
    walker = review.gated(rider, person, [{5: [95, 110, 115, 129 - road.RIDER_FEET_PX]}])  # feet 1 px lower: in front
    assert walker["is_person"] and walker["rider_unconfirmed"]


def test_readme_first_screen_fits_a_phone_its_links_resolve_and_one_story_on_the_kaggle_account():
    """The README's first screen (everything before "## Check it yourself") stays under 30 lines; every link to a
    README or GATES.md heading lands on one (the first screen once pointed at a GATES heading that had been renamed);
    and the README, its Declarations and the Version 2 record say the same thing about who ran the Kaggle notebook."""
    import re
    from pathlib import Path
    here = Path(__file__).parent
    readme, gates = (here / "README.md").read_text(), (here / "GATES.md").read_text()
    assert len(readme.split("\n## Check it yourself")[0].splitlines()) < 30

    def slugs(text):  # GitHub's heading anchors: lower case, punctuation dropped, spaces to hyphens
        return {re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-")
                for h in re.findall(r"^#+ (.+)$", text, re.M)}
    for page, anchors in (("", slugs(readme)), ("GATES.md", slugs(gates))):
        for anchor in re.findall(r"\]\(" + re.escape(page) + r"#([^)]+)\)", readme):
            assert anchor in anchors, (page or "README.md", anchor)
    who = "The Kaggle notebook was run by the author."
    assert who in readme.split("## Declarations")[1]
    assert " ".join(who.split()) in " ".join((here / "kaggle" / "<removed-run-record>").read_text().split())
    assert "not downloaded yet" not in readme


def test_feet_overlap_counts_frames_whose_feet_sit_on_a_vehicle_box_after_the_rider_filter():
    """feet_overlap.py's share: a rider sitting on a bike's box counts as hidden, a walker in front of it does not,
    and a rider inside a bus's box (dropped by without_riders) is not in the total at all."""
    import feet_overlap
    people = {"rider": {0: [115, 20, 145, 110]}, "walker": {0: [120, 90, 140, 215]}, "in bus": {1: [10, 10, 50, 100]}}
    vehicles = {"motorcycle#1": {0: [100, 100, 160, 200]}, "bus#2": {1: [0, 0, 400, 300]}}
    assert feet_overlap.feet_overlap(people, vehicles) == (1, 2)


def test_a_judge_that_always_fails_costs_one_writer_call_and_a_real_objection_still_goes_back():
    """A judge outage is no fault in the letter: the writer is paid once and that letter is kept with the point to
    check. When one judge fails and the other objects, only the objection goes back, and a writer blip on that retry
    keeps the paid letter."""
    import contextlib, io
    import urllib.error
    good = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "Cars passed close to children."}
    prompts = []
    def writer(prompt, key, photo=None, known=None):
        prompts.append(prompt)
        if len(prompts) > 1 and blip:
            raise urllib.error.URLError("network is unreachable")
        return good
    def spark_down(prompt, image, key):
        raise urllib.error.URLError("no route to host")
    old = pack.model_plan, pack.spark_reply, pack.open_model_reply, pack.JUDGE_URL
    pack.model_plan, pack.spark_reply, blip = writer, spark_down, False
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            plan = pack.ask_plan("PROMPT", "{}", "key")
            assert len(prompts) == 1 and plan["tries"] == 1 and plan["unsupported"] == [pack.JUDGE_FAILED]
            pack.JUDGE_URL = "http://127.0.0.1:8080/v1"
            pack.open_model_reply = lambda prompt, image, schema, judge=False: ('{"problems": ["Too long."]}', {})
            prompts.clear()
            plan = pack.ask_plan("PROMPT", "{}", "key")  # Spark down, the open judge objects every time
            assert len(prompts) == pack.LETTER_TRIES and "Too long." in prompts[1]
            assert pack.JUDGE_FAILED not in prompts[1] and plan["unsupported"] == [pack.JUDGE_FAILED, "Too long."]
            prompts.clear()
            blip = True
            kept = pack.ask_plan("PROMPT", "{}", "key")
            assert kept["letter"] == good["letter"] and kept["tries"] == 1 and len(prompts) == 2
    finally:
        pack.model_plan, pack.spark_reply, pack.open_model_reply, pack.JUDGE_URL = old



def test_judge_bench_public_is_built_only_from_sample_letters_with_each_source_recorded():
    """kaggle/judge-bench-public.json holds the letters public_bench() builds: Glimmer v1's and Spark Open's letters
    about the synthetic sample/, each item naming its source, and no word of DUT, SinD, YouTube or kids' footage."""
    import judge_bench, re
    real = re.compile(r"\bDUT\b|\bSinD\b|youtu|\bkids?\b|footage", re.I)
    bases = [judge_bench.glimmer_base(), judge_bench.spark_open_base()]
    assert [b[0] for b in bases] == list(judge_bench.SOURCES)
    for name, letter, facts in bases:
        assert not real.search(letter) and not judge_bench.code_flags(letter, facts)
        assert json.loads(facts)["site"].startswith("Synthetic example crossing")
        assert "synthetic sample/" in judge_bench.SOURCES[name]
    bench = judge_bench.public_bench()
    assert len(bench) == 31 and sum(not i["planted"] for i in bench) == 8  # Spark Open's letter has no swap to plant
    assert all(i["source"] == judge_bench.SOURCES[i["id"].split("/")[0]] for i in bench)
    assert not any(real.search(i["letter"] + i["measured"] + i["source"]) for i in bench)
    published = json.loads(judge_bench.PUBLIC.read_text())
    keys = ("id", "kind", "named", "planted", "letter", "measured", "source")
    assert [{k: i[k] for k in keys} for i in published] == bench  # the file is the bench, judge verdicts aside
    assert all(i["code"] == [bool(judge_bench.code_flags(i["letter"], i["measured"]))] for i in published)
    record = json.loads(judge_bench.SPARK_OPEN_RECORD.read_text())
    assert record["model"].endswith("muse-spark-open") and record["letter_sha256"].startswith("a721a428")



def test_open_judge_with_two_votes_counts_a_problem_only_when_both_replies_list_one():
    """JUDGE_VOTES=2: the JUDGE_MODEL_URL judge (a fake llama-server here) is asked twice per letter, in pack.py and in
    judge_bench.py's Glimmer column; one flag of two is no problem, an unreadable reply is still never a pass, and the
    bench keeps both raw replies with the vote. Muse Spark is still asked once."""
    import contextlib, io, judge_bench
    as_reply = lambda content: {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    flag, clean = '{"problems": ["Says a warrant is met."]}', '{"problems": []}'
    server, seen = fake_open_model([as_reply(r) for r in (flag, flag, flag, clean, flag, "no JSON here",
                                                         flag, clean, flag, flag)])
    sparks, old = [], (pack.JUDGE_URL, pack.LETTER_URL, pack.JUDGE_VOTES, pack.spark_reply)
    pack.JUDGE_URL, pack.LETTER_URL, pack.JUDGE_VOTES = f"http://127.0.0.1:{server.server_port}/v1", "", 2
    pack.spark_reply = lambda prompt, image, key: sparks.append(prompt) or clean
    item = {"id": "x", "kind": "k", "named": True, "planted": True, "letter": "L", "measured": "{}"}
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            both, split, unread = (pack.judge_problems("letter", "{}", None) for _ in range(3))
            ask = judge_bench.asker("glimmer")
            one_of_two = judge_bench.judged(item, "glimmer", ask, 1, pack.JUDGE_VOTES)
            two_of_two = judge_bench.judged(item, "glimmer", ask, 1, pack.JUDGE_VOTES)
            pack.JUDGE_URL = ""
            spark_only = pack.judge_problems("letter", "{}", "key")
            spark_run = judge_bench.judged(item, "spark", lambda prompt: flag, 1)
    finally:
        pack.JUDGE_URL, pack.LETTER_URL, pack.JUDGE_VOTES, pack.spark_reply = old
        server.shutdown()
        server.server_close()
    assert both == ["Says a warrant is met."] and split == [] and unread == ["The reviewer's reply could not be read."]
    assert len(seen) == 10 and all(body["response_format"]["type"] == "json_schema" for _, body, _ in seen)
    assert one_of_two["glimmer"] == [False] and one_of_two["glimmer_votes"] == [{"replies": [flag, clean], "vote": False}]
    assert two_of_two["glimmer"] == [True] and two_of_two["glimmer_votes"][0]["vote"] is True
    assert spark_only == [] and len(sparks) == 1  # Spark: one call, as before
    assert spark_run["spark"] == [True] and "spark_votes" not in spark_run
    assert pack.vote([["a"], ["b"]]) == ["a"] and pack.vote([["a"], []]) == [] and pack.vote([["a"], None]) is None
    assert pack.vote([[]]) == [] and pack.vote([["a"]]) == ["a"]  # one vote: what the one reply said
    text = "\n".join(judge_bench.table([one_of_two, two_of_two]))
    assert "Muse Glimmer: 2 of 2 runs asked 2 times, a problem counted only when every reply listed one" in text
    assert "Muse Spark:" not in text



def test_kaggle_notebook_v3_judges_the_public_bench_twice_and_saves_the_letter():
    """Version 3 of the Glimmer notebook: valid JSON, the bench from the repo's public sample/ file with JUDGE_VOTES=2
    for Glimmer, the letter and plan.json saved as outputs, and who ran it in the agreed words."""
    from pathlib import Path
    raw = Path(__file__).with_name("kaggle").joinpath("<removed-run-record>").read_text()
    notebook = json.loads(raw)
    text = "\n".join("".join(c["source"]) for c in notebook["cells"])
    for pin in ("'notebook': '<removed-run-record>, version 3'", "BENCH_FROM = f'{CW}/kaggle/judge-bench-public.json'",
                "JUDGE_VOTES = '2'", "'JUDGE_VOTES': JUDGE_VOTES", "shutil.copyfile(BENCH_FROM, BENCH_JSON)",
                "shutil.copyfile(f'{OUT}/plan.json', '/kaggle/working/plan.json')", "/kaggle/working/glimmer-letter.txt",
                "OUT = f'{CW}/sample'", "-DCMAKE_CUDA_ARCHITECTURES=75"):
        assert pin in text, pin
    team = "The Kaggle notebook was run by the author."
    assert text.count(team) == 2  # the first cell and <removed-run-record>'s "team"


def test_writers_table_prices_each_letter_from_its_run_record_and_marks_what_it_cannot_check():
    """writers_table.py on fixture records: Kaggle costs $0, Fireworks and the Meta API are tokens x the quoted price
    (cached prompt at the cached price), an unpriced model is NOT CHECKED, and kaggle/open-weights.md holds the table
    as the committed records produce it now."""
    import tempfile
    from pathlib import Path
    import writers_table
    kaggle = {"nvidia_smi": "| 0 Tesla T4 |\n| 1 Tesla T4 |", "pack_py_s": 313, "model": {"repo": "meta-models/x"},
              "letter": {"writer": "Muse Glimmer 30B (open weights, self-hosted)", "tries": 2, "judged_by": None,
                         "unmeasured": [], "unsupported": [], "usage": {"prompt_tokens": 962, "completion_tokens": 2263}}}
    fireworks = {"model": "accounts/fireworks/models/muse-spark-open", "host": "api.fireworks.ai", "wall_s": 55.5,
                 "tries": 1, "usage": {"prompt_tokens": 1000, "completion_tokens": 2000, "prompt_tokens_details": {
                     "cached_tokens": 600}, "completion_tokens_details": {"reasoning_tokens": 1500}}}
    meta = {"model": "muse-spark-1.3", "host": "api.meta.ai", "wall_s": 20, "tries": 3, "judged_by": None,
            "unmeasured": ["40"], "usage": {"input_tokens": 1000000, "output_tokens": 1000000,
                                            "output_tokens_details": {"reasoning_tokens": 7}}}
    unknown = {"model": "some-model", "host": "example.com", "tries": 3, "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for i, record in enumerate((kaggle, fireworks, meta, unknown)):
            paths.append(Path(tmp) / f"{i}.json")
            paths[-1].write_text(json.dumps(record))
        lines = writers_table.table(paths)
    assert lines[2] == ("| Muse Glimmer 30B | yes | Kaggle, 2 x Tesla T4, self-hosted | 313 | 962 (not reported) | 2,263 "
                        "| not reported | 2 | passed | none ran | $0 (free Kaggle GPU quota) |")
    assert lines[3] == ("| Muse Spark Open | yes | Fireworks (serverless) | 55.5 | 1,000 (600) | 2,000 | 1,500 | 1 "
                        "| passed | NOT RECORDED | $0.0091 |")  # (400x1.25 + 600x0.15 + 2000x4.25) / 1M
    assert lines[4] == ("| Muse Spark | no | Meta API | 20 | 1,000,000 (not reported) | 1,000,000 | 7 | 3 | failed: 1 left "
                        "| none ran | $5.5000 |")
    assert lines[5].endswith("| 3 | NOT RECORDED | NOT RECORDED | NOT CHECKED |") and "example.com" in lines[5]
    assert all(line.count("|") == lines[0].count("|") for line in lines[1:6])
    doc = Path(__file__).with_name("kaggle").joinpath("open-weights.md").read_text()
    assert "\n".join(writers_table.table(writers_table.RECORDS)) in doc


def chat_reply(name=None, arguments="{}", tokens=(2000, 100)):
    """A Chat Completions reply, as Fireworks sends one: a tool call (or plain text with reasoning_content) and usage."""
    message = {"role": "assistant", "content": None if name else "I will track first.", "reasoning_content": "Think."}
    if name:
        message["tool_calls"] = [{"id": f"tc-{name}", "type": "function",
                                  "function": {"name": name, "arguments": arguments}}]
    return {"id": "chatcmpl-1", "choices": [{"message": message, "finish_reason": "tool_calls" if name else "stop"}],
            "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1],
                      "completion_tokens_details": {"reasoning_tokens": 40}}}


def open_agent(server, model="accounts/fireworks/models/muse-spark-open", key=""):
    """Points openagent at the fake server; returns the old settings for restore_agent."""
    import openagent
    old = openagent.URL, openagent.MODEL, openagent.KEY
    openagent.URL, openagent.MODEL, openagent.KEY = f"http://127.0.0.1:{server.server_port}/v1", model, key
    return old


def restore_agent(old, server):
    import openagent
    openagent.URL, openagent.MODEL, openagent.KEY = old
    server.shutdown()
    server.server_close()


def test_case_agent_on_open_weights_works_the_case_to_the_tape_measure():
    """AGENT_MODEL_URL: the turns go to an OpenAI-compatible server (a local fake of Fireworks): an HTTP error pauses
    the case, plain text with reasoning_content is sent back, a malformed call is reported and recovered from, and
    the case stops for a tape measure; every turn's model, usage and wall time are logged, and the page names the
    model. The case cannot then resume on Muse Spark."""
    import agent, contextlib, io, openagent, tempfile
    replies = [500, chat_reply(), chat_reply("track", '{"people": "video"'),
               chat_reply("track", '{"people": "video", "vehicles": "video"}'), chat_reply("measure"),
               chat_reply("request_measurement")]
    server, seen = fake_open_model(replies)
    old, old_tracker = open_agent(server), agent.run_tracker
    agent.run_tracker = lambda p, site: {"person": [0, 1]}
    try:
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            out, _, _ = agent_case(folder)
            run = lambda: agent.work(out / "video.mp4", out / "site.json", out, "meta-key")
            assert run() == "paused" and run() == "needs_input"
            progress = json.loads((out / "case" / "progress.json").read_text())
            log = [json.loads(line) for line in (out / "case" / agent.LOG).read_text().splitlines()]
            section = agent.case_section(out)
            label = openagent.label()
            openagent.URL = ""
            switched = stopped(run)
    finally:
        agent.run_tracker = old_tracker
        restore_agent(old, server)
    bodies = [body for _, body, _ in seen]
    assert replies == [] and all(path == "/v1/chat/completions" for path, _, _ in seen) and len(bodies) == 6
    assert all(b["model"] == "accounts/fireworks/models/muse-spark-open" and b["parallel_tool_calls"] is False
               and b["tool_choice"] == "required" and b["messages"][0] == {"role": "system", "content": agent.INSTRUCTIONS}
               for b in bodies)
    assert [t["function"]["name"] for t in bodies[0]["tools"]] == [t["name"] for t in agent.TOOLS]
    assert bodies[0]["tools"][0]["function"]["parameters"]["required"] == ["people", "vehicles"]
    assert bodies[2]["messages"][-1] == {"role": "user", "content": agent.NUDGE}  # plain text: told to call a tool
    assert not any("reasoning_content" in m for b in bodies for m in b["messages"])
    bad, told = bodies[3]["messages"][-2:]
    assert bad["tool_calls"][0]["function"]["arguments"] == "{}" and told["tool_call_id"] == bad["tool_calls"][0]["id"]
    assert "track failed" in json.loads(told["content"])["summary"]
    assert '"people": "video", "vehicles": "video"' in bodies[4]["messages"][-2]["tool_calls"][0]["function"]["arguments"]
    turns = [s for s in log if "turn" in s]
    assert progress["status"] == "needs_input" and progress["requests"][0]["kind"] == "measurement"
    assert progress["agent_model"] == label == "Muse Spark Open (open weights, self-hosted)" and len(turns) == 5
    assert all(s["model"] == label and s["usage"]["prompt_tokens"] == 2000 and isinstance(s["wall_s"], float)
               for s in turns)
    assert "Paused: the model call failed (HTTP Error 500" in log[0]["summary"]
    assert abs(progress["usd"] - 5 * (2000 * 1.25 + 100 * 4.25) / 1e6) < 1e-9
    assert f"{label} chose one tool per turn: 5 turns" in section and "list price for accounts/fireworks/models" in section
    assert "is a case Muse Spark Open (open weights, self-hosted) worked, not Muse Spark" in switched
    assert openweights_label_on_fireworks() == "Muse Spark Open (open weights, on Fireworks)"


def openweights_label_on_fireworks():
    import openweights
    return openweights.label("https://api.fireworks.ai/inference/v1", "accounts/fireworks/models/muse-spark-open")


def test_case_agent_on_open_weights_keeps_its_turn_and_dollar_caps_at_the_fireworks_price():
    """The $1 cap prices the open model's turns at writers_table's quoted Fireworks price; the turn cap pauses; a
    model with no quoted price stops before any turn."""
    import agent, contextlib, io, openagent, tempfile
    server, seen = fake_open_model([chat_reply(), chat_reply(), chat_reply(tokens=(10000, 1000))])
    old, caps = open_agent(server), (agent.MAX_TURNS, agent.MAX_USD)
    try:
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            out, _, _ = agent_case(folder)
            run = lambda: agent.work(out / "video.mp4", out / "site.json", out, "key")
            agent.MAX_TURNS = 2
            assert run() == "paused" and len(seen) == 2
            agent.MAX_USD = 0.01  # two turns cost $0.0059, the third $0.0168 more
            assert run() == "over_budget" and len(seen) == 3 and raises_system_exit(run)
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            out, _, _ = agent_case(folder)
            openagent.MODEL = "some-unpriced-model"
            unpriced = stopped(lambda: agent.work(out / "video.mp4", out / "site.json", out, "key"))
    finally:
        agent.MAX_TURNS, agent.MAX_USD = caps
        restore_agent(old, server)
    assert "quotes no price for some-unpriced-model" in unpriced and len(seen) == 3


def test_case_agent_on_open_weights_sends_no_key_to_another_host():
    """FIREWORKS_API_KEY goes only to Fireworks' API, the Meta key never to the open model's server; a key set with
    AGENT_MODEL_KEY goes to that server."""
    import agent, contextlib, io, openagent, openweights, os, tempfile
    server, seen = fake_open_model([chat_reply(), chat_reply()])
    old, old_env = open_agent(server), os.environ.get("FIREWORKS_API_KEY")
    os.environ["FIREWORKS_API_KEY"] = "fw-test-secret"
    try:
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            out, _, _ = agent_case(folder)
            agent.MAX_TURNS, caps = 1, agent.MAX_TURNS
            try:
                agent.work(out / "video.mp4", out / "site.json", out, "meta-secret")
                openagent.KEY = "agent-secret"
                agent.work(out / "video.mp4", out / "site.json", out, "meta-secret")
            finally:
                agent.MAX_TURNS = caps
        to_fireworks = openweights.server_key("https://api.fireworks.ai/inference/v1", "")
    finally:
        os.environ.pop("FIREWORKS_API_KEY")
        if old_env is not None:
            os.environ["FIREWORKS_API_KEY"] = old_env
        restore_agent(old, server)
    sent = [json.dumps(body) + json.dumps(headers) for _, body, headers in seen]
    assert len(sent) == 2 and not any("fw-test-secret" in s or "meta-secret" in s for s in sent)
    assert "Authorization" not in seen[0][2] and seen[1][2]["Authorization"] == "Bearer agent-secret"
    assert to_fireworks == "fw-test-secret"


def test_case_agent_without_agent_model_url_talks_to_muse_spark_as_before():
    """The default path: the Responses API body as before, the log and page name Muse Spark at its Meta API price,
    and a case saved before AGENT_MODEL_URL existed resumes on Spark."""
    import agent, contextlib, io, openagent, tempfile
    bodies, old = [], (agent.spark_turn, agent.MAX_TURNS, openagent.URL)
    agent.spark_turn, agent.MAX_TURNS, openagent.URL = scripted_spark([None, None], bodies), 1, ""
    try:
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            out, _, _ = agent_case(folder)
            run = lambda: agent.work(out / "video.mp4", out / "site.json", out, "key")
            assert run() == "paused"
            saved = out / "case" / "progress.json"
            progress = json.loads(saved.read_text())
            saved.write_text(json.dumps({k: v for k, v in progress.items() if k != "agent_model"}))
            assert run() == "paused" and len(bodies) == 2
            log = [json.loads(line) for line in (out / "case" / agent.LOG).read_text().splitlines()]
            section = agent.case_section(out)
    finally:
        agent.spark_turn, agent.MAX_TURNS, openagent.URL = old
    assert set(bodies[0]) == {"model", "instructions", "input", "tools", "parallel_tool_calls", "store", "reasoning"}
    assert bodies[0]["model"] == "muse-spark-1.3" and bodies[0]["tools"] == agent.TOOLS
    assert progress["agent_model"] == "Muse Spark" and all(s["model"] == "Muse Spark" for s in log if "turn" in s)
    assert log[0]["input_tokens"] == 2000 and log[0]["usage"] == {"input_tokens": 2000, "output_tokens": 100}
    assert f"Muse Spark chose one tool per turn: 2 turns, about $0.01, estimated at the {agent.PRICE}" in section


def test_case_agent_asks_a_person_when_the_same_tool_fails_twice_in_a_row():
    """On a case with no video, track failed about 20 turns running (provenance/spark-open-agent-sample.json): two
    failures of the same tool in a row now stop the case with a tool_failed request; a success in between does not."""
    import agent, contextlib, io, tempfile
    track = ("track", {"people": "video", "vehicles": "video"})
    outcomes = []
    def tracker(p, site):
        if outcomes.pop(0):
            raise ValueError("no video")
        return {}
    old = agent.spark_turn, agent.run_tracker, agent.MAX_TURNS
    agent.run_tracker = tracker
    try:
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            out, _, _ = agent_case(folder)
            outcomes[:], agent.spark_turn = [True, True], scripted_spark([track, track], [])
            assert agent.work(out / "video.mp4", out / "site.json", out, "key") == "needs_input"
            stopped = json.loads((out / "case" / "progress.json").read_text())
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            out, _, _ = agent_case(folder)
            outcomes[:], agent.MAX_TURNS = [True, False, True], 3
            agent.spark_turn = scripted_spark([track, track, track], [])
            assert agent.work(out / "video.mp4", out / "site.json", out, "key") == "paused"
            kept_going = json.loads((out / "case" / "progress.json").read_text())
    finally:
        agent.spark_turn, agent.run_tracker, agent.MAX_TURNS = old
    request = stopped["requests"][-1]
    assert stopped["turn"] == 2 and request["kind"] == "tool_failed" and request["answer"] is None
    assert "track failed" in request["question"] and "no video" in request["question"]
    assert kept_going["turn"] == 3 and kept_going["requests"] == [] and kept_going["failures"] == 1


def test_letter_provenance_records_the_judge_or_what_the_checks_left():
    """letter-provenance.json keeps who judged a letter that passed, and what the checks left on one kept after the
    last try, so writers_table no longer prints NOT RECORDED for a judged run."""
    import contextlib, io, tempfile
    from pathlib import Path
    import writers_table
    good = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "PET 0.4 s."}
    reply = {"id": "fw-1", "usage": {"prompt_tokens": 9, "completion_tokens": 3},
             "choices": [{"message": {"content": json.dumps(good)}, "finish_reason": "stop"}]}
    server, _ = fake_open_model([reply] * (1 + pack.LETTER_TRIES))
    verdicts = ['{"problems": []}'] + ['{"problems": ["Says a warrant is met."]}'] * pack.LETTER_TRIES
    names = "LETTER_URL", "LETTER_MODEL", "LETTER_KEY", "JUDGE_URL", "spark_reply"
    old = [getattr(pack, n) for n in names]
    pack.LETTER_URL, pack.LETTER_MODEL, pack.LETTER_KEY, pack.JUDGE_URL = (
        f"http://127.0.0.1:{server.server_port}/v1", SPARK_OPEN, "", "")
    pack.spark_reply = lambda prompt, image, key: verdicts.pop(0)
    records = []
    try:
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
                pack.new_plan(Path(tmp), "PROMPT", '{"pet_s": 0.4}', "key", None)
                records.append(json.loads((Path(tmp) / pack.PROVENANCE).read_text()))
    finally:
        for n, value in zip(names, old):
            setattr(pack, n, value)
        server.shutdown()
        server.server_close()
    passed, kept = records
    assert passed["judged_by"] == pack.JUDGE and "unsupported" not in passed
    assert "judged_by" not in kept and kept["tries"] == pack.LETTER_TRIES
    assert (kept["unmeasured"], kept["mixed"], kept["unsupported"]) == ([], [], ["Says a warrant is met."])
    assert writers_table.judge_check(passed) == pack.JUDGE and writers_table.judge_check(kept) == "failed: 1 left"
    assert writers_table.judge_check({"tries": 1}) == "NOT RECORDED"
    sample = json.loads(Path(__file__).with_name("provenance").joinpath("spark-open-fireworks-sample.json").read_text())
    assert sample["judged_by"] == pack.JUDGE  # from that run's plan.json, same letter sha256


def test_writers_table_says_passed_for_a_letter_kept_on_its_first_try():
    """A record without the checks' lists: a letter kept on try 1 plainly passed; one kept on a later try (but before
    the last) passed too, as ask_plan returns early only then; on the last try it is not known."""
    import writers_table
    assert writers_table.number_check({}, 1) == "passed"
    assert writers_table.number_check({}, 2) == "passed (kept before the last try)"
    assert writers_table.number_check({}, pack.LETTER_TRIES) == writers_table.number_check({}, None) == "NOT RECORDED"
    assert writers_table.number_check({"unmeasured": ["40"], "mixed": []}, 1) == "failed: 1 left"


def test_muse_spark_letter_records_its_wall_time_and_tokens_like_an_open_weights_one():
    """Without LETTER_MODEL_URL, Muse Spark's Responses API usage and the measured wall seconds go into plan.json and
    letter-provenance.json, so writers_table shows Spark's time, tokens and cost too. A fake Meta API, no network."""
    import contextlib, io, sam, tempfile
    from pathlib import Path
    import writers_table
    good = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "PET 0.4 s."}
    usage = {"input_tokens": 1000, "output_tokens": 500, "input_tokens_details": {"cached_tokens": 200},
             "output_tokens_details": {"reasoning_tokens": 300}}
    said = lambda text: [{"type": "reasoning", "summary": []},
                         {"type": "message", "content": [{"type": "output_text", "text": text}]}]
    server, seen = fake_open_model([{"id": "resp-1", "usage": usage, "output": said(json.dumps(good))},
                                    {"id": "resp-2", "usage": {"input_tokens": 1}, "output": said('{"problems": []}')}])
    names = "LETTER_URL", "JUDGE_URL"
    old = [getattr(pack, n) for n in names] + [sam.API_URL]
    pack.LETTER_URL = pack.JUDGE_URL = ""
    sam.API_URL = f"http://127.0.0.1:{server.server_port}/v1/responses"
    try:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            plan = pack.new_plan(Path(tmp), "PROMPT", '{"pet_s": 0.4}', "spark-key-1", None)
            record = json.loads((Path(tmp) / pack.PROVENANCE).read_text())
    finally:
        pack.LETTER_URL, pack.JUDGE_URL, sam.API_URL = old
        server.shutdown()
        server.server_close()
    assert len(seen) == 2 and plan["usage"] == usage and isinstance(plan["wall_s"], float)  # the letter's, not the judge's
    assert record == {"model": "muse-spark-1.3", "host": "127.0.0.1", "request_id": "resp-1", "usage": usage,
                      "wall_s": plan["wall_s"], "timings": None, "response_format": "json_object", "tries": 1,
                      "judged_by": pack.JUDGE, "letter_sha256": pack.sha256(good["letter"])}
    assert "spark-key-1" not in json.dumps(record)
    row = writers_table.row({**record, "host": writers_table.META_HOST})  # $ (800x1.25 + 200x0.15 + 500x4.25) / 1M
    assert f"| Meta API | {plan['wall_s']} | 1,000 (200) | 500 | 300 | 1 | passed | {pack.JUDGE} | $0.0032 |" in row


def test_case_agent_on_open_weights_asks_for_a_tool_every_turn_and_falls_back_to_auto_on_400():
    """openagent sends tool_choice "required" (Fireworks documents it); a server that rejects it with HTTP 400 is asked
    again with "auto", and each turn's log says which one was answered. Another error still pauses the case."""
    import agent, contextlib, io, tempfile
    replies = [chat_reply("measure"), 400, chat_reply("measure"), 500]
    server, seen = fake_open_model(replies)
    old = open_agent(server)
    try:
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            out, _, _ = agent_case(folder)
            assert agent.work(out / "video.mp4", out / "site.json", out, "meta-key") == "paused"
            log = [json.loads(line) for line in (out / "case" / agent.LOG).read_text().splitlines()]
    finally:
        restore_agent(old, server)
    assert [body["tool_choice"] for _, body, _ in seen] == ["required", "required", "auto", "required"]
    assert [s.get("tool_choice") for s in log] == ["required", "auto", None]
    assert "HTTP Error 500" in log[-1]["summary"] and replies == []


def fake_transcriber(transcript):
    """A stand-in for Muse Voice Transcribe at voice.urllib.request.urlopen: keeps each request, answers `transcript`.
    Returns (requests, restore)."""
    import io
    import voice
    seen, old = [], voice.urllib.request.urlopen
    voice.urllib.request.urlopen = lambda req, timeout: (seen.append(req), io.BytesIO(json.dumps(
        {"sessionId": "s", "transcript": transcript, "audioDurationMs": 2000, "turns": []}).encode()))[1]
    return seen, lambda: setattr(voice.urllib.request, "urlopen", old)


def phone_audio(folder):
    """Two seconds of tone as a phone's .m4a, outside the pack folder."""
    import subprocess
    from pathlib import Path
    audio = Path(folder) / "principal.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-ac", "2",
                    "-c:a", "aac", str(audio)], check=True)
    return audio


def test_voice_notes_are_transcribed_shown_and_revise_the_letter_as_typed_notes_would():
    """--voice-notes: the phone's audio goes to api.meta.ai as the docs' WAV with a Hindi and English hint; the
    transcript reaches the notes path labelled as stated by the principal, is saved as notes-<sha8>.txt with the
    audio's sha256, and the page says the notes were spoken; the audio never lands in the pack or share/."""
    import hashlib, io, tempfile, voice, wave
    from email.parser import BytesParser
    from pathlib import Path
    spoken = "कृपया लिखिए कि हमारे 1,200 pupils हैं."
    draft = {"fix": "speed table", "why": "w", "image_prompt": "i", "writer": pack.WRITER,
             "letter": "Dear Sir. A car passed 0.5 s from a child. We ask for a speed table."}
    revised = {**draft, "letter": "Dear Sir. A car passed 0.5 s from one of our 1,200 pupils. We ask for a speed table."}
    seen, restore = fake_transcriber(spoken)
    try:
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as phone:
            audio = phone_audio(phone)
            digest = hashlib.sha256(audio.read_bytes()).hexdigest()
            out = pack_folder(folder)
            run_pack(out, ask=lambda prompt: draft)
            [(prompt, stated)] = run_pack(out, "--voice-notes", str(audio), key="meta-key", ask=lambda p: revised)
            assert prompt.endswith(f"NOTES:\n{spoken}") and stated == [spoken]
            assert (out / f"notes-{digest[:8]}.txt").read_text() == spoken + "\n"
            saved = json.loads((out / "plan.json").read_text())
            assert saved["notes"] == [spoken] and saved["spoken_notes"] == [{"audio_sha256": digest, "model": voice.MODEL}]
            page = (out / "index.html").read_text()
            assert "the principal's notes (spoken and transcribed by Muse Voice Transcribe). Read and approved by" in page
            audio_files = [p for p in Path(folder).rglob("*") if p.suffix in (".m4a", ".wav", ".opus")]
            assert audio_files == [] and audio.read_bytes() not in b"".join(
                p.read_bytes() for p in (out / "share").iterdir())
            assert len(run_pack(out, "--voice-notes", str(audio), key="meta-key", ask=lambda p: revised)) == 1
            assert len(seen) == 1  # the same audio again: its saved transcript, no second call
    finally:
        restore()
    [req] = seen
    assert req.full_url == "https://api.meta.ai/v1/asr/transcribe" and req.get_header("Authorization") == "Bearer meta-key"
    form = BytesParser().parsebytes(f"Content-Type: {req.get_header('Content-type')}\r\n\r\n".encode() + req.data)
    parts = {p.get_param("name", header="content-disposition"): p for p in form.get_payload()}
    request = json.loads(parts["request"].get_payload(decode=True))
    assert request["model"] == "muse-voice-transcribe-1.0" and request["languageBias"] == ["Hindi", "English"]
    assert parts["request"].get_content_type() == "application/json"
    with wave.open(io.BytesIO(parts["audio"].get_payload(decode=True))) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
    assert pack.spoken_line({"notes": ["a", "b"], "spoken_notes": [{}]}) == (
        " (1 of 2 spoken and transcribed by Muse Voice Transcribe)")


def test_an_empty_transcript_stops_with_a_clear_message_and_revises_nothing():
    import contextlib, io, sys, tempfile, voice
    draft = {"fix": "speed table", "why": "w", "image_prompt": "i", "writer": pack.WRITER, "letter": "Dear Sir. PET 0.5 s."}
    seen, restore = fake_transcriber("  ")
    try:
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as phone:
            audio = phone_audio(phone)
            out = pack_folder(folder)
            run_pack(out, ask=lambda prompt: draft)
            before = (out / "plan.json").read_text()
            try:
                run_pack(out, "--voice-notes", str(audio), key="meta-key", ask=lambda p: 1 / 0)
                stopped = None
            except SystemExit as stop:
                stopped = str(stop)
            assert stopped and "heard no words in principal.m4a: nothing was revised" in stopped
            assert (out / "plan.json").read_text() == before and not list(out.glob("notes-*.txt")) and len(seen) == 1
            assert exits(lambda: run_pack(out, "--voice-notes", str(audio), "--notes", str(audio)))
            with contextlib.redirect_stderr(io.StringIO()):
                assert raises_system_exit(lambda: voice.spoken_notes(audio, out, None))  # no key: nothing sent
            assert len(seen) == 1
    finally:
        restore()


def test_hindi_copy_holds_exactly_the_english_letters_numbers():
    """hindi.mismatch: Devanagari digits read as digits; a changed, missing or added number, or a number in words of
    either language, is refused; a word that only holds a number word (विचार, दोनों) is not."""
    import hindi
    check = lambda text: hindi.mismatch("A car at 30.0 km/h passed 0.5 s from one of our 1,200 pupils.", text,
                                        pack.NUMBER, pack.NUMBER_WORD)
    assert check("एक कार ३०.० km/h पर हमारे 1200 विद्यार्थियों में से एक से ०.५ s दूर से निकली। इस पर विचार करें, दोनों ओर।") == ""
    assert check("एक कार 35.0 km/h पर 1,200 विद्यार्थियों में से एक से 0.5 s दूर से निकली।") == (
        "missing 30; not in the English letter: 35")
    assert check("एक कार 30.0 km/h पर 0.5 s दूर से निकली।") == "missing 1200"
    assert check("30.0 km/h, 0.5 s, 1,200 विद्यार्थी, दो बार, two cars") == "numbers in words: two, दो"


def test_hindi_copy_goes_back_while_its_numbers_differ_and_stops_after_three_tries():
    import hindi
    letter = "A car at 30.0 km/h passed 0.5 s from a child."
    good, bad = '{"letter_hi": "एक कार ३०.० km/h पर एक बच्चे से ०.५ s दूर से निकली।"}', '{"letter_hi": "कार 31 km/h, 0.5 s"}'
    prompts, replies = [], ["no json", bad, good]
    ask = lambda prompt: (prompts.append(prompt), replies.pop(0))[1]
    assert hindi.translate(letter, ask, pack.NUMBER, pack.NUMBER_WORD) == (json.loads(good)["letter_hi"], "")
    assert letter in prompts[0] and "could not be read" in prompts[1] and "(missing 30; not in the English letter: 31)" in prompts[2]
    prompts.clear()
    text, why = hindi.translate(letter, lambda p: (prompts.append(p), bad)[1], pack.NUMBER, pack.NUMBER_WORD)
    assert text == "" and len(prompts) == hindi.TRIES == 3 and "missing 30" in why


def test_hindi_copy_is_shown_under_the_letter_and_signed_with_it():
    """site "hindi_copy": true: the writer translates the checked English letter once; the page shows the copy under
    it; the sign-off's sha covers both, so a changed Hindi copy reads as changed after sign-off. A copy whose numbers
    never match leaves the English letter only, said on the page; a signing run asks for no copy."""
    import datetime, tempfile
    draft = {"fix": "speed table", "why": "w", "image_prompt": "i", "writer": pack.WRITER,
             "letter": "Dear Sir. A car at 30.0 km/h passed 0.5 s from a child. We ask for a speed table."}
    hindi_letter = "महोदय। एक कार ३०.० km/h पर एक बच्चे से ०.५ s दूर से निकली। हम स्पीड टेबल का अनुरोध करते हैं।"
    sign = ["--approved-by", "A. Rao, Principal", "--school", "Gate School"]
    asked, old = [], pack.spark_reply
    try:
        with tempfile.TemporaryDirectory() as folder:
            out = pack_folder(folder)
            site = json.loads((out / "site.json").read_text())
            (out / "site.json").write_text(json.dumps({**site, "hindi_copy": True}))
            pack.spark_reply = lambda prompt, image, key: (asked.append(prompt), json.dumps({"letter_hi": hindi_letter}))[1]
            run_pack(out, ask=lambda p: draft, key="meta-key")
            plan = json.loads((out / "plan.json").read_text())
            assert plan["letter"] == draft["letter"] and plan["letter_hi"] == hindi_letter and len(asked) == 1
            assert draft["letter"] in asked[0] and "never write a number in words" in asked[0]
            page = (out / "index.html").read_text()
            assert (f"Hindi copy, translated by {pack.WRITER}, numbers checked against the English letter</h3>"
                    f'<div class="letter" lang="hi"><p>{hindi_letter}</p>') in page
            assert page.index('lang="hi"') > page.index('contenteditable') and ".hindi-copy { break-before: page; }" in page
            assert run_pack(out, key="meta-key") == [] and len(asked) == 1  # a re-run pays nothing
            run_pack(out, *sign)
            record = json.loads((out / "signoff.json").read_text())
            assert record["letter_sha256"] == pack.signed_sha(plan) != pack.sha256(draft["letter"])
            assert "Read and approved by: A. Rao, Principal" in (out / "index.html").read_text()
            (out / "plan.json").write_text(json.dumps({**plan, "letter_hi": hindi_letter.replace("३०.०", "३५.०")}))
            run_pack(out)
            today = datetime.date.today().isoformat()
            assert f"Changed after sign-off by A. Rao, Principal on {today}, not signed." in (out / "index.html").read_text()
        with tempfile.TemporaryDirectory() as folder:
            out = pack_folder(folder)
            site = json.loads((out / "site.json").read_text())
            (out / "site.json").write_text(json.dumps({**site, "hindi_copy": True}))
            asked.clear()
            pack.spark_reply = lambda prompt, image, key: (asked.append(prompt), '{"letter_hi": "कार 31 km/h"}')[1]
            run_pack(out, ask=lambda p: draft, key="meta-key")
            plan = json.loads((out / "plan.json").read_text())
            assert len(asked) == 3 and "letter_hi" not in plan and "missing 0.5, 30" in plan["letter_hi_failed"]
            assert "No Hindi copy, send the English letter: no translation kept" in (out / "index.html").read_text()
            assert run_pack(out, key="meta-key") == [] and len(asked) == 3  # tried once per letter
        with tempfile.TemporaryDirectory() as folder:
            out = pack_folder(folder)
            run_pack(out, ask=lambda p: draft, key="meta-key")
            site = json.loads((out / "site.json").read_text())
            (out / "site.json").write_text(json.dumps({**site, "hindi_copy": True}))
            asked.clear()
            run_pack(out, *sign, key="meta-key")  # the principal reads a copy before signing it: none made here
            assert asked == [] and "letter_hi" not in json.loads((out / "plan.json").read_text())
            assert json.loads((out / "signoff.json").read_text())["letter_sha256"] == pack.sha256(draft["letter"])
    finally:
        pack.spark_reply = old


def test_crowd_tracker_keeps_a_walker_hidden_behind_a_car_for_1_4_s():
    import crowd
    box = lambda x: [x, 100, x + 20, 160]  # 20x60 px walker, sampled every 2 frames at 10 fps
    seen = {f: [box(10 * f)] for f in range(0, 22, 2)}  # walks at 10 px a frame, then stops behind a car
    seen.update({f: [box(200)] for f in range(34, 44, 2)})  # out again 1.4 s later, 140 px short of the guess
    tracks = crowd.associate(seen, 10)
    assert len(tracks) == 1 and len(next(iter(tracks.values()))) == 16
    stranger = {**seen, 34: [box(600)]}  # someone else 400 px past the hidden walker: never stitched on
    assert len(crowd.associate({f: b for f, b in stranger.items() if f <= 34}, 10)) == 2


def test_a_piece_that_never_moves_is_no_conflict_however_short():
    fps, frames = 10, 40  # 4 s, far below STILL_RUN_S: the windowed rule alone would keep it
    car = {"car#1": edges_along_x(8.0, fps, frames)}
    pole = {"p/0": {f: (0.1 * (f % 3), 0.0) for f in range(frames)}}  # foot jitter within 0.2 m
    assert road.conflicts(pole, car, fps) == []
    walker = {"p/0": {f: (0.0, -1.0 + 0.05 * f) for f in range(frames)}}  # 2 m across the car's path
    assert [e["person"] for e in road.conflicts(walker, car, fps)] == ["p/0"]


def test_walking_motion_overrules_sparks_not_a_person_and_a_fast_rider_needs_no_bike_box():
    """A "not a person" piece walking 1.5-8 km/h over 2 m is kept (review_disputed) and named on the page, unless
    another piece walks beside it (a shadow); a rider call over 8 km/h stands without a bike box."""
    import analyze
    walker = {f: (0.1 * f, 0.0) for f in range(100)}  # 3.6 km/h at analyze.FPS = 10, 9.9 m
    shadow = {f: (0.1 * f, 0.6) for f in range(100)}
    still = {f: (5.0, 5.0) for f in range(100)}
    no = {"is_person": False, "road_user": "not a person", "reason": "a shadow"}
    kmh, moved, beside = analyze.motion({"w/0": walker, "s/0": still}, "w/0")
    assert review.WALK_KMH[0] <= kmh <= review.WALK_KMH[1] and moved >= review.WALK_MIN_M and not beside
    kept = review.gated(no, {}, [], kmh, moved, beside)
    assert kept["is_person"] and kept["review_disputed"] and "Spark thought not a person" in review.unconfirmed_rider(kept)
    assert analyze.motion({"w/0": walker, "s/0": shadow}, "w/0")[2] is True
    assert review.gated(no, {}, [], kmh, moved, True) == no  # side by side: the shadow rule stands
    assert review.gated(no, {}, [], *analyze.motion({"s/0": still}, "s/0")) == no  # standing still: not overruled
    rider = {"is_person": False, "road_user": "cyclist", "reason": "on a bike"}
    assert review.gated(rider, {}, [], review.RIDE_KMH + 2) == rider
    assert review.gated(rider, {}, [], kmh)["rider_unconfirmed"] is True


if __name__ == "__main__":
    for name, check in list(globals().items()):
        if name.startswith("test_"):
            check()
            print("pass", name)
