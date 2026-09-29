"""The authenticated product API: driver and operator endpoints, ownership and role enforcement."""
import uuid

import pytest

from app.config import settings
from app.db import SessionLocal
from app.models import DriverRequest

C = (settings.center_lat, settings.center_lon)
SPEC = {"lat": C[0], "lng": C[1], "soc": 12, "target_soc": 80, "deadline": 90}


def make_driver(client):
    email = f"drv-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/signup", json={"name": "Other Driver", "email": email, "password": "another-pass1"})
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]


# ---- access control -------------------------------------------------------------------------------------
DRIVER_ROUTES = [
    ("post", "/api/driver/recommend"), ("get", "/api/driver/requests/latest"), ("post", "/api/driver/requests/1/refresh"),
    ("post", "/api/driver/location"), ("post", "/api/driver/reservations"), ("get", "/api/driver/reservations"),
    ("post", "/api/driver/reservations/1/cancel"), ("get", "/api/driver/stations"),
]
OPERATOR_ROUTES = [
    ("get", "/api/operator/state"), ("patch", "/api/operator/stations/1"), ("get", "/api/operator/reservations"),
    ("post", "/api/operator/reservations/1/cancel"), ("post", "/api/operator/seed"), ("get", "/api/operator/control"),
]


@pytest.mark.parametrize("method,path", DRIVER_ROUTES + OPERATOR_ROUTES + [("post", "/api/explain"), ("get", "/api/geo/reverse")])
def test_every_product_route_requires_authentication(client, method, path):
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize("method,path", OPERATOR_ROUTES)
def test_drivers_cannot_use_operator_routes(client, driver, method, path):
    assert getattr(client, method)(path, headers=driver[0]).status_code == 403


@pytest.mark.parametrize("method,path", DRIVER_ROUTES)
def test_operators_cannot_use_driver_routes(client, operator, method, path):
    assert getattr(client, method)(path, headers=operator[0]).status_code == 403


def test_legacy_open_api_is_off_unless_enabled(client, monkeypatch):
    assert client.get("/stations").status_code == 200
    monkeypatch.setattr(settings, "legacy_api_enabled", False)
    for method, path in (("get", "/stations"), ("post", "/seed"), ("get", "/dashboard/state"), ("get", "/devices"),
                         ("get", "/control/state"), ("get", "/reservations"), ("post", "/recommend"),
                         ("get", "/telemetry/latest")):
        assert getattr(client, method)(path).status_code == 404, path
    assert client.get("/health").status_code == 200  # health stays public


def test_device_endpoints_use_the_device_key_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "legacy_api_enabled", False)
    body = {"device_id": "esp32-station-a", "voltage": 12, "current": 1, "power": 12, "mode": "NORMAL"}
    assert client.post("/telemetry/update", json=body).status_code == 201  # no key configured => open (dev)
    monkeypatch.setattr(settings, "device_api_key", "s3cret-device-key")
    assert client.post("/telemetry/update", json=body).status_code == 401
    assert client.post("/telemetry/update", json=body, headers={"X-Device-Key": "wrong"}).status_code == 401
    ok = {"X-Device-Key": "s3cret-device-key"}
    assert client.post("/telemetry/update", json=body, headers=ok).status_code == 201
    assert client.get("/device/esp32-station-a/command", headers=ok).status_code == 200
    assert client.get("/device/esp32-station-a/command").status_code == 401


# ---- driver flow ---------------------------------------------------------------------------------------
def test_driver_recommend_stores_the_request_for_the_signed_in_user(client, driver):
    headers, user = driver
    rec = client.post("/api/driver/recommend", json={**SPEC, "driver_name": "Spoofed Name"}, headers=headers)
    assert rec.status_code == 200
    body = rec.json()
    assert body["chosen_station"]["name"].startswith("Station B") and len(body["ranking"]) == 2
    with SessionLocal() as db:
        req = db.get(DriverRequest, body["request_id"])
        assert req.user_id == user["id"] and req.driver_name == user["name"]  # named after the account, not the payload


def test_recommend_validates_input(client, driver):
    h = driver[0]
    assert client.post("/api/driver/recommend", json={**SPEC, "target_soc": 5}, headers=h).status_code == 422
    assert client.post("/api/driver/recommend", json={**SPEC, "lat": 999}, headers=h).status_code == 422
    assert client.post("/api/driver/recommend", json={"lat": 1}, headers=h).status_code == 422


def test_latest_request_restores_the_session_state(client, driver):
    h = driver[0]
    empty = client.get("/api/driver/requests/latest", headers=h).json()
    assert empty == {"request": None, "recommendation": None, "reservation": None}
    rec = client.post("/api/driver/recommend", json=SPEC, headers=h).json()
    latest = client.get("/api/driver/requests/latest", headers=h).json()
    assert latest["request"]["id"] == rec["request_id"] and latest["request"]["soc_current"] == 12
    assert latest["recommendation"]["chosen_station"]["id"] == rec["chosen_station"]["id"]
    assert latest["reservation"] is None
    client.post("/api/driver/reservations", json={"request_id": rec["request_id"]}, headers=h)
    assert client.get("/api/driver/requests/latest", headers=h).json()["reservation"]["status"] in ("queued", "active")


def test_refresh_recomputes_from_the_latest_position(client, driver):
    h = driver[0]
    rec = client.post("/api/driver/recommend", json=SPEC, headers=h).json()
    b = next(s for s in client.get("/api/driver/stations", headers=h).json() if s["code"] == "B")
    client.post("/api/driver/location", json={"request_id": rec["request_id"], "lat": b["lat"], "lon": b["lng"]}, headers=h)
    again = client.post(f"/api/driver/requests/{rec['request_id']}/refresh", headers=h).json()
    tb = next(r for r in again["ranking"] if r["code"] == "B")["travel_time_min"]
    assert tb < 1.0 and again["request_id"] == rec["request_id"]


def test_live_location_returns_etas(client, driver):
    h = driver[0]
    rec = client.post("/api/driver/recommend", json=SPEC, headers=h).json()
    r = client.post("/api/driver/location", json={"request_id": rec["request_id"], "lat": C[0] + 0.001, "lon": C[1],
                                                  "accuracy_m": 12, "source": "gps"}, headers=h)
    assert r.status_code == 200 and len(r.json()["etas"]) == 2 and r.json()["updates"] == 1


def test_drivers_cannot_touch_each_others_requests(client, driver):
    h1 = driver[0]
    h2, _ = make_driver(client)
    rec = client.post("/api/driver/recommend", json=SPEC, headers=h1).json()
    rid = rec["request_id"]
    assert client.post(f"/api/driver/requests/{rid}/refresh", headers=h2).status_code == 404
    assert client.post("/api/driver/location", json={"request_id": rid, "lat": C[0], "lon": C[1]}, headers=h2).status_code == 404
    assert client.post("/api/driver/reservations", json={"request_id": rid}, headers=h2).status_code == 404
    assert client.post("/api/explain", json={"request_id": rid}, headers=h2).status_code == 404
    assert client.get("/api/driver/requests/latest", headers=h2).json()["request"] is None


def test_reservation_lifecycle_and_ownership(client, driver):
    h1 = driver[0]
    h2, _ = make_driver(client)
    rid = client.post("/api/driver/recommend", json=SPEC, headers=h1).json()["request_id"]
    res = client.post("/api/driver/reservations", json={"request_id": rid}, headers=h1)
    assert res.status_code == 201 and res.json()["status"] in ("queued", "active")
    assert client.post("/api/driver/reservations", json={"request_id": rid}, headers=h1).status_code == 409

    mine = client.get("/api/driver/reservations", headers=h1).json()
    assert [r["id"] for r in mine] == [res.json()["id"]]
    assert client.get("/api/driver/reservations", headers=h2).json() == []  # seeded/other drivers' bookings are private

    res_id = res.json()["id"]
    assert client.post(f"/api/driver/reservations/{res_id}/cancel", headers=h2).status_code == 404
    done = client.post(f"/api/driver/reservations/{res_id}/cancel", headers=h1)
    assert done.status_code == 200 and done.json()["status"] == "cancelled"
    assert client.post(f"/api/driver/reservations/{res_id}/cancel", headers=h1).status_code == 409


def test_driver_station_view_is_public_data_only(client, driver):
    stations = client.get("/api/driver/stations", headers=driver[0]).json()
    assert [s["code"] for s in stations] == ["A", "B"]
    for s in stations:
        assert {"available_ports", "queue_count", "current_load_w", "site_power_limit_w", "utilization_pct"} <= set(s)
        for private in ("queue", "active", "control", "device", "telemetry", "device_id"):
            assert private not in s  # other drivers' names and hardware internals stay off the driver API


# ---- explanation (optional OpenRouter) -----------------------------------------------------------------------
def test_explain_falls_back_to_rules_and_respects_ownership(client, driver, operator):
    h = driver[0]
    rid = client.post("/api/driver/recommend", json=SPEC, headers=h).json()["request_id"]
    out = client.post("/api/explain", json={"request_id": rid}, headers=h).json()
    assert out["source"] == "rules" and out["text"] and "OPENROUTER_API_KEY" in out["fallback_reason"]
    assert client.post("/api/explain", json={"request_id": rid}, headers=operator[0]).status_code == 200  # operators see all
    assert client.post("/api/explain", json={"request_id": 99999}, headers=h).status_code == 404


def test_explain_uses_the_llm_text_when_available_without_changing_the_decision(client, driver, monkeypatch):
    h = driver[0]
    rec = client.post("/api/driver/recommend", json=SPEC, headers=h).json()
    monkeypatch.setattr("app.services.driver_flow.llm_explanation", lambda r: ("Friendly rewrite of Station B advice.", None, 7))
    out = client.post("/api/explain", json={"request_id": rec["request_id"]}, headers=h).json()
    assert out["source"] == "llm" and out["text"].startswith("Friendly")
    again = client.post(f"/api/driver/requests/{rec['request_id']}/refresh", headers=h).json()
    assert again["chosen_station"]["id"] == rec["chosen_station"]["id"]


# ---- operator ---------------------------------------------------------------------------------------------
def test_operator_state_has_everything_the_dashboard_needs(client, operator):
    s = client.get("/api/operator/state", headers=operator[0]).json()
    for key in ("stations", "reservations", "totals", "control_events", "devices", "hardware_summary", "timeline",
                "latest_recommendation", "live_drivers", "system"):
        assert key in s
    assert [x["code"] for x in s["stations"]] == ["A", "B"] and "control" in s["stations"][0]


def test_operator_sees_all_reservations_including_drivers(client, operator, driver):
    rid = client.post("/api/driver/recommend", json=SPEC, headers=driver[0]).json()["request_id"]
    res = client.post("/api/driver/reservations", json={"request_id": rid}, headers=driver[0]).json()
    allr = client.get("/api/operator/reservations", params={"status": "queued,active"}, headers=operator[0]).json()
    assert res["id"] in [r["id"] for r in allr] and len(allr) >= 5  # 4 seeded + the driver's


def test_operator_can_change_a_station_and_cancel_any_reservation(client, operator, driver):
    h = operator[0]
    stations = client.get("/api/operator/state", headers=h).json()["stations"]
    a = next(s for s in stations if s["code"] == "A")
    upd = client.patch(f"/api/operator/stations/{a['id']}", json={"site_limit_kw": 27}, headers=h)
    assert upd.status_code == 200 and upd.json()["site_limit_kw"] == 27
    assert client.patch(f"/api/operator/stations/{a['id']}", json={"site_limit_kw": -5}, headers=h).status_code == 422
    assert client.patch(f"/api/operator/stations/{a['id']}", json={}, headers=h).status_code == 422
    assert client.patch("/api/operator/stations/999", json={"site_limit_kw": 20}, headers=h).status_code == 404

    rid = client.post("/api/driver/recommend", json=SPEC, headers=driver[0]).json()["request_id"]
    res = client.post("/api/driver/reservations", json={"request_id": rid}, headers=driver[0]).json()
    cancelled = client.post(f"/api/operator/reservations/{res['id']}/cancel", headers=h)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert client.post("/api/operator/reservations/99999/cancel", headers=h).status_code == 404


def test_operator_reset_keeps_accounts(client, operator, driver):
    h = operator[0]
    client.post("/api/driver/recommend", json=SPEC, headers=driver[0])
    r = client.post("/api/operator/seed", headers=h)
    assert r.status_code == 200 and r.json()["seeded"] is True
    assert client.get("/api/operator/state", headers=h).json()["latest_recommendation"] is None
    assert client.post("/api/auth/signin", json={"email": "driver@gridpulse.local", "password": "Driver123!"}).status_code == 200


def test_operator_control_panel_data(client, operator):
    c = client.get("/api/operator/control", headers=operator[0]).json()
    assert [s["station_code"] for s in c["stations"]] == ["A", "B"]
    assert c["stations"][0]["command"] == "NORMAL" and "fallback_reason" in c["stations"][0]
    assert {"devices", "events", "hardware_summary", "commands"} <= set(c)
    assert c["hardware_summary"]["mode"] == "software"
