"""WebSocket realtime updates, the scheduler clock, and single-page-app serving."""
import uuid
from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.db import SessionLocal, utcnow
from app.main import app
from app.models import Reservation
from app.services import realtime, scheduler

C = (settings.center_lat, settings.center_lon)
SPEC = {"lat": C[0], "lng": C[1], "soc": 12, "target_soc": 80, "deadline": 90}


@pytest.fixture()
def live(monkeypatch):
    """A client whose app runs the background scheduler + broadcaster with fast ticks."""
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    monkeypatch.setattr(settings, "ws_tick_s", 0.2)
    monkeypatch.setattr(settings, "scheduler_tick_s", 0.2)
    with TestClient(app) as c:
        c.post("/seed")
        yield c
    realtime.manager.clear()


def token(client, email, password):
    return client.post("/api/auth/signin", json={"email": email, "password": password}).json()["access_token"]


def op_token(c):
    return token(c, "operator@gridpulse.local", "Operator123!")


def drv_token(c):
    return token(c, "driver@gridpulse.local", "Driver123!")


def new_driver_token(c):
    email = f"rt-{uuid.uuid4().hex[:8]}@example.com"
    return c.post("/api/auth/signup", json={"name": "RT", "email": email, "password": "realtime-pass1"}).json()["access_token"]


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def read_until(ws, predicate, limit=40):
    """Read messages until predicate(message) is true. Ticks are 0.2 s, so this returns quickly when it works."""
    for _ in range(limit):
        msg = ws.receive_json()
        if predicate(msg):
            return msg
    raise AssertionError("expected message never arrived")


# ---- authentication of the socket --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["", "not-a-token", "abc.def.ghi"])
def test_websocket_rejects_missing_or_invalid_tokens(live, bad):
    with live.websocket_connect(f"/api/ws?token={bad}") as ws:
        assert ws.receive_json()["type"] == "error"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_websocket_rejects_a_refresh_token(live):
    live.cookies.clear()
    live.post("/api/auth/signin", json={"email": "driver@gridpulse.local", "password": "Driver123!"})
    refresh = live.cookies.get("gp_refresh")
    with live.websocket_connect(f"/api/ws?token={refresh}") as ws:
        assert ws.receive_json()["type"] == "error"


def test_websocket_rejects_an_expired_access_token(live, monkeypatch):
    monkeypatch.setattr(settings, "access_token_minutes", -1)
    t = drv_token(live)
    with live.websocket_connect(f"/api/ws?token={t}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error" and "expired" in msg["detail"].lower()


def test_connection_is_closed_when_the_token_expires_mid_session(live, monkeypatch):
    monkeypatch.setattr(settings, "access_token_minutes", 0.02)  # ~1.2 s
    t = drv_token(live)
    with live.websocket_connect(f"/api/ws?token={t}") as ws:
        assert ws.receive_json()["type"] == "hello"
        with pytest.raises(WebSocketDisconnect) as exc:
            for _ in range(60):
                ws.receive_json()
        assert exc.value.code == 4401


def test_ping_pong(live):
    with live.websocket_connect(f"/api/ws?token={drv_token(live)}") as ws:
        ws.send_text("ping")
        assert read_until(ws, lambda m: m["type"] == "pong")


# ---- operator stream ------------------------------------------------------------------------------------------
def test_operator_receives_the_full_dashboard_state(live):
    with live.websocket_connect(f"/api/ws?token={op_token(live)}") as ws:
        hello = ws.receive_json()
        assert hello == {"type": "hello", "role": "operator", "name": "Demo Operator"}
        msg = read_until(ws, lambda m: m["type"] == "state")
        data = msg["data"]
        assert [s["code"] for s in data["stations"]] == ["A", "B"] and "control" in data["stations"][0]
        assert msg["ts"].endswith("Z") and "hardware_summary" in data


def test_operator_sees_a_new_reservation_pushed_immediately(live):
    dt = drv_token(live)
    with live.websocket_connect(f"/api/ws?token={op_token(live)}") as ws:
        read_until(ws, lambda m: m["type"] == "state")
        rid = live.post("/api/driver/recommend", json=SPEC, headers=bearer(dt)).json()["request_id"]
        res = live.post("/api/driver/reservations", json={"request_id": rid}, headers=bearer(dt)).json()
        msg = read_until(ws, lambda m: m["type"] == "state" and any(r["id"] == res["id"] for r in m["data"]["reservations"]))
        assert msg["data"]["latest_recommendation"]["request_id"] == rid


def test_operator_sees_device_telemetry_live(live):
    with live.websocket_connect(f"/api/ws?token={op_token(live)}") as ws:
        read_until(ws, lambda m: m["type"] == "state")
        live.post("/telemetry/update", json={"device_id": "esp32-station-a", "voltage": 11.9, "current": 1.1, "power": 13.1,
                                             "mode": "NORMAL", "source": "real", "sensor_status": "ok"})
        msg = read_until(ws, lambda m: m["type"] == "state" and m["data"]["stations"][0]["telemetry"] is not None)
        assert msg["data"]["stations"][0]["telemetry"]["voltage"] == 11.9
        assert msg["data"]["hardware_summary"]["mode"] == "real"


def test_operator_sees_a_station_change_pushed(live):
    with live.websocket_connect(f"/api/ws?token={op_token(live)}") as ws:
        read_until(ws, lambda m: m["type"] == "state")
        a = next(s for s in live.get("/api/driver/stations", headers=bearer(drv_token(live))) .json() if s["code"] == "A")
        live.patch(f"/api/operator/stations/{a['id']}", json={"site_limit_kw": 26}, headers=bearer(op_token(live)))
        msg = read_until(ws, lambda m: m["type"] == "state" and m["data"]["stations"][0]["site_limit_kw"] == 26)
        assert msg["data"]["stations"][0]["control"]["command"] == "REDUCE_LOAD"


# ---- driver stream --------------------------------------------------------------------------------------------
def test_driver_gets_only_public_data_and_only_their_own_reservations(live):
    t1, t2 = drv_token(live), new_driver_token(live)
    with live.websocket_connect(f"/api/ws?token={t1}") as w1, live.websocket_connect(f"/api/ws?token={t2}") as w2:
        m1 = read_until(w1, lambda m: m["type"] == "driver")
        read_until(w2, lambda m: m["type"] == "driver")
        assert m1["data"]["reservations"] == [] and "control" not in m1["data"]["stations"][0]
        assert "queue" not in m1["data"]["stations"][0]

        rid = live.post("/api/driver/recommend", json=SPEC, headers=bearer(t1)).json()["request_id"]
        res = live.post("/api/driver/reservations", json={"request_id": rid}, headers=bearer(t1)).json()
        got = read_until(w1, lambda m: m["type"] == "driver" and m["data"]["reservations"])
        assert got["data"]["reservations"][0]["id"] == res["id"]
        # The other driver's socket may get a station-availability update, but never this driver's reservation.
        # Ping barriers make this deterministic without waiting for messages that are not supposed to come.
        seen = []
        for _ in range(2):
            w2.send_text("ping")
            while True:
                msg = w2.receive_json()
                if msg["type"] == "pong":
                    break
                seen.append(msg)
        assert all(m["type"] == "driver" and m["data"]["reservations"] == [] for m in seen)


def test_driver_socket_is_quiet_when_nothing_changes(live):
    with live.websocket_connect(f"/api/ws?token={drv_token(live)}") as ws:
        read_until(ws, lambda m: m["type"] == "driver")
        ws.send_text("ping")
        # the next thing we get is the pong, not a repeated identical snapshot
        assert ws.receive_json()["type"] == "pong"


# ---- scheduler clock ----------------------------------------------------------------------------------------------
def test_scheduler_tick_advances_reservations_and_reports_changes(client):
    with SessionLocal() as db:
        queued = db.query(Reservation).filter_by(status="queued").order_by(Reservation.id).first()
        active = db.query(Reservation).filter_by(status="active").order_by(Reservation.id).first()
        assert scheduler.tick() is False  # nothing due yet
        queued_id, active_id = queued.id, active.id
        active.planned_end_at = utcnow() - timedelta(minutes=1)  # finished a minute ago
        db.commit()
    assert scheduler.tick() is True
    with SessionLocal() as db:
        assert db.get(Reservation, active_id).status == "done"
    assert scheduler.tick() is False  # stable again
    assert queued_id  # (queued driver at the same station starts when its own planned time arrives)


def test_poke_without_a_running_broadcaster_is_harmless():
    realtime.poke()


# ---- single-page app --------------------------------------------------------------------------------------------------
@pytest.fixture()
def fake_dist(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>GridPulse SPA</title><div id=root></div>")
    (tmp_path / "assets" / "app.abc123.js").write_text("console.log('hi')")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path.parent / "secret.txt").write_text("TOP SECRET")
    monkeypatch.setattr("app.main.WEB_DIST", tmp_path)
    return tmp_path


@pytest.mark.parametrize("path", ["/", "/app", "/app/driver", "/app/operator", "/signin", "/signup", "/app/anything/else"])
def test_client_side_routes_serve_the_app_shell(client, fake_dist, path):
    r = client.get(path)
    assert r.status_code == 200 and "GridPulse SPA" in r.text and r.headers["cache-control"] == "no-cache"


def test_built_assets_are_served_and_cached_forever(client, fake_dist):
    r = client.get("/assets/app.abc123.js")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    assert client.get("/favicon.svg").status_code == 200


def test_unknown_files_and_api_paths_are_404_not_the_app(client, fake_dist):
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/api/does-not-exist").status_code == 404
    assert client.get("/api").status_code == 404


def test_path_traversal_cannot_escape_the_build_folder(client, fake_dist):
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt", "/..%2fsecret.txt"):
        r = client.get(path)
        assert "TOP SECRET" not in r.text, path


def test_api_docs_and_health_are_not_shadowed_by_the_app(client, fake_dist):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/openapi.json").status_code == 200


def test_missing_build_gives_helpful_instructions(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.WEB_DIST", tmp_path / "nope")
    r = client.get("/app/driver")
    assert r.status_code == 503 and "npm run build" in r.text
