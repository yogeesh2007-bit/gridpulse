import pytest

from app.services.control import decide_command


def view(util=40.0, over=False, online=True, active=(), queue=(), ev=None, base=3.0, limit=30.0, ports=1):
    ev_load = sum(a[1] for a in active) if ev is None else ev
    return {
        "utilization_pct": util, "over_limit": over, "is_online": online, "ports": ports,
        "queue_length": len(queue), "ev_load_kw": ev_load, "base_load_kw": base, "site_limit_kw": limit,
        "active": [{"priority_class": c, "kw": kw} for c, kw in active],
        "queue": [{"priority_class": c} for c in queue],
    }


def test_normal_when_lightly_loaded():
    d = decide_command(view(util=40, active=[("normal", 10)]))
    assert d.command == "NORMAL" and d.power_fraction == 1.0


def test_reduce_load_at_site_power_threshold():
    d = decide_command(view(util=88, active=[("normal", 22)]))
    assert d.command == "REDUCE_LOAD" and d.power_fraction == pytest.approx(0.8)
    assert "threshold" in d.reason.lower()


def test_reduce_load_when_over_limit_scales_to_allowed_power():
    # limit 30, base 3 => 27 kW allowed for EVs, 40 kW requested
    d = decide_command(view(util=140, over=True, active=[("normal", 20), ("normal", 20)], base=3, limit=30))
    assert d.command == "REDUCE_LOAD"
    assert d.power_fraction == pytest.approx(27 / 40)


def test_prioritize_urgent_when_urgent_is_queued_behind_busy_station():
    d = decide_command(view(util=60, active=[("normal", 20)], queue=["urgent"]))
    assert d.command == "PRIORITIZE_URGENT" and d.power_fraction == 1.0


def test_prioritize_urgent_when_queue_pressure_and_urgent_active():
    d = decide_command(view(util=50, active=[("urgent", 22)], queue=["normal", "normal"]))
    assert d.command == "PRIORITIZE_URGENT"


def test_pause_flex_when_urgent_present_and_site_near_limit():
    d = decide_command(view(util=95, active=[("urgent", 10), ("flexible", 10)], queue=[]))
    assert d.command == "PAUSE_FLEX" and d.flex_paused
    assert d.power_fraction == pytest.approx(0.5)  # only the urgent half of the load keeps running


def test_pause_flex_needs_a_flexible_session_to_pause():
    d = decide_command(view(util=95, active=[("urgent", 22)]))
    assert d.command != "PAUSE_FLEX"


def test_pause_flex_all_flexible_active_gives_zero_fraction():
    d = decide_command(view(util=99, active=[("flexible", 22)], queue=["urgent"]))
    assert d.command == "PAUSE_FLEX" and d.power_fraction == 0.0


def test_overtemperature_forces_reduce_load():
    d = decide_command(view(util=10, active=[("normal", 5)]), temperature_c=78)
    assert d.command == "REDUCE_LOAD" and d.power_fraction == pytest.approx(0.5)
    assert "temperature" in d.reason.lower()


def test_offline_station_disables_output():
    d = decide_command(view(online=False, active=[("normal", 5)]))
    assert d.command == "REDUCE_LOAD" and d.power_fraction == 0.0 and "offline" in d.reason.lower()


def test_idle_urgent_only_in_queue_on_empty_site_is_normal():
    d = decide_command(view(util=10, active=[], queue=["urgent"]))
    assert d.command == "NORMAL"
