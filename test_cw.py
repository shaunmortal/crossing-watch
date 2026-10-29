"""Self-check for road geometry, PET and SAM parsing. Run: python3 test_cw.py"""
import json
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


def test_page_links_find_an_event_card_and_its_moment():
    """A page link to #event-N finds card N, and data-t is when, in its clip, the near-miss begins."""
    e = {"vehicle": "car#1", "vehicle_kmh": 30.0, "pet_s": 2.5, "t_person_s": 6.0, "t_vehicle_s": 3.5, "gap_m": 0.4,
         "death_risk_pct": 1.5, "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5},
                                               "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    assert '<article class="card" id="event-3" data-t="2.00">' in pack.event_card(3, e, 10)  # clip starts at 1.5 s
    assert 'data-t="1.00"' in pack.event_card(1, e | {"t_vehicle_s": 1.0}, 10)  # clip starts at 0, not -1 s


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
    tiles = pack.stats([], seen)
    assert "pedestrian crossings watched" in tiles and "85% of vehicles" in tiles and "conflicts per 100" in tiles



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
    assert "about $6.00 of it image detection, at Meta&#x27;s list prices" in crowd and "guess" not in crowd
    import analyze, contextlib, io  # Meta's list price for SAM images is $2.50 per 1,000
    with contextlib.redirect_stdout(io.StringIO()):
        assert analyze.check_cost([(0, None, None)], [], None, 100, False, images=1000, all_images=1000) == 2.5
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



def test_letters_quoting_unmeasured_numbers_go_back_to_spark():
    facts = '{"pet_s": 0.4, "vehicle_kmh": 27.3, "at_20_kmh_limit": {"death_risk_pct": 0.6}}'
    assert pack.unmeasured("PET 0.4 s at 27.3 km/h; a 20 km/h limit; 3 times this week", facts) == ["3"]
    good = {"fix": "speed table", "why": "cars at 27.3 km/h", "image_prompt": "add a speed table", "letter": "PET 0.4 s."}
    replies, prompts = [{**good, "letter": "It happened 12 times."}, good], []
    old = pack.model_plan, pack.judge_problems
    pack.model_plan = lambda prompt, key, photo=None, known=None: (prompts.append(prompt), replies.pop(0))[1]
    pack.judge_problems = lambda letter, measured, key: []
    try:
        assert pack.ask_plan("PROMPT", facts, "key") == {**good, "writer": pack.WRITER, "judged_by": pack.JUDGE}
        assert "12" in prompts[1] and "not in the measurements" in prompts[1]
        replies[:] = [{**good, "letter": "It happened 12 times."}] * pack.LETTER_TRIES
        stubborn = pack.ask_plan("PROMPT", facts, "key")
    finally:
        pack.model_plan, pack.judge_problems = old
    assert stubborn["unmeasured"] == ["12"] and "12" in pack.letter_section(stubborn)


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


def test_pack_saves_the_letter_plan_next_to_the_page():
    import contextlib, io, sys, tempfile
    from pathlib import Path
    e = {"person": "1/0", "vehicle": "car#1", "tier": "serious", "pet_s": 0.5, "vehicle_kmh": 30.0, "death_risk_pct": 1.5,
         "t_person_s": 3.0, "t_vehicle_s": 3.5, "gap_m": 0.4, "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5},
                                                                         "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    plan = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "PET 0.5 s, स्कूल.", "writer": "Muse Spark"}
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder)
        (out / "events.json").write_text(json.dumps({"fps": 10, "exposure": {"minutes": 0.3}, "events": [e]}))
        (out / "site.json").write_text(json.dumps({"name": "gate", "world_points": SQUARE_ROAD}))
        old = sys.argv, pack.optional_key, pack.street_photo, pack.ask_plan
        sys.argv = ["pack.py", folder, str(out / "site.json")]
        pack.optional_key, pack.street_photo = lambda: None, lambda *args: None  # no key, no network, no photo
        pack.ask_plan = lambda prompt, measured, key, photo: plan
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                pack.main()
        finally:
            sys.argv, pack.optional_key, pack.street_photo, pack.ask_plan = old
        assert json.loads((out / "plan.json").read_text()) == plan and "speed table" in (out / "index.html").read_text()


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
    """A local stand-in for llama-server: answers each POST with the next reply and keeps (path, body, headers)."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    seen = []

    class Fake(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))), dict(self.headers)))
            reply = json.dumps(replies.pop(0)).encode()
            self.send_response(200)
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
    server, seen = fake_open_model([{"choices": [{"message": {"content": json.dumps(plan)}, "finish_reason": "stop"}],
                                     "timings": timings, "usage": usage}])
    old = pack.LETTER_URL
    pack.LETTER_URL = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            photo = Path(tmp) / "street.jpg"
            photo.write_bytes(b"\xff\xd8jpeg")
            with contextlib.redirect_stderr(io.StringIO()):
                assert pack.model_plan("PROMPT", None, photo) == {**plan, "timings": timings, "usage": usage}
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
         "with_limit": {"20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
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
    judged, old = [], (pack.LETTER_URL, pack.judge_problems)
    pack.LETTER_URL = f"http://127.0.0.1:{server.server_port}/v1"
    pack.judge_problems = lambda letter, measured, key: judged.append(letter) or []
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            plan = pack.ask_plan("PROMPT", '{"pet_s": 0.4, "vehicle_kmh": 27.3}', "key")
    finally:
        pack.LETTER_URL, pack.judge_problems = old
        server.shutdown()
        server.server_close()
    first, second = (body for _, body, _ in seen)
    pattern = lambda body: body["response_format"]["json_schema"]["schema"]["properties"]["letter"]["pattern"]
    assert "not in the measurements: 12" in second["messages"][0]["content"][0]["text"]
    assert pattern(second) == pattern(first) and not re.fullmatch(pattern(second), "It happened 12 times.")
    assert plan["letter"] == good["letter"] and judged == [good["letter"]] and plan["judged_by"] == pack.JUDGE


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
                "k != 'MODEL_API_KEY'", "<removed-run-record>"):  # the Glimmer-only judge pass, skipped without a bench
        assert pin in text, pin
    assert re.search(r"assert sha256\(path\) == SHA256\[name\]", text)
    assert "shaunmortal" in text
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
    assert roadmap.svg([], [[0, 0], [1, 0], [1, 1], [0, 1]]) == ""
    site = {"world_points": [[-2, -2], [2, -2], [2, 2], [-2, 2]]}
    assert "Where it happened" in pack.map_section(events, site) and pack.map_section(events[2:], site) == ""


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


def test_number_check_reads_grouped_numbers_and_non_english_facts():
    facts = json.dumps({"vehicles_per_hour": 1200, "site": "स्कूल गेट"}, ensure_ascii=False)
    assert pack.unmeasured("1,200 vehicles an hour", facts) == []
    assert pack.unmeasured("about 2,000 an hour", facts) == ["2,000"]
    assert "0921" not in pack.facts({"name": "स्कूल"}, [], {"minutes": 1})  # no \\u escapes to hide digits in


def test_paths_and_other_arrays_never_reach_the_letter_facts():
    """Every number in the facts counts as measured, so arrays of coordinates would let a letter's numbers through."""
    e = {"person": "1/0", "vehicle": "car#1", "tier": "serious", "pet_s": 0.5, "vehicle_kmh": 30.0, "death_risk_pct": 1.5,
         "with_limit": {"20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}, "where": [41.7, 63.2],
         "path_person": [[57.9, 88.4]], "path_vehicle": [[77.3, 12.6]], "replay": [[71.1, 72.2]], "spans": [[13.7, 19.3]]}
    seen = {"minutes": 0.3, "crossings": 4, "spans": [[23.9, 31.7]], "replay": (44.4, 55.5)}
    text = pack.facts({"name": "gate"}, [e], seen)
    array_numbers = "41.7 63.2 57.9 88.4 77.3 12.6 71.1 72.2 13.7 19.3 23.9 31.7 44.4 55.5"
    assert pack.unmeasured(array_numbers, text) == sorted(array_numbers.split(), key=float)
    assert '"crossings": 4' in text and '"vehicle_kmh": 30.0' in text


def test_sam_text_parses_into_tracks():
    text = ("<0f>0<|box;x1=1.0;y1=2.0;x2=3.0;y2=4.0;w=640;h=360|><|mask...|>1<|box;x1=5;y1=6;x2=7;y2=8;w=640;h=360|>"
            "<1f>0<|box;x1=1.5;y1=2.5;x2=3.5;y2=4.5;w=640;h=360|>")
    assert sam.parse(text) == {"0": {0: [1.0, 2.0, 3.0, 4.0], 1: [1.5, 2.5, 3.5, 4.5]}, "1": {0: [5.0, 6.0, 7.0, 8.0]}}
    assert sam.parse("<0f>0<|box;x1=5;y1=6;x2=5;y2=8;w=640;h=360|>") == {}  # zero-width box dropped


def agent_case(folder):
    """A case folder for the agent: one measured near-miss, and a site whose check distance reads 7.0 m in the video."""
    from pathlib import Path
    out = Path(folder)
    e = {"person": "1/0", "vehicle": "car#1", "tier": "serious", "pet_s": 0.5, "vehicle_kmh": 30.0, "death_risk_pct": 1.5,
         "t_person_s": 3.0, "t_vehicle_s": 3.5, "gap_m": 0.4, "with_limit": {"30": {"impact_kmh": 30.0, "death_risk_pct": 1.5},
                                                                         "20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}}}
    (out / "events.json").write_text(json.dumps({"fps": 10, "exposure": {"minutes": 0.3}, "events": [e]}))
    site = {"name": "gate", "image_points": SQUARE_IMG, "world_points": SQUARE_ROAD, "vehicles": ["car"],
            "check": {"what": "kerb to kerb at the zebra", "points": [[100, 200], [240, 200]]}}  # 140 px at 20 px/m
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
    import agent, contextlib, io, tempfile
    submit = ("submit_letter", {"notes": ""})
    script = [("track", {"people": "video", "vehicles": "video"}), ("track", {"people": "crowd", "vehicles": "video"}),
              None, submit, submit, submit, ("measure", {}), ("request_measurement", {}), submit,
              ("submit_letter", {"notes": "Name the school gate."})]
    bodies, tracked, prompts = [], [], []
    plan = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "PET 0.5 s.", "writer": "Muse Spark"}
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
            assert run(approve=True) == "done" and raises_system_exit(run)
            progress = json.loads((out / "case" / "progress.json").read_text())
            log = (out / "case" / "agent_log.jsonl").read_text().splitlines()
            page = (out / "index.html").read_text()
    finally:
        agent.spark_turn, agent.run_tracker, pack.ask_plan = old
    assert script == [] and len(bodies) == progress["turn"] == 10 and len(log) == 14  # 10 turns, 4 person steps
    assert all(b["parallel_tool_calls"] is False and b["store"] is False for b in bodies)
    assert {t["name"] for t in bodies[0]["tools"]} == set(agent.RUNNERS)
    assert bodies[3]["input"][-1] == {"role": "user", "content": agent.NUDGE}
    assert not any(item.get("type") == "reasoning" for b in bodies for item in b["input"])
    assert [r["kind"] for r in progress["requests"]] == ["letter_refused", "measurement"] and progress["tape_m"] == 7.2
    assert abs(progress["usd"] - 10 * (2000 * 1.25 + 100 * 4.25) / 1e6) < 1e-9
    assert '"tape_m": 7.2' in prompts[0] and '"video_m": 7.0' in prompts[0]  # measured, so the letter may quote it
    assert "How the agent worked this case" in page and "Video 7.0 m, tape 7.2 m, 3% off: proven" in page
    assert "Person: R2 answered: 7.2 m" in page and "approved" in page
    assert "off" in agent.letter_blocker({"tape_m": 9.0}, site, [e], "")  # 22% off: mark the calibration again
    assert "numbers" in agent.letter_blocker({"tape_m": 7.2, "tracked_with": agent.calibration(site)}, site, [e], "3")
    assert agent.tape_metres("720 cm") == agent.tape_metres(" 7.2M ") == 7.2
    assert all(raises_system_exit(lambda t=t: agent.tape_metres(t))
               for t in ("7 ft", "24 feet", "7,2 m", "1,200 cm", "2 m 20 cm", "720", "7.2 mm"))  # never read as metres


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
        (out / "events.json").write_text(json.dumps({"events": [{"vehicle_kmh": 87.9}, {"vehicle_kmh": 34.0}]}))
        (out / "jokes.txt").write_text("lol\n2\n500\n")
        old = sys.argv
        try:
            sys.argv = ["guess.py", str(out / "replies.txt"), str(out / "events.json"), "--event", "2"]
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                guess.main()
            assert "5 guesses, median 40 km/h. Measured: 34 km/h." in printed.getvalue()
            assert (out / "guess.svg").read_text() == chart
            sys.argv[-1] = "3"
            assert raises_system_exit(guess.main)  # no event #3
            sys.argv[1:] = [str(out / "jokes.txt"), str(out / "events.json")]
            assert raises_system_exit(guess.main)  # no guesses at all
        finally:
            sys.argv = old


if __name__ == "__main__":
    for name, check in list(globals().items()):
        if name.startswith("test_"):
            check()
            print("pass", name)
