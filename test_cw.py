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
                               "death_risk_pct": 1.5, "with_limit": {"20": {"impact_kmh": 9.9, "death_risk_pct": 0.2}},
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
                    "through the same spot within 3 s, 300 within 1.5 s (200 school days, 30-minute dismissals).")
    assert "about 300 crossings" in pack.headline(events, seen, {**school, "school_days": 197})[-1]  # not 295.5
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
    pack.model_plan = lambda prompt, key, photo=None: (prompts.append(prompt), replies.pop(0))[1]
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


def test_number_check_flags_words_and_mph_and_reads_the_measurements_only():
    facts = '{"worst": [{"vehicle_kmh": 38.0, "pet_s": 0.2}]}'
    assert pack.unmeasured("The four worst; thirty-eight km/h; 38 mph; dozens of times", facts) == [
        "four", "thirty-eight", "dozens", "38 mph"]
    assert pack.unmeasured("One car and two-wheelers, three wheelers, at 38.0 km/h, 0.2 s, by the Triumph", facts) == []
    letter = {"fix": "speed table", "why": "w", "image_prompt": "i", "letter": "SAM 3.1 measured 38.0 km/h."}
    old = pack.model_plan
    pack.model_plan = lambda prompt, key, photo=None: letter
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
    pack.model_plan = lambda prompt, key, photo=None: (prompts.append(prompt), replies.pop(0))[1]
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
    assert 'id="event-1"' in page and 'href="#event-1"' in page and 'contenteditable="plaintext-only"' in page
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
    (out / "site.json").write_text(json.dumps({"name": "gate", "world_points": SQUARE_ROAD}))
    return out


def run_pack(out, *flags, ask=None, key=None, draw=None):
    """pack.main() on `out` with no network: `ask(prompt)` stands in for the letter model, `draw` for Muse Image (and
    with it a street photo). Returns each (prompt, stated notes) the letter step was asked with."""
    import contextlib, io, sys
    calls, old = [], (sys.argv, pack.optional_key, pack.street_photo, pack.ask_plan, pack.draw_fix)
    sys.argv = ["pack.py", str(out), str(out / "site.json"), *flags]
    pack.optional_key = lambda: key
    pack.street_photo = (lambda clip, path, *args: (path.write_bytes(b"jpeg"), path)[1]) if draw else lambda *args: None
    pack.ask_plan = lambda prompt, measured, key, photo, stated=(): (calls.append((prompt, stated)), ask(prompt))[1]
    pack.draw_fix = draw or pack.draw_fix
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            pack.main()
    finally:
        sys.argv, pack.optional_key, pack.street_photo, pack.ask_plan, pack.draw_fix = old
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
    pack.model_plan = lambda prompt, key, photo=None: letter
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
    assert pack.letter_section({"letter": "x"}).startswith('<section class="letter-sheet">')

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
    unplaced_first = roadmap.svg(events[2:] + events[:1], [[-2, -2], [2, -2], [2, 2], [-2, 2]])
    assert ">#2</text>" in unplaced_first and ">#1</text>" not in unplaced_first  # the dot keeps card #2's number


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


if __name__ == "__main__":
    for name, check in list(globals().items()):
        if name.startswith("test_"):
            check()
            print("pass", name)
