"""Self-check for road geometry, PET and SAM parsing. Run: python3 test_cw.py"""
import math

import listen
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


def raises_value_error(call):
    try:
        call()
    except ValueError:
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


def test_spark_verdicts_are_validated():
    ok = review.read_verdict('Sure: {"cyan_is_a_person": false, "road_user": "not a person", "reason": "a pole"}')
    assert ok == {"is_person": False, "road_user": "not a person", "reason": "a pole"}
    assert review.read_verdict('{"cyan_is_a_person": "yes", "road_user": "adult"}') is None
    assert review.read_verdict('{"cyan_is_a_person": true, "road_user": "alien"}') is None
    assert review.read_verdict("no json") is None and review.read_verdict("[1, 2]") is None
    assert review.read_verdict('{"cyan_is_a_person": true, "road_user": "not a person"}')["is_person"] is False


def test_pack_keeps_people_and_escapes_text():
    base = {"person": "1/0", "vehicle": "car#1", "vehicle_kmh": 30.0, "pet_s": 0.5, "t_person_s": 3.0, "gap_m": 0.4, "death_risk_pct": 1.5,
            "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5}, "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    pole = base | {"person": "9/0", "review": {"is_person": False, "road_user": "not a person", "reason": "pole"}}
    pole_again = base | {"person": "9/0", "vehicle": "car#2"}  # same pole, another car, never reviewed
    child = base | {"review": {"is_person": True, "road_user": "child", "reason": "<script>x</script>"}}
    unreviewed = base | {"person": "2/0"}
    assert pack.confirmed([pole, child, pole_again, unreviewed]) == [child, unreviewed]
    card = pack.event_card(1, child)
    assert "&lt;script&gt;" in card and "<script>" not in card and "from a child" in card
    assert "from a pedestrian" in pack.event_card(2, base | {"review": {"is_person": True, "road_user": "unclear"}})


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
    assert seen == {"minutes": 1.0, "crossings": 1, "vehicles": 1, "speed_85th_kmh": 28.8}
    tiles = pack.stats([], seen)
    assert "pedestrian crossings watched" in tiles and "85% of vehicles" in tiles and "conflicts per 100" in tiles


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


def test_sam_text_parses_into_tracks():
    text = ("<0f>0<|box;x1=1.0;y1=2.0;x2=3.0;y2=4.0;w=640;h=360|><|mask...|>1<|box;x1=5;y1=6;x2=7;y2=8;w=640;h=360|>"
            "<1f>0<|box;x1=1.5;y1=2.5;x2=3.5;y2=4.5;w=640;h=360|>")
    assert sam.parse(text) == {"0": {0: [1.0, 2.0, 3.0, 4.0], 1: [1.5, 2.5, 3.5, 4.5]}, "1": {0: [5.0, 6.0, 7.0, 8.0]}}
    assert sam.parse("<0f>0<|box;x1=5;y1=6;x2=5;y2=8;w=640;h=360|>") == {}  # zero-width box dropped


if __name__ == "__main__":
    for name, check in list(globals().items()):
        if name.startswith("test_"):
            check()
            print("pass", name)
