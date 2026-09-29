"""Bulb/relay node: device reports, remote commands, manual-vs-remote semantics, offline detection, access control."""
from datetime import timedelta

import pytest

from app.config import settings
from app.db import SessionLocal, utcnow
from app.models import BulbDevice, BulbEvent

DEV = "bulb-01"


def report(client, on, source="heartbeat", **extra):
    return client.post(f"/api/bulb/{DEV}/status", json={"bulb_on": on, "source": source, **extra})


def command(client, headers, on, dev=DEV):
    return client.post(f"/api/operator/bulbs/{dev}/command", json={"bulb_on": on}, headers=headers)


def node(client, headers):
    return next(b for b in client.get("/api/operator/bulbs", headers=headers).json() if b["device_id"] == DEV)


@pytest.fixture(autouse=True)
def clean_bulbs(client):
    with SessionLocal() as db:
        db.query(BulbEvent).delete()
        db.query(BulbDevice).delete()
        db.commit()


def test_placeholder_node_is_offline_until_the_device_reports(client, operator):
    n = node(client, operator[0])
    assert n["online"] is False and n["seen"] is False and n["state"] == "unknown" and n["sync"] == "unknown"
    assert client.get("/api/operator/state", headers=operator[0]).json()["bulbs"][0]["device_id"] == DEV


def test_device_report_marks_it_online_and_returns_the_command(client, operator):
    r = report(client, False, "boot", rssi=-61, firmware="gp-bulb 1.0")
    assert r.status_code == 200 and r.json() == {"accepted": True, "bulb_on": False, "seq": 0}
    n = node(client, operator[0])
    assert n["online"] and n["state"] == "off" and n["last_source"] == "boot" and n["rssi"] == -61 and n["firmware"] == "gp-bulb 1.0"


def test_command_endpoint_returns_compact_json_the_firmware_can_match(client):
    body = client.get(f"/api/bulb/{DEV}/command").text
    assert '"bulb_on":false' in body  # no spaces: the sketch searches for this exact text
    assert '"bulb_on":true' not in body


def test_remote_command_flow(client, operator):
    h = operator[0]
    report(client, False, "boot")
    sent = command(client, h, True)
    assert sent.status_code == 200 and sent.json()["desired_on"] is True and sent.json()["sync"] == "pending"
    assert sent.json()["commanded_by"] == operator[1]["name"]
    assert '"bulb_on":true' in client.get(f"/api/bulb/{DEV}/command").text

    report(client, True, "remote_command")  # the device applied it and says so
    n = node(client, h)
    assert n["state"] == "on" and n["sync"] == "in_sync" and n["last_source"] == "remote_command"


def test_manual_button_press_becomes_the_new_intent_and_is_not_reverted(client, operator):
    h = operator[0]
    report(client, False, "boot")
    command(client, h, False)
    r = report(client, True, "manual_button")  # someone pressed the physical button
    assert r.json()["bulb_on"] is True  # the backend follows the button; the next poll must not turn it off again
    assert '"bulb_on":true' in client.get(f"/api/bulb/{DEV}/command").text
    n = node(client, h)
    assert n["sync"] == "in_sync" and n["commanded_by"] == "button" and n["last_source"] == "manual_button"
    # the first sketch's name for a button press is treated the same way
    assert report(client, False, "state_change").json()["bulb_on"] is False


def test_boot_and_heartbeat_never_overwrite_the_desired_state(client, operator):
    h = operator[0]
    command(client, h, True)
    report(client, False, "boot")  # safe boot: relay OFF until the backend's command is applied
    assert node(client, h)["desired_on"] is True and node(client, h)["sync"] == "pending"
    report(client, False, "heartbeat")
    assert node(client, h)["desired_on"] is True
    assert '"bulb_on":true' in client.get(f"/api/bulb/{DEV}/command").text


def test_node_goes_offline_when_heartbeats_stop(client, operator):
    report(client, True, "heartbeat")
    assert node(client, operator[0])["online"] is True
    with SessionLocal() as db:
        db.query(BulbDevice).one().last_seen_at = utcnow() - timedelta(seconds=120)
        db.commit()
    n = node(client, operator[0])
    assert n["online"] is False and n["state"] == "on" and n["age_s"] >= 119  # last known state is kept, flagged offline


def test_event_log_records_changes_and_commands_but_not_idle_heartbeats(client, operator):
    h = operator[0]
    report(client, False, "boot")
    report(client, False, "heartbeat")
    report(client, False, "heartbeat")
    command(client, h, True)
    report(client, True, "remote_command")
    report(client, True, "manual_button")
    kinds = [(e["kind"], e["source"]) for e in client.get(f"/api/operator/bulbs/{DEV}/events", headers=h).json()]
    assert kinds == [("status", "manual_button"), ("status", "remote_command"), ("command", "remote"), ("status", "boot")]


def test_access_control(client, operator, driver):
    assert client.get("/api/operator/bulbs").status_code == 401
    assert client.post(f"/api/operator/bulbs/{DEV}/command", json={"bulb_on": True}).status_code == 401
    assert command(client, driver[0], True).status_code == 403
    assert client.get("/api/operator/bulbs", headers=driver[0]).status_code == 403


def test_device_endpoints_require_the_device_key_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "device_api_key", "k3y-secret")
    assert report(client, True).status_code == 401
    assert client.get(f"/api/bulb/{DEV}/command").status_code == 401
    ok = {"X-Device-Key": "k3y-secret"}
    assert client.post(f"/api/bulb/{DEV}/status", json={"bulb_on": True}, headers=ok).status_code == 200
    assert client.get(f"/api/bulb/{DEV}/command", headers=ok).status_code == 200


def test_input_validation(client, operator):
    assert client.post(f"/api/bulb/{DEV}/status", json={}).status_code == 422
    assert client.post(f"/api/bulb/{DEV}/status", json={"bulb_on": True, "source": "magic"}).status_code == 422
    assert client.post("/api/bulb/BAD ID!/status", json={"bulb_on": True}).status_code == 422
    assert client.post("/api/operator/bulbs/x/command", json={"bulb_on": True}, headers=operator[0]).status_code == 422
    assert client.post(f"/api/operator/bulbs/{DEV}/command", json={"bulb_on": "maybe"}, headers=operator[0]).status_code == 422


def test_a_second_node_is_independent(client, operator):
    client.post("/api/bulb/porch-light/status", json={"bulb_on": True, "source": "boot"})
    command(client, operator[0], True, dev="porch-light")
    ids = {b["device_id"]: b for b in client.get("/api/operator/bulbs", headers=operator[0]).json()}
    assert ids["porch-light"]["desired_on"] is True
    assert ids.get(DEV, {"desired_on": False})["desired_on"] is False  # the other node is untouched
