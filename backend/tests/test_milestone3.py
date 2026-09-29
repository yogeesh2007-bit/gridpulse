"""Milestone 3: real vs simulated devices, freshness, command polling, acknowledgments."""
from datetime import timedelta

from app.db import SessionLocal, utcnow
from app.models import Telemetry

DEV = "esp32-station-a"


def pkt(**over):
    body = {"device_id": DEV, "voltage": 11.9, "current": 1.2, "power": 14.3, "mode": "NORMAL",
            "source": "real", "dry_run": False, "sensor_status": "ok"}
    body.update(over)
    return body


def register(client, **over):
    body = {"device_id": DEV, "device_mode": "real", "dry_run": False, "firmware_version": "1.0.0",
            "sensor_status": "ok"}
    body.update(over)
    return client.post("/device/register", json=body)


def device(client, device_id=DEV):
    return client.get(f"/device/{device_id}").json()


def control_a(client):
    return next(s for s in client.get("/control/state").json()["stations"] if s["station_code"] == "A")


def age_packets(seconds):
    with SessionLocal() as db:
        for t in db.query(Telemetry).all():
            t.received_at = utcnow() - timedelta(seconds=seconds)
        db.commit()


# ---- seeded placeholder ----------------------------------------------------------------------------
def test_seed_creates_placeholder_device_and_reports_software_only_station(client):
    body = client.get("/devices").json()
    assert body["count"] == 1 and body["stations_without_device"] == ["B"]
    d = body["devices"][0]
    assert d["device_id"] == DEV and d["station_code"] == "A"
    assert d["registered"] is False and d["placeholder"] is True
    assert d["freshness"] == "offline" and d["hardware_confirmed"] is False and d["last_telemetry_at"] is None
    assert "not reported" in d["fallback_reason"] or "has not" in d["fallback_reason"]
    c = control_a(client)
    assert c["confirmation"] == "simulated" and c["source"] == "simulated" and c["freshness"] == "offline"
    assert c["fallback_reason"]


# ---- registration ---------------------------------------------------------------------------------
def test_register_real_device(client):
    r = register(client, dry_run=True, sensor_status="missing")
    assert r.status_code in (200, 201)
    d = r.json()
    assert d["registered"] is True and d["placeholder"] is False and d["device_mode"] == "real"
    assert d["dry_run"] is True and d["sensor_status"] == "missing" and d["station_code"] == "A"
    assert d["firmware_version"] == "1.0.0" and d["output_physical"] is False


def test_register_simulated_device_and_bind_to_station_b(client):
    r = register(client, device_id="sim-b", device_mode="simulated", station_code="B")
    assert r.status_code in (200, 201) and r.json()["station_code"] == "B"
    stations = {s["code"]: s for s in client.get("/stations").json()}
    assert stations["B"]["device_id"] == "sim-b"
    assert client.get("/devices").json()["stations_without_device"] == []


def test_register_conflict_and_validation(client):
    assert register(client, device_id="intruder", station_code="A").status_code == 409  # A already bound
    assert register(client, device_mode="hologram").status_code == 422
    assert register(client, device_id="").status_code == 422
    assert register(client, device_id="x", station_code="Z").status_code == 404


def test_unregistered_device_is_auto_registered_by_telemetry(client):
    r = client.post("/telemetry/update", json=pkt(device_id="newcomer", source="simulated"))
    assert r.status_code == 201 and r.json()["registered_device"] is False  # not bound to a station
    d = device(client, "newcomer")
    assert d["registered"] is True and d["device_mode"] == "simulated" and d["station_code"] is None


# ---- real telemetry, freshness and confirmation ----------------------------------------------------
def test_real_live_telemetry_is_hardware_confirmed(client):
    register(client)
    r = client.post("/telemetry/update", json=pkt()).json()
    assert r["control"]["confirmation"] == "hardware-confirmed"
    d = device(client)
    assert (d["device_mode"], d["telemetry_source"], d["freshness"], d["stale"]) == ("real", "real", "live", False)
    assert d["hardware_confirmed"] is True and d["fallback_reason"] is None and d["output_physical"] is True
    c = control_a(client)
    assert c["confirmation"] == "hardware-confirmed" and c["source"] == "hardware" and c["hardware_confirmed"] is True
    assert c["device_mode"] == "real" and c["freshness"] == "live" and c["fallback_reason"] is None


def test_packets_without_source_are_treated_as_real_for_backward_compatibility(client):
    body = pkt()
    del body["source"]
    client.post("/telemetry/update", json=body)
    assert device(client)["telemetry_source"] == "real"


def test_simulated_packets_are_never_hardware_confirmed(client):
    register(client, device_mode="simulated", dry_run=True)
    client.post("/telemetry/update", json=pkt(source="simulated", dry_run=True))
    d = device(client)
    assert d["device_mode"] == "simulated" and d["freshness"] == "live" and d["hardware_confirmed"] is False
    assert "simulated" in d["fallback_reason"].lower()
    c = control_a(client)
    assert c["confirmation"] == "simulated" and c["source"] == "simulated" and c["hardware_confirmed"] is False
    assert c["device_mode"] == "simulated" and c["freshness"] == "live"


def test_device_mode_follows_the_packet_source_in_both_directions(client):
    register(client)
    client.post("/telemetry/update", json=pkt(source="simulated"))
    assert device(client)["device_mode"] == "simulated"
    client.post("/telemetry/update", json=pkt(source="real"))
    assert device(client)["device_mode"] == "real"


def test_stale_then_offline_real_telemetry_falls_back_to_simulated_control(client):
    register(client)
    client.post("/telemetry/update", json=pkt())
    age_packets(30)
    d = device(client)
    assert d["freshness"] == "stale" and d["stale"] is True and d["hardware_confirmed"] is False
    assert "stale" in d["fallback_reason"].lower()
    c = control_a(client)
    assert c["confirmation"] == "simulated" and c["source"] == "simulated" and c["freshness"] == "stale"
    assert "stale" in c["fallback_reason"].lower()

    age_packets(300)
    d = device(client)
    assert d["freshness"] == "offline" and "offline" in d["fallback_reason"].lower()

    client.post("/telemetry/update", json=pkt())  # device comes back
    assert device(client)["freshness"] == "live" and control_a(client)["confirmation"] == "hardware-confirmed"


def test_sensor_missing_is_flagged_and_caveated(client):
    register(client)
    client.post("/telemetry/update", json=pkt(voltage=0, current=0, power=0, sensor_status="missing"))
    d = device(client)
    assert d["sensor_status"] == "missing" and d["freshness"] == "live"
    assert any("placeholder" in c.lower() for c in d["caveats"])


def test_dry_run_is_flagged_and_not_physical(client):
    register(client, dry_run=True)
    client.post("/telemetry/update", json=pkt(dry_run=True))
    d = device(client)
    assert d["dry_run"] is True and d["output_physical"] is False
    assert any("dry-run" in c.lower() for c in d["caveats"])
    assert d["hardware_confirmed"] is True  # real device did confirm the command, just not physically


def test_button_event_sets_local_override_and_counts(client):
    register(client)
    client.post("/telemetry/update", json=pkt(event="button_press", local_override=True, mode="LOCAL_OVERRIDE"))
    d = device(client)
    assert d["local_override"] is True and d["button_count"] == 1 and d["last_button_at"]
    assert control_a(client)["confirmation"] == "hardware-pending"  # device is not running the commanded mode
    client.post("/telemetry/update", json=pkt(event="button_press", local_override=False))
    d = device(client)
    assert d["local_override"] is False and d["button_count"] == 2


# ---- command polling ------------------------------------------------------------------------------
def test_command_polling_returns_command_and_records_delivery(client):
    register(client)
    before = device(client)
    assert before["last_command_sent"] is None and before["ack_status"] == "none"
    r = client.get(f"/device/{DEV}/command")
    assert r.status_code == 200
    cmd = r.json()
    for key in ("command", "power_fraction", "duty_pct", "seq", "valid_for_s", "generated_at", "device_mode", "dry_run"):
        assert key in cmd
    assert cmd["command"] == "NORMAL" and cmd["duty_pct"] == 100
    d = device(client)
    assert d["last_command_sent"]["seq"] == cmd["seq"] and d["last_polled_at"] and d["ack_status"] == "pending"
    assert d["command_generated_at"] and d["current_command"]["command"] == "NORMAL"
    assert client.get(f"/control/command/{DEV}").status_code == 200  # Milestone 2 path still works


def test_command_polling_errors(client):
    assert client.get("/device/ghost/command").status_code == 404
    client.post("/telemetry/update", json=pkt(device_id="lonely"))
    assert client.get("/device/lonely/command").status_code == 409  # exists but bound to no station


def test_new_command_is_pending_until_acknowledged(client):
    register(client)
    cmd = client.get(f"/device/{DEV}/command").json()
    a = client.post(f"/device/{DEV}/ack", json={"seq": cmd["seq"], "command": cmd["command"], "status": "applied"})
    assert a.status_code == 200 and a.json()["ack_status"] == "applied" and a.json()["stale_ack"] is False
    assert device(client)["ack_status"] == "applied"

    st = next(s for s in client.get("/stations").json() if s["code"] == "A")
    client.patch(f"/stations/{st['id']}", json={"site_limit_kw": 27})  # 25 of 27 kW -> REDUCE_LOAD, seq+1
    d = device(client)
    assert d["current_command"]["command"] == "REDUCE_LOAD" and d["current_command"]["seq"] == cmd["seq"] + 1
    assert d["ack_status"] == "pending"  # the new command has not been delivered/acknowledged yet
    new = client.get(f"/device/{DEV}/command").json()
    assert new["command"] == "REDUCE_LOAD" and new["power_fraction"] == 0.8
    client.post(f"/device/{DEV}/ack", json={"seq": new["seq"], "command": "REDUCE_LOAD", "status": "applied",
                                            "dry_run": True, "detail": "dry-run: would output 80%"})
    d = device(client)
    assert d["ack_status"] == "applied" and d["last_ack"]["detail"].startswith("dry-run") and d["last_ack"]["at"]


def test_ack_rejected_and_stale_ack(client):
    register(client)
    cmd = client.get(f"/device/{DEV}/command").json()
    r = client.post(f"/device/{DEV}/ack", json={"seq": cmd["seq"], "command": "NORMAL", "status": "rejected",
                                                "detail": "overcurrent latched"})
    assert r.json()["ack_status"] == "rejected" and device(client)["ack_status"] == "rejected"
    old = client.post(f"/device/{DEV}/ack", json={"seq": cmd["seq"] - 1, "command": "NORMAL", "status": "applied"})
    assert old.status_code == 200 and old.json()["stale_ack"] is True
    assert device(client)["ack_status"] == "rejected"  # an old ack must not overwrite the current state


def test_ack_validation_and_unknown_device(client):
    assert client.post("/device/ghost/ack", json={"seq": 1, "command": "NORMAL", "status": "applied"}).status_code == 404
    register(client)
    assert client.post(f"/device/{DEV}/ack", json={"seq": 1, "command": "NORMAL", "status": "maybe"}).status_code == 422
    assert client.post(f"/device/{DEV}/ack", json={"command": "NORMAL", "status": "applied"}).status_code == 422


def test_ack_confirms_hardware_even_if_mode_echo_differs(client):
    register(client)
    client.post("/telemetry/update", json=pkt(mode="DRY_RUN_IDLE"))
    assert control_a(client)["confirmation"] == "hardware-pending"
    cmd = client.get(f"/device/{DEV}/command").json()
    client.post(f"/device/{DEV}/ack", json={"seq": cmd["seq"], "command": cmd["command"], "status": "applied"})
    assert control_a(client)["confirmation"] == "hardware-confirmed"


# ---- dashboard aggregate -----------------------------------------------------------------------------
def test_dashboard_state_exposes_device_model(client):
    register(client, dry_run=True)
    client.post("/telemetry/update", json=pkt(dry_run=True))
    cmd = client.get(f"/device/{DEV}/command").json()
    client.post(f"/device/{DEV}/ack", json={"seq": cmd["seq"], "command": cmd["command"], "status": "applied"})
    s = client.get("/dashboard/state").json()
    a = next(x for x in s["stations"] if x["code"] == "A")
    b = next(x for x in s["stations"] if x["code"] == "B")
    assert a["device"]["device_mode"] == "real" and a["device"]["freshness"] == "live"
    assert a["device"]["ack_status"] == "applied" and a["device"]["last_command_sent"]["seq"] == cmd["seq"]
    assert b["device"] is None
    assert s["devices"][0]["device_id"] == DEV
    hw = s["hardware_summary"]
    assert hw["real_live"] == 1 and hw["simulated_live"] == 0 and hw["mode"] == "real"


def test_hardware_summary_modes(client):
    assert client.get("/dashboard/state").json()["hardware_summary"]["mode"] == "software"  # nothing reported
    register(client, device_mode="simulated")
    client.post("/telemetry/update", json=pkt(source="simulated"))
    assert client.get("/dashboard/state").json()["hardware_summary"]["mode"] == "simulated"
    age_packets(30)
    hw = client.get("/dashboard/state").json()["hardware_summary"]
    assert hw["mode"] == "software" and hw["stale"] == 1


def test_simulated_activity_does_not_leak_into_a_real_device(client):
    """Button presses, acks and deliveries from a simulator must never be attributed to real hardware."""
    register(client, device_mode="simulated")
    client.post("/telemetry/update", json=pkt(source="simulated", event="button_press", local_override=True,
                                              mode="LOCAL_OVERRIDE"))
    cmd = client.get(f"/device/{DEV}/command").json()
    client.post(f"/device/{DEV}/ack", json={"seq": cmd["seq"], "command": cmd["command"], "status": "applied"})
    d = device(client)
    assert d["button_count"] == 1 and d["local_override"] and d["last_ack"] and d["last_command_sent"]

    client.post("/telemetry/update", json=pkt(source="real", local_override=False))  # now it says it is real
    d = device(client)
    assert d["device_mode"] == "real"
    assert d["button_count"] == 0 and d["last_button_at"] is None and d["local_override"] is False
    assert d["last_ack"] is None and d["last_command_sent"] is None and d["ack_status"] == "none"
    assert control_a(client)["confirmation"] == "hardware-confirmed"  # via mode echo only, not the old ack


def test_registering_with_a_different_mode_also_resets_activity(client):
    register(client, device_mode="simulated")
    client.post("/telemetry/update", json=pkt(source="simulated", event="button_press", local_override=True))
    assert device(client)["button_count"] == 1
    register(client, device_mode="real")
    d = device(client)
    assert d["device_mode"] == "real" and d["button_count"] == 0 and d["local_override"] is False


def test_same_mode_reregistration_keeps_history(client):
    register(client)
    client.post("/telemetry/update", json=pkt(event="button_press", local_override=True))
    register(client)  # e.g. after a Wi-Fi reconnect
    assert device(client)["button_count"] == 1


def test_earlier_ack_does_not_confirm_a_device_that_is_overriding_or_faulted(client):
    register(client)
    cmd = client.get(f"/device/{DEV}/command").json()
    client.post(f"/device/{DEV}/ack", json={"seq": cmd["seq"], "command": cmd["command"], "status": "applied"})
    client.post("/telemetry/update", json=pkt(mode="NORMAL"))
    assert control_a(client)["confirmation"] == "hardware-confirmed"
    for held_mode in ("LOCAL_OVERRIDE", "FAILSAFE", "FAULT_OVERCURRENT"):
        client.post("/telemetry/update", json=pkt(mode=held_mode))
        c = control_a(client)
        assert c["confirmation"] == "hardware-pending" and c["hardware_confirmed"] is False, held_mode
        assert device(client)["hardware_confirmed"] is False
    client.post("/telemetry/update", json=pkt(mode="NORMAL"))  # back to running the command
    assert control_a(client)["confirmation"] == "hardware-confirmed"
