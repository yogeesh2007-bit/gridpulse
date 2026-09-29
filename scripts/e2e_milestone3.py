"""Milestone 3 live end-to-end check: simulated device, stale fallback, and the real-device protocol.

Needs the backend running on :8000.   WARNING: it re-seeds the database (POST /seed), wiping current data.
Takes ~45 s (it waits for telemetry to go stale).      Run:  python scripts/e2e_milestone3.py

IMPORTANT (honesty): there is no physical ESP32 in this test. Part 2 uses firmware/tools/fake_esp32.py, which
declares itself SIMULATED. Part 3 drives the *real-device protocol* (register as real, poll, ack, telemetry with
source="real") from this script to prove the backend handles a real device correctly -- that is a protocol test
of the backend, not proof that hardware works. Hardware proof comes from flashing the firmware.
"""
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://localhost:8000"
DEV = "esp32-station-a"
c = httpx.Client(base_url=BASE, timeout=60)
ok = True


def check(label, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + label, extra)


def ctl():
    return next(s for s in c.get("/control/state").json()["stations"] if s["station_code"] == "A")


def dev():
    return c.get(f"/device/{DEV}").json()


def hw():
    return c.get("/dashboard/state").json()["hardware_summary"]


print("== Part 1: no device at all (software-simulated fallback) ==")
c.post("/seed")
d = dev()
check("seeded placeholder device, not registered", d["placeholder"] and not d["registered"] and d["freshness"] == "offline", d["fallback_reason"])
k = ctl()
check("control is software-simulated", k["confirmation"] == "simulated" and k["source"] == "simulated" and not k["hardware_confirmed"])
check("dashboard hardware mode = software", hw()["mode"] == "software", hw())
rec = c.post("/recommendation", json={"request_id": c.post("/drivers/request", json={
    "driver_name": "NoHW", "lat": 13.0067, "lon": 80.0037, "soc_current": 20, "soc_target": 80, "deadline_minutes": 120}).json()["id"]}).json()
check("recommendations still work with no hardware", rec["chosen"] is not None, rec["chosen"]["name"])

print("\n== Part 2: simulated device (fake_esp32.py) ==")
fake = subprocess.Popen([sys.executable, str(ROOT / "firmware/tools/fake_esp32.py"), "--interval", "0.5", "--count", "200", "--quiet",
                         "--press-button-every", "9"])
time.sleep(7)
d = dev()
check("registered as SIMULATED and live", d["device_mode"] == "simulated" and d["freshness"] == "live" and d["registered"], f'source={d["telemetry_source"]}')
k = ctl()
check("simulated device is NEVER hardware-confirmed", k["confirmation"] == "simulated" and not k["hardware_confirmed"] and k["device_mode"] == "simulated", k["fallback_reason"])
check("command was polled and acknowledged by the simulator", d["last_command_sent"] and d["last_ack"] and d["last_ack"]["status"] in ("applied", "local_override"), d["last_ack"])
check("dashboard hardware mode = simulated", hw()["mode"] == "simulated", hw())
time.sleep(6)  # the simulated button presses toggle local override
d = dev()
check("simulated button press reached the backend", d["button_count"] >= 1, f'presses={d["button_count"]} override={d["local_override"]}')

print("\n== Part 3: stop the simulator -> stale -> fallback ==")
fake.terminate(); fake.wait()
time.sleep(12)
d = dev()
check("telemetry stale, control falls back to software", d["freshness"] in ("stale", "offline") and ctl()["confirmation"] == "simulated", d["fallback_reason"])
check("dashboard hardware mode = software again", hw()["mode"] == "software", hw())

print("\n== Part 4: REAL-device protocol (protocol test from this script, no physical hardware) ==")
r = c.post("/device/register", json={"device_id": DEV, "device_mode": "real", "station_code": "A", "dry_run": True,
                                     "firmware_version": "protocol-test", "sensor_status": "missing"}).json()
check("register as real / dry-run / sensor missing", r["device_mode"] == "real" and r["dry_run"] and r["sensor_status"] == "missing")


def real_packet(mode, **extra):
    body = {"device_id": DEV, "voltage": 0, "current": 0, "power": 0, "mode": mode, "source": "real", "dry_run": True,
            "sensor_status": "missing", "note": "protocol test (no hardware)",
            "local_override": False}  # the real firmware sends this in every packet
    body.update(extra)
    return c.post("/telemetry/update", json=body).json()


cmd = c.get(f"/device/{DEV}/command").json()
real_packet(cmd["command"])
d, k = dev(), ctl()
check("real + live + mode echo => hardware-confirmed (dry-run, sensor placeholder flagged)",
      k["confirmation"] == "hardware-confirmed" and k["source"] == "hardware" and d["dry_run"] and not d["output_physical"]
      and any("placeholder" in x for x in d["caveats"]), d["caveats"])
check("hardware mode = real", hw()["mode"] == "real", hw())

a_id = ctl()["station_id"]
c.patch(f"/stations/{a_id}", json={"site_limit_kw": 26})  # tighten grid limit -> REDUCE_LOAD
d = dev()
check("new command generated, ack PENDING until the device answers", d["current_command"]["command"] == "REDUCE_LOAD" and d["ack_status"] == "pending", d["current_command"])
new = c.get(f"/device/{DEV}/command").json()
check("device polls the new command", new["command"] == "REDUCE_LOAD" and new["seq"] == d["current_command"]["seq"], f'{new["command"]} #{new["seq"]} {new["duty_pct"]}%')
a = c.post(f"/device/{DEV}/ack", json={"seq": new["seq"], "command": new["command"], "status": "applied", "detail": "dry-run: would output 80%", "dry_run": True}).json()
check("ack recorded", a["ack_status"] == "applied" and not a["stale_ack"], a)
real_packet("REDUCE_LOAD")
check("confirmed again after the new mode is echoed", ctl()["confirmation"] == "hardware-confirmed" and ctl()["command"] == "REDUCE_LOAD")
real_packet("LOCAL_OVERRIDE", event="button_press", local_override=True)
check("button press => local override, control PENDING (device is not running the command)",
      dev()["local_override"] and dev()["button_count"] == 1 and ctl()["confirmation"] == "hardware-pending")

print("\n== Part 5: real device goes silent -> stale hardware -> fallback -> recovery ==")
time.sleep(12)
d, k = dev(), ctl()
check("real telemetry STALE: labelled, not confirmed, simulated fallback with reason",
      d["freshness"] in ("stale", "offline") and d["stale"] and not d["hardware_confirmed"] and k["confirmation"] == "simulated"
      and "stale" in k["fallback_reason"].lower() or "offline" in (k["fallback_reason"] or "").lower(), k["fallback_reason"])
check("app still serves recommendations while hardware is stale", c.get("/dashboard/state").status_code == 200)
real_packet("REDUCE_LOAD")
check("device returns -> LIVE and confirmed again", dev()["freshness"] == "live" and ctl()["confirmation"] == "hardware-confirmed")

c.post("/seed")  # leave the demo clean
print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
