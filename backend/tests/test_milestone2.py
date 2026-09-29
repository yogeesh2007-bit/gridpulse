from datetime import timedelta

import httpx
import pytest

from app.config import settings
from app.db import SessionLocal, utcnow
from app.models import Telemetry
from app.services import routing

CENTER = (settings.center_lat, settings.center_lon)
DEVICE = "esp32-station-a"


def packet(**over):
    body = {"device_id": DEVICE, "voltage": 11.9, "current": 1.2, "power": 14.3, "temperature": 34.5,
            "mode": "NORMAL", "note": "test"}
    body.update(over)
    return body


def driver_body(**over):
    body = {"driver_name": "Live Driver", "lat": CENTER[0], "lon": CENTER[1], "soc_current": 20,
            "soc_target": 80, "deadline_minutes": 120, "location_source": "gps"}
    body.update(over)
    return body


def station(client, code):
    return next(s for s in client.get("/stations").json() if s["code"] == code)


# ---- telemetry --------------------------------------------------------------------------------------
def test_telemetry_accepts_packet_and_returns_latest(client):
    r = client.post("/telemetry/update", json=packet())
    assert r.status_code == 201
    body = r.json()
    assert body["accepted"] and body["station_code"] == "A" and body["registered_device"]
    assert body["control"]["command"] in {"NORMAL", "REDUCE_LOAD", "PRIORITIZE_URGENT", "PAUSE_FLEX"}

    latest = client.get("/telemetry/latest").json()
    assert latest["count"] == 1
    d = latest["devices"][0]
    assert (d["device_id"], d["voltage"], d["current"], d["power"], d["temperature"]) == (DEVICE, 11.9, 1.2, 14.3, 34.5)
    assert d["mode"] == "NORMAL" and d["note"] == "test" and d["is_stale"] is False and d["age_s"] < 5


def test_telemetry_temperature_is_optional_and_latest_wins(client):
    client.post("/telemetry/update", json=packet(power=10.0))
    p = packet(power=20.0)
    del p["temperature"]
    client.post("/telemetry/update", json=p)
    d = client.get("/telemetry/latest", params={"device_id": DEVICE}).json()["devices"][0]
    assert d["power"] == 20.0 and d["temperature"] is None


def test_telemetry_validation(client):
    assert client.post("/telemetry/update", json=packet(voltage=-1)).status_code == 422
    assert client.post("/telemetry/update", json=packet(device_id="")).status_code == 422
    bad = packet()
    del bad["current"]
    assert client.post("/telemetry/update", json=bad).status_code == 422


def test_unknown_device_is_stored_but_unregistered(client):
    r = client.post("/telemetry/update", json=packet(device_id="mystery-1")).json()
    assert r["accepted"] and r["registered_device"] is False and r["control"] is None
    assert client.get("/telemetry/latest", params={"device_id": "mystery-1"}).json()["count"] == 1


def test_device_timestamp_is_parsed(client):
    r = client.post("/telemetry/update", json=packet(timestamp="2026-09-29T12:00:00Z"))
    assert r.status_code == 201
    assert client.get("/telemetry/latest").json()["devices"][0]["timestamp"].startswith("2026-09-29T12:00:00")


def test_telemetry_goes_stale(client):
    client.post("/telemetry/update", json=packet())
    with SessionLocal() as db:
        t = db.query(Telemetry).one()
        t.received_at = utcnow() - timedelta(seconds=60)
        db.commit()
    d = client.get("/telemetry/latest").json()["devices"][0]
    assert d["is_stale"] is True and d["age_s"] >= 59
    state = next(s for s in client.get("/control/state").json()["stations"] if s["station_code"] == "A")
    assert state["confirmation"] == "simulated" and state["source"] == "simulated"


# ---- control ---------------------------------------------------------------------------------------
def test_control_state_defaults_to_simulated_normal(client):
    cs = client.get("/control/state").json()
    assert cs["commands"] == ["NORMAL", "REDUCE_LOAD", "PRIORITIZE_URGENT", "PAUSE_FLEX"]
    a = next(s for s in cs["stations"] if s["station_code"] == "A")
    assert a["command"] == "NORMAL" and a["source"] == "simulated" and a["confirmation"] == "simulated"
    assert a["valid_for_s"] > 0 and a["duty_pct"] == 100
    assert any(e["station_code"] == "A" for e in cs["events"])


def test_control_reduce_load_when_site_limit_tightened_and_logged(client):
    a = station(client, "A")
    client.patch(f"/stations/{a['id']}", json={"site_limit_kw": 27})  # 25 kW of 27 = 93%
    st = next(s for s in client.get("/control/state").json()["stations"] if s["station_code"] == "A")
    assert st["command"] == "REDUCE_LOAD" and st["power_fraction"] == pytest.approx(0.8)
    ev = client.get("/control/state").json()["events"][0]
    assert ev["command"] == "REDUCE_LOAD" and ev["previous"] == "NORMAL" and ev["station_code"] == "A"

    client.patch(f"/stations/{a['id']}", json={"site_limit_kw": 20})  # over limit
    st2 = next(s for s in client.get("/control/state").json()["stations"] if s["station_code"] == "A")
    assert st2["command"] == "REDUCE_LOAD" and st2["power_fraction"] == pytest.approx((20 - 3) / 22, abs=0.01)
    assert st2["seq"] == st["seq"]  # same command => same sequence number


def test_urgent_driver_at_hot_station_pauses_flexible_sessions(client):
    a = station(client, "A")
    client.patch(f"/stations/{a['id']}", json={"site_limit_kw": 27})
    req = client.post("/drivers/request", json=driver_body(
        soc_current=6, deadline_minutes=60, lat=CENTER[0] + 0.009, lon=CENTER[1] + 0.01)).json()
    assert req["priority_class"] == "urgent"
    assert client.post("/reservations", json={"request_id": req["id"], "station_id": a["id"]}).status_code == 201
    st = next(s for s in client.get("/control/state").json()["stations"] if s["station_code"] == "A")
    assert st["command"] == "PAUSE_FLEX" and st["power_fraction"] == 0.0  # only Arun (flexible) is charging
    assert client.get("/control/state").json()["events"][0]["command"] == "PAUSE_FLEX"


def test_hardware_confirmation_flow(client):
    cmd = client.get(f"/control/command/{DEVICE}").json()
    assert cmd["command"] == "NORMAL" and cmd["confirmation"] == "simulated" and cmd["station_code"] == "A"

    client.post("/telemetry/update", json=packet(mode="REDUCE_LOAD"))  # device is not yet in the commanded mode
    a = next(s for s in client.get("/control/state").json()["stations"] if s["station_code"] == "A")
    assert a["confirmation"] == "hardware-pending" and a["source"] == "hardware"

    r = client.post("/telemetry/update", json=packet(mode="normal")).json()  # case-insensitive echo
    assert r["control"]["confirmation"] == "hardware-confirmed"
    a = next(s for s in client.get("/control/state").json()["stations"] if s["station_code"] == "A")
    assert a["confirmation"] == "hardware-confirmed" and a["hardware_mode"] == "NORMAL"


def test_overtemperature_telemetry_reduces_load(client):
    r = client.post("/telemetry/update", json=packet(temperature=82)).json()
    assert r["control"]["command"] == "REDUCE_LOAD" and r["control"]["power_fraction"] == pytest.approx(0.5)
    assert "temperature" in r["control"]["reason"].lower()


def test_control_command_unknown_device(client):
    assert client.get("/control/command/nope").status_code == 404


# ---- live location --------------------------------------------------------------------------------
def test_live_location_update_returns_etas_and_shows_on_dashboard(client):
    req = client.post("/drivers/request", json=driver_body()).json()
    r = client.post("/driver/location/update", json={
        "request_id": req["id"], "lat": CENTER[0] + 0.001, "lon": CENTER[1] + 0.001, "accuracy_m": 12, "source": "gps"})
    assert r.status_code == 200
    body = r.json()
    assert body["updates"] == 1 and len(body["etas"]) == 2 and body["etas_reused"] is False
    assert all(e["travel_min"] > 0 and e["distance_km"] > 0 for e in body["etas"])

    again = client.post("/driver/location/update", json={
        "request_id": req["id"], "lat": CENTER[0] + 0.002, "lon": CENTER[1], "accuracy_m": 9, "source": "gps"}).json()
    assert again["updates"] == 2 and again["etas_reused"] is True  # throttled: no new routing calls

    live = client.get("/dashboard/state").json()["live_drivers"]
    assert len(live) == 1 and live[0]["driver_name"] == "Live Driver" and live[0]["is_live"] is True
    assert live[0]["lat"] == pytest.approx(CENTER[0] + 0.002) and len(live[0]["etas"]) == 2


def test_live_location_moves_the_recommendation_origin(client):
    req = client.post("/drivers/request", json=driver_body()).json()
    first = client.post("/recommendation", json={"request_id": req["id"]}).json()
    # driver drives right up to Station B
    b = station(client, "B")
    client.post("/driver/location/update", json={"request_id": req["id"], "lat": b["lat"], "lon": b["lon"]})
    second = client.post("/recommendation", json={"request_id": req["id"]}).json()
    tb1 = next(c for c in first["candidates"] if c["code"] == "B")["travel_min"]
    tb2 = next(c for c in second["candidates"] if c["code"] == "B")["travel_min"]
    assert tb2 < 1.0 < tb1


def test_live_location_validation(client):
    assert client.post("/driver/location/update", json={"request_id": 9999, "lat": 1, "lon": 1}).status_code == 404
    req = client.post("/drivers/request", json=driver_body()).json()
    assert client.post("/driver/location/update", json={"request_id": req["id"], "lat": 99, "lon": 1}).status_code == 422


# ---- recommendation summary / routing confidence ---------------------------------------------------
def test_recommendation_summary_and_routing_confidence(client):
    req = client.post("/drivers/request", json=driver_body()).json()
    rec = client.post("/recommendation", json={"request_id": req["id"]}).json()
    s = rec["summary"]
    for key in ("station_name", "route_distance_km", "route_travel_min", "predicted_wait_min",
                "predicted_charge_min", "ready_at", "fallback_routing_used", "reason_summary", "routing_confidence"):
        assert key in s
    assert s["route_travel_min"] == rec["chosen"]["travel_min"] and s["ready_at"].endswith("Z")
    # test env uses haversine mode: estimated, but not a *fallback*
    assert rec["routing"]["estimated"] is True and rec["routing"]["fallback_used"] is False
    assert rec["routing"]["confidence"] == "reduced" and s["fallback_routing_used"] is False
    assert any("Lower confidence" in w for w in rec["warnings"])
    assert all("projected_load_pct" in c and "load_penalty" in c["score_breakdown"] for c in rec["candidates"] if c["feasible"])


# ---- routing: OSRM success, failure and rate limit ---------------------------------------------------
@pytest.fixture()
def osrm_mode(monkeypatch):
    monkeypatch.setattr(settings, "routing_mode", "osrm")
    routing.reset_state()
    yield
    routing.reset_state()


def test_osrm_success_is_used_and_cached(osrm_mode, monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return httpx.Response(200, json={"code": "Ok", "routes": [{"distance": 5000, "duration": 600}]},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(routing.httpx, "get", fake_get)
    r = routing.route((13.0, 80.0), (13.05, 80.05))
    assert (r.source, r.distance_km, r.duration_min) == ("osrm", 5.0, 10.0)
    routing.route((13.0, 80.0), (13.05, 80.05))
    assert len(calls) == 1  # second call served from cache
    assert routing.status()["osrm_ok"] == 1 and routing.status()["osrm_available"] is True


def test_osrm_failure_falls_back_to_haversine_and_flags_recommendation(osrm_mode, monkeypatch, client):
    def boom(url, **kw):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(routing.httpx, "get", boom)
    r = routing.route((13.0, 80.0), (13.05, 80.05))
    assert r.source == "haversine-fallback" and r.distance_km > 0 and r.duration_min > 0
    st = routing.status()
    assert st["osrm_available"] is False and st["cooldown_s"] > 0 and st["fallbacks"] >= 1 and "ConnectError" in st["last_error"]

    req = client.post("/drivers/request", json=driver_body()).json()
    rec = client.post("/recommendation", json={"request_id": req["id"]}).json()
    assert rec["chosen"] is not None  # the app keeps working
    assert rec["routing"]["fallback_used"] is True and rec["summary"]["fallback_routing_used"] is True
    assert "unavailable" in rec["routing"]["note"] and "approximate" in rec["explanation"]["text"]
    assert all(c["route_fallback"] for c in rec["candidates"])


def test_osrm_rate_limit_backs_off_longer(osrm_mode, monkeypatch):
    calls = []

    def limited(url, **kw):
        calls.append(1)
        return httpx.Response(429, request=httpx.Request("GET", url))

    monkeypatch.setattr(routing.httpx, "get", limited)
    r1 = routing.route((13.0, 80.0), (13.05, 80.05))
    r2 = routing.route((13.0, 80.0), (13.06, 80.06))
    assert r1.source == r2.source == "haversine-fallback"
    assert len(calls) == 1  # cooldown: second call did not hit OSRM again
    st = routing.status()
    assert "429" in st["last_error"] and st["cooldown_s"] > 60


# ---- dashboard aggregate -------------------------------------------------------------------------
def test_dashboard_state_has_milestone2_sections(client):
    client.post("/telemetry/update", json=packet())
    req = client.post("/drivers/request", json=driver_body()).json()
    client.post("/recommendation", json={"request_id": req["id"]})
    client.post("/driver/location/update", json={"request_id": req["id"], "lat": CENTER[0], "lon": CENTER[1]})
    s = client.get("/dashboard/state").json()

    a = next(x for x in s["stations"] if x["code"] == "A")
    b = next(x for x in s["stations"] if x["code"] == "B")
    assert a["control"]["command"] and a["telemetry"]["device_id"] == DEVICE and b["telemetry"] is None
    assert b["control"]["source"] == "simulated"
    assert s["telemetry"][0]["voltage"] == 11.9
    assert s["control_events"] and s["live_drivers"]
    eta = s["latest_route_etas"]
    assert eta["request_id"] == req["id"] and len(eta["items"]) == 2 and len(eta["live_etas"]) == 2
    assert all("travel_min" in i and "route_source" in i for i in eta["items"])
    tl = s["timeline"]
    assert tl["horizon_min"] == 120 and len(tl["items"]) >= 3
    assert all(0 <= i["start_min"] <= i["end_min"] <= 120 for i in tl["items"])
    assert s["system"]["routing"]["mode"] == "haversine"
