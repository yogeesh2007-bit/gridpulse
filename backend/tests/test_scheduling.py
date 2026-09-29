import pytest

from app.services.scheduling import (
    MIN_KW,
    ActiveLoad,
    DriverNeed,
    QueueJob,
    QueuedLoad,
    StationSnapshot,
    charge_minutes,
    classify,
    compute_urgency,
    evaluate_station,
    simulate_queue,
    soc_after_drive,
)


def snap(id=1, ports=1, kw=22.0, limit=100.0, base=0.0, active=(), queued=(), online=True):
    return StationSnapshot(
        id=id, code=str(id), name=f"S{id}", kind="simulated", lat=0, lon=0, ports=ports,
        max_kw_per_port=kw, site_limit_kw=limit, base_load_kw=base, is_online=online,
        active=tuple(active), queued=tuple(queued),
    )


def need(**kw):
    d = dict(soc_current=30, soc_target=80, deadline_min=240, battery_kwh=40, max_charge_kw=50,
             urgency=0.2, priority_class="normal")
    d.update(kw)
    return DriverNeed(**d)


# ---- helpers -------------------------------------------------------------------------------------
def test_charge_minutes_without_taper():
    # 20% of 40 kWh = 8 kWh at 20 kW = 24 min
    assert charge_minutes(20, 40, 40, 20) == pytest.approx(24.0)


def test_charge_minutes_taper_above_80():
    # 70->90: 10% (4 kWh) at 20 kW = 12 min, 10% (4 kWh) at 10 kW = 24 min
    assert charge_minutes(70, 90, 40, 20) == pytest.approx(36.0)


def test_soc_after_drive():
    # 10 km * 0.18 = 1.8 kWh of 40 kWh = 4.5 points
    assert soc_after_drive(50, 10, 40) == pytest.approx(45.5)
    assert soc_after_drive(2, 100, 40) == 0.0


def test_urgency_low_soc_is_urgent():
    u, cls = compute_urgency(8, 80, 600, 40, 50)
    assert u == 1.0 and cls == "urgent"


def test_urgency_relaxed_is_flexible():
    u, cls = compute_urgency(60, 80, 600, 40, 50)
    assert u == 0.0 and cls == "flexible"


def test_urgency_tight_deadline_is_urgent():
    # 30% -> 80% at 22 kW needs ~ 55 min; a 50 min deadline has no slack
    u, cls = compute_urgency(45, 100, 50, 40, 50)
    assert cls == "urgent"


def test_classify_thresholds():
    assert classify(0.7) == "urgent" and classify(0.3) == "flexible" and classify(0.5) == "normal"


# ---- queue simulation -----------------------------------------------------------------------------
def test_queue_urgent_jumps_queued_flexible_but_not_active():
    jobs = [
        QueueJob("flex", 0, 30, 2, 20),
        QueueJob("urgent", 5, 30, 0, 20),
    ]
    # port busy until t=20 (active session, never preempted)
    slots = simulate_queue([20], jobs)
    assert slots["urgent"].start_min == 20  # gets the port as soon as it frees...
    assert slots["flex"].start_min == 50  # ...ahead of the earlier-arrived flexible driver


def test_queue_free_port_starts_immediately_on_arrival():
    slots = simulate_queue([0, 0], [QueueJob("a", 7, 20, 1, 20)])
    assert slots["a"].start_min == 7


def test_queue_two_ports_parallel():
    jobs = [QueueJob("a", 0, 30, 1, 10), QueueJob("b", 0, 30, 1, 10), QueueJob("c", 0, 30, 1, 10)]
    slots = simulate_queue([0, 0], jobs)
    assert sorted(s.start_min for s in slots.values()) == [0, 0, 30]


def test_queue_power_gating_delays_start():
    # 30 kW available on site, 28 kW already used by an active session ending at t=15
    running = [(-1e9, 15.0, 28.0)]
    slots = simulate_queue([0, 0], [QueueJob("a", 0, 30, 1, 10)], running, site_avail_kw=30.0)
    assert slots["a"].start_min == 15.0
    assert slots["a"].headroom_kw >= MIN_KW


# ---- station evaluation ---------------------------------------------------------------------------
def test_free_station_has_no_wait_and_is_feasible():
    c = evaluate_station(need(), snap(), distance_km=3, travel_min=6)
    assert c.feasible and c.wait_min == 0
    assert c.total_min == pytest.approx(c.travel_min + c.charge_min, abs=0.2)
    assert c.charge_kw == 22.0


def test_busy_station_adds_wait():
    s = snap(active=[ActiveLoad(end_min=40, kw=22)])
    c = evaluate_station(need(), s, 3, 6)
    assert c.wait_min == pytest.approx(34.0, abs=0.2)


def test_farther_station_wins_when_nearest_has_queue():
    n = need(urgency=0.6, priority_class="normal")
    near = snap(id=1, active=[ActiveLoad(40, 22)],
                queued=[QueuedLoad("q1", -5, 30, 1, 22)])
    far = snap(id=2, ports=2, kw=50)
    c_near = evaluate_station(n, near, 2, 4)
    c_far = evaluate_station(n, far, 8, 16)
    assert c_far.travel_min > c_near.travel_min
    assert c_far.score < c_near.score
    assert c_far.total_min < c_near.total_min


def test_urgent_driver_displaces_queued_flexible():
    s = snap(active=[ActiveLoad(20, 22)], queued=[QueuedLoad("q1", -5, 30, 2, 22)])
    urgent = evaluate_station(need(urgency=0.9, priority_class="urgent"), s, 1, 2)
    flexible = evaluate_station(need(urgency=0.1, priority_class="flexible"), s, 1, 2)
    assert urgent.displaces == 1 and urgent.queue_ahead == 0
    assert flexible.displaces == 0 and flexible.queue_ahead == 1
    assert urgent.wait_min < flexible.wait_min


def test_infeasible_when_arrival_below_reserve():
    c = evaluate_station(need(soc_current=6), snap(), distance_km=30, travel_min=50)
    assert not c.feasible and "reserve" in c.rejection_reason


def test_offline_station_is_infeasible():
    c = evaluate_station(need(), snap(online=False), 1, 2)
    assert not c.feasible and c.rejection_reason == "Station is offline"


def test_power_headroom_caps_charging_rate():
    # 50 kW port but only 12 kW of site headroom
    s = snap(kw=50, limit=40, base=8, active=[ActiveLoad(60, 20)], ports=2)
    c = evaluate_station(need(), s, 1, 2)
    assert c.feasible and c.charge_kw == pytest.approx(12.0) and c.power_limited


def test_no_site_power_is_infeasible():
    s = snap(kw=50, limit=10, base=9, ports=2)
    c = evaluate_station(need(), s, 1, 2)
    assert not c.feasible and "power" in c.rejection_reason


def test_deadline_miss_is_penalised_in_score():
    tight = evaluate_station(need(deadline_min=20), snap(), 3, 6)
    relaxed = evaluate_station(need(deadline_min=500), snap(), 3, 6)
    assert not tight.deadline_ok and tight.deadline_miss_min > 0
    assert tight.score > relaxed.score
    assert tight.score_breakdown["urgency_bonus"] == 0  # a station that misses the deadline earns no urgency bonus


def test_urgency_lowers_the_score_through_the_bonus_but_not_the_predicted_wait():
    s = snap(active=[ActiveLoad(30, 22)])
    calm = evaluate_station(need(urgency=0.0), s, 1, 2)
    hurried = evaluate_station(need(urgency=1.0), s, 1, 2)
    assert hurried.score < calm.score
    assert hurried.wait_min == calm.wait_min


# ---- Milestone 2: load pressure + routing confidence ----------------------------------------------------
def test_high_projected_site_load_is_penalised():
    relaxed = evaluate_station(need(), snap(kw=22, limit=100), 1, 2)
    tight = evaluate_station(need(), snap(kw=22, limit=24), 1, 2)  # 22 kW on a 24 kW site = 92%
    assert relaxed.score_breakdown["load_penalty"] == 0
    assert tight.projected_load_pct == pytest.approx(22 / 24 * 100, abs=0.2)
    assert tight.score_breakdown["load_penalty"] == pytest.approx(60 * (22 / 24 - 0.70), abs=0.1)
    assert tight.score > relaxed.score


def test_load_pressure_can_flip_the_choice():
    n = need()
    hot = snap(id=1, kw=22, limit=23)  # ~96% utilisation, slightly closer
    cool = snap(id=2, kw=22, limit=100)
    c_hot = evaluate_station(n, hot, 2, 5.0)
    c_cool = evaluate_station(n, cool, 2, 8.0)
    assert c_cool.score < c_hot.score  # 3 minutes farther, but not running at the limit


def test_route_fallback_flags():
    ok = evaluate_station(need(), snap(), 3, 6, "osrm")
    est = evaluate_station(need(), snap(), 3, 6, "haversine")
    fb = evaluate_station(need(), snap(), 3, 6, "haversine-fallback")
    assert (ok.route_estimated, ok.route_fallback) == (False, False)
    assert (est.route_estimated, est.route_fallback) == (True, False)
    assert (fb.route_estimated, fb.route_fallback) == (True, True)
