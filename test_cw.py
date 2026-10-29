"""Self-check for road geometry, PET and SAM parsing. Run: python3 test_cw.py"""
import html
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
    person = {"7": {f: (0.0, 0.0) for f in range(40)}}  # standing in the road while a car passes 0.1 m away
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
    pack.model_plan = lambda prompt, key, photo=None: (prompts.append(prompt), replies.pop(0))[1]
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
    pack.model_plan = lambda prompt, key, photo=None: (prompts.append(prompt), replies.pop(0))[1]
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


def test_open_weights_letter_writer_gets_the_prompt_and_street_photo():
    """With LETTER_MODEL_URL set, the plan comes from an OpenAI-compatible server (llama-server running Muse Glimmer)."""
    import tempfile, threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from pathlib import Path
    seen = {}
    plan = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "l"}

    class Fake(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reply = json.dumps({"choices": [{"message": {"content": json.dumps(plan)}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.handle_request, daemon=True).start()
    old = pack.LETTER_URL
    pack.LETTER_URL = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            photo = Path(tmp) / "street.jpg"
            photo.write_bytes(b"\xff\xd8jpeg")
            assert pack.model_plan("PROMPT", None, photo) == plan
    finally:
        pack.LETTER_URL = old
        server.server_close()
    content = seen["body"]["messages"][0]["content"]
    assert seen["path"] == "/v1/chat/completions" and seen["body"]["response_format"] == {"type": "json_object"}
    assert content[0] == {"type": "text", "text": "PROMPT"} and content[1]["image_url"]["url"].startswith("data:image/jpeg")
    assert "Muse Glimmer" in pack.letter_section({**plan, "writer": "Muse Glimmer 30B (open weights)"})


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
