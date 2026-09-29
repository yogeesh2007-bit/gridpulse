# Milestone 2 — live routing, real-time updates, ESP32-ready telemetry, simulated control

Built as an in-place upgrade of Milestone 1 (no rewrite). Status: **verified** — 66 automated tests pass, plus a live
end-to-end run (`scripts/e2e_milestone2.py`) with real OSRM routing, a real OpenRouter call and a separate fake-ESP32
process, and headless-Chrome rendering of the dashboard.

## Run

```powershell
cd C:\Users\yogee\GridPulse\backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```
Driver `http://localhost:8000/` · Dashboard `http://localhost:8000/dashboard` · API docs `http://localhost:8000/docs`

Try the hardware loop with no hardware (second terminal):
```powershell
python firmware\tools\fake_esp32.py            # polls commands, posts telemetry every second, Ctrl+C to stop
```
Then on the dashboard: set Station A "Site limit kW" to 26 → Apply. Watch the control command flip to `REDUCE_LOAD`,
the badge go `HARDWARE PENDING` → `HARDWARE CONFIRMED`, and the telemetry power drop ~20%.

Full automated check (WARNING: re-seeds the DB): `python scripts\e2e_milestone2.py`
Unit/API tests: `cd backend; python -m pytest -q`

## What changed

| Area | Change |
|---|---|
| Routing | OSRM (already present) now has health counters, 429-aware back-off (2× cooldown), `routing.status()` on the dashboard; every candidate carries `route_source`, `route_estimated`, `route_fallback`. |
| Recommendation | Score now `travel + (1+urgency)·wait + charge + 2·deadline_miss + load_penalty` (`load_penalty` = 40 min per 100 points of projected site utilisation above 85%). Response adds `summary` (route distance/time, wait, charge, `ready_at`, `fallback_routing_used`, `reason_summary`) and `routing` (`confidence`, note). |
| Live location | `POST /driver/location/update` stores the position, updates the request origin, returns route ETAs to every station (throttled: reuses ETAs < 8 s old). Driver app pushes updates from `watchPosition` when it moved ≥ 20 m or every 15 s, only while the tab is visible. |
| Refresh flow | Driver app "Refresh recommendation" button + optional 30 s auto-refresh; shows if the recommendation changed. |
| Telemetry | `POST /telemetry/update`, `GET /telemetry/latest[?device_id=]`, table `telemetry` (history, 500/device). Fields: device_id, voltage, current, power, temperature (nullable), timestamp, mode, note. Stale after 10 s. |
| Control | `services/control.py`: pure `decide_command()` → `NORMAL / REDUCE_LOAD / PRIORITIZE_URGENT / PAUSE_FLEX` with reason + `power_fraction`; persisted per station (`control_states`), transitions logged (`control_events`). `GET /control/state`, `GET /control/command/{device_id}` (what an ESP32 polls). |
| Confirmation | `simulated` (no fresh telemetry) → `hardware-pending` (device online, mode differs) → `hardware-confirmed` (device echoes the command in `mode`). |
| Dashboard | Control + telemetry panel per station, reservation timeline (lanes per port), live driver locations, route ETAs for the latest request, control decision log, routing health line, ESP32 tile. `/dashboard/state` now includes all of it. |
| DB | New tables `live_locations`, `telemetry`, `control_states`, `control_events`; `stations.device_id` added by a tiny automatic migration (Milestone 1 databases keep working — tested). |

## Control rules (deterministic, evaluated in order)

1. Station offline → `REDUCE_LOAD`, output 0%.
2. Telemetry temperature ≥ 70 °C → `REDUCE_LOAD`, 50%.
3. Urgent driver present **and** a flexible session is charging **and** (over limit **or** site ≥ 90%) → `PAUSE_FLEX` (keep only non-flexible load).
4. Over the site limit → `REDUCE_LOAD`, scaled to the allowed power (30–95%).
5. Urgent driver present and (urgent waiting for a port, or ≥ 2 queued, or site ≥ 85%, or flexible sessions can yield) → `PRIORITIZE_URGENT`, 100%.
6. Site ≥ 85% → `REDUCE_LOAD`, 80%.
7. Otherwise `NORMAL`.

Thresholds live at the top of `services/control.py`.

## ESP32 contract (for the firmware, Milestone 3)

Loop every ~1 s: `GET /control/command/esp32-station-a` → `{command, power_fraction, duty_pct, seq, valid_for_s}`;
apply `duty_pct` (clamped locally); `POST /telemetry/update` with the INA219 readings and `mode` = the command being
run. The POST response also contains the current command, so one round trip is enough. **Fail safe:** if no valid
command arrives within `valid_for_s` (15 s), output OFF. `firmware/tools/fake_esp32.py` is a working reference client.

## Honest limits

- Control commands are **simulated** until real hardware reports telemetry. `fake_esp32.py` packets say
  `fake-esp32 (simulated device)` in `note`, and will show as "hardware confirmed" — that is the tool doing its job,
  not real hardware. The ESP32 firmware itself is not written yet (Milestone 3).
- Commands affect the reported/simulated load only; they do not yet re-plan the queue or stretch session durations.
- Only one device is mapped (Station A ↔ `esp32-station-a`); Station B is a digital twin without telemetry.
- OSRM is the public demo server (no SLA, rate limited). On failure the app falls back to straight-line estimates and
  says so (badge, warning, explanation note, dashboard routing line).
- Free OpenRouter models vary per call; junk output is rejected by guards and the rule-based text is used.
- Phone GPS needs HTTPS or localhost (use `cloudflared tunnel --url http://localhost:8000`). Not yet tested on a real
  phone in this session.

## Next: Milestone 3 (hardware actuation)
ESP32 firmware (INA219 + WiFi + command polling + PWM/MOSFET output with failsafe and current limit), button event
endpoint, wiring doc, then the closed-loop demo with the real bulb.
