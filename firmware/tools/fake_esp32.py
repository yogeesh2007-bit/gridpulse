"""Fake ESP32: a SIMULATED device for testing the GridPulse device protocol without hardware.

It follows the exact same protocol the real firmware uses:
  1. POST /device/register            device_mode="simulated"  (so the backend never mistakes it for hardware)
  2. GET  /device/{id}/command        the command the backend wants
  3. POST /device/{id}/ack            "applied" whenever a new command (new seq) is received
  4. POST /telemetry/update           source="simulated", sensor_status="simulated", dry_run=true
  5. fail safe: if commands stop arriving for longer than valid_for_s, output goes to 0 (mode FAILSAFE)

The dashboard therefore shows it as a SIMULATED DEVICE - never as "hardware confirmed". Use it to develop and demo
the whole loop before the real ESP32 is connected. Stop it and the backend falls back to software-simulated control
after the telemetry goes stale.

Usage:
    python firmware/tools/fake_esp32.py                       # run until Ctrl+C
    python firmware/tools/fake_esp32.py --count 20 --interval 0.5
    python firmware/tools/fake_esp32.py --press-button-every 15   # also simulate a button toggling local override
"""
from __future__ import annotations

import argparse
import os
import random
import time
from datetime import datetime, timezone

import httpx

NOMINAL_V = 12.0
NOMINAL_A = 1.5  # bulb current at 100% output
WIRE_DROP_OHMS = 0.1
FIRMWARE = "fake-esp32 1.0"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--device", default="esp32-station-a")
    ap.add_argument("--station", default=None, help="station code to bind to on registration (e.g. A)")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between polls/packets")
    ap.add_argument("--count", type=int, default=0, help="number of telemetry packets to send (0 = forever)")
    ap.add_argument("--press-button-every", type=float, default=0.0,
                    help="simulate a button press (toggle local override) every N seconds; 0 = never")
    ap.add_argument("--no-register", action="store_true", help="skip POST /device/register (tests auto-registration)")
    ap.add_argument("--key", default=os.environ.get("DEVICE_API_KEY", ""),
                    help="device API key (X-Device-Key); defaults to $DEVICE_API_KEY. Needed when the backend sets DEVICE_API_KEY")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    client = httpx.Client(base_url=args.base_url, timeout=5.0,
                          headers={"X-Device-Key": args.key} if args.key else None)
    fraction, mode, valid_for = 0.0, "FAILSAFE", 15.0  # boot state: output OFF until a command arrives
    last_cmd_ok = 0.0
    last_seq = None
    override = False
    pending_event = None
    last_press = time.monotonic()
    temp = 28.0
    sent = 0
    registered = args.no_register

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg)

    print(f"[fake-esp32] SIMULATED device '{args.device}' -> {args.base_url}  (Ctrl+C to stop)")
    try:
        while args.count == 0 or sent < args.count:
            t0 = time.monotonic()

            if not registered:
                try:
                    r = client.post("/device/register", json={
                        "device_id": args.device, "device_mode": "simulated", "station_code": args.station,
                        "dry_run": True, "firmware_version": FIRMWARE, "sensor_status": "simulated"})
                    r.raise_for_status()
                    registered = True
                    log("[fake-esp32] registered as simulated device")
                except Exception as exc:
                    log(f"[fake-esp32] register failed: {type(exc).__name__}: {exc}")

            if args.press_button_every and time.monotonic() - last_press >= args.press_button_every:
                override, pending_event, last_press = not override, "button_press", time.monotonic()
                log(f"[fake-esp32] simulated button press -> local override {'ON' if override else 'off'}")

            cmd = None
            try:
                r = client.get(f"/device/{args.device}/command")
                r.raise_for_status()
                cmd = r.json()
                last_cmd_ok = time.monotonic()
            except Exception as exc:
                if time.monotonic() - last_cmd_ok > valid_for:  # fail safe
                    fraction, mode = 0.0, "FAILSAFE"
                log(f"[fake-esp32] command poll failed: {type(exc).__name__}: {exc}")

            if cmd is not None:
                valid_for = float(cmd["valid_for_s"])
                if override:
                    fraction, mode = 0.0, "LOCAL_OVERRIDE"
                else:
                    fraction, mode = float(cmd["power_fraction"]), cmd["command"]
                if cmd["seq"] != last_seq:  # new command => acknowledge exactly once
                    try:
                        client.post(f"/device/{args.device}/ack", json={
                            "seq": cmd["seq"], "command": cmd["command"],
                            "status": "local_override" if override else "applied",
                            "detail": f"simulated: output {fraction * 100:.0f}%", "dry_run": True,
                            "output_pct": round(fraction * 100, 1)}).raise_for_status()
                        last_seq = cmd["seq"]
                    except Exception as exc:
                        log(f"[fake-esp32] ack failed: {type(exc).__name__}: {exc}")

            current = NOMINAL_A * fraction * (1 + random.uniform(-0.01, 0.01))
            voltage = NOMINAL_V - WIRE_DROP_OHMS * current + random.uniform(-0.02, 0.02)
            power = voltage * current
            temp += (28.0 + 22.0 * fraction - temp) * 0.1  # first-order warm-up towards a load-dependent temperature
            packet = {
                "device_id": args.device,
                "voltage": round(voltage, 3), "current": round(current, 3), "power": round(power, 3),
                "temperature": round(temp, 1),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": mode,
                "note": "fake-esp32 (simulated device)",
                "source": "simulated", "dry_run": True, "sensor_status": "simulated",
                "local_override": override,
            }
            if pending_event:
                packet["event"], pending_event = pending_event, None
            try:
                resp = client.post("/telemetry/update", json=packet)
                resp.raise_for_status()
                ctl = resp.json().get("control") or {}
                sent += 1
                log(f"[fake-esp32] #{sent:>3} mode={mode:<17} {voltage:5.2f} V {current:5.3f} A {power:6.2f} W "
                    f"{temp:4.1f} C | backend: {ctl.get('command', '?')} ({ctl.get('confirmation', '?')})")
            except Exception as exc:
                print(f"[fake-esp32] telemetry post failed: {type(exc).__name__}: {exc}")
            time.sleep(max(0.0, args.interval - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        print("\n[fake-esp32] stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
