# Milestone 3 — real ESP32 path with simulated fallback

Extends Milestone 2 in place. The app still runs with **no hardware at all**; a simulated device still works; a real
ESP32 plugs into the same protocol and is reported honestly.

**Verification status (be precise about what was and was not proven):**

| Claim | Evidence |
|---|---|
| Backend + all earlier behaviour | 91 automated tests (66 from M1/M2 unchanged and green, 25 new) |
| Whole flow with no device / simulated device / stale / real-device *protocol* | `scripts/e2e_milestone3.py` against the live server (ALL PASS) |
| Existing Milestone 2 database upgrades in place | server restarted on the M2 `gridpulse.db` (new table + columns added automatically) |
| Firmware compiles | `pio run` → SUCCESS on arduino-esp32 **2.0.17** (RAM 14.3 %, flash 63.8 %) **and** on **3.3.12** (`pio run -e esp32_core3`; RAM 15.4 %, flash 76.7 %), so both PWM API branches build. The 3.x env needs PlatformIO Core ≥ 6.2. |
| **Firmware runs on a real ESP32** | **NOT verified — no hardware was available.** The protocol it speaks is exercised by the e2e script, but the firmware itself has never executed on a chip. |
| INA219 readings, MOSFET output, button | **NOT verified** (hardware pending). Code paths exist; dry-run and sensor-missing fallbacks are implemented and flagged. |

## Run / update the backend

```powershell
cd C:\Users\yogee\GridPulse\backend
pip install -r requirements.txt          # no new dependencies in M3
python -m uvicorn app.main:app --reload --port 8000
```
The database upgrades itself on start (adds the `devices` table and new `telemetry` columns; Station A gets a
placeholder device row). To be safe copy `backend\gridpulse.db` first. Dashboard: <http://localhost:8000/dashboard>
(listen on your LAN IP for the ESP32: add `--host 0.0.0.0`).

## Device protocol (what the firmware and the fake device both speak)

| Step | Call | Notes |
|---|---|---|
| Announce | `POST /device/register` `{device_id, device_mode: "real"\|"simulated", station_code?, dry_run, firmware_version, sensor_status}` | on boot and after every Wi-Fi reconnect; `station_code` binds the device to a station |
| Poll | `GET /device/{id}/command` (alias `GET /control/command/{id}`) | ~1 Hz; returns `{command, power_fraction, duty_pct, seq, valid_for_s, generated_at, …}`; records delivery |
| Acknowledge | `POST /device/{id}/ack` `{seq, command, status: applied\|rejected\|failsafe\|local_override, detail?, dry_run?, output_pct?}` | once per new `seq`; an ack for an older `seq` is reported `stale_ack` and ignored |
| Report | `POST /telemetry/update` `{device_id, voltage, current, power, temperature?, mode, note?, source, dry_run, sensor_status, event?, local_override?}` | response also carries the current command + device state |
| Inspect | `GET /devices`, `GET /device/{id}`, `GET /control/state`, `GET /telemetry/latest`, `GET /dashboard/state` | |

## How "real", "simulated", "stale" are decided

* `device_mode` follows the **`source` declared by the newest packet** (`real` | `simulated`); packets from before M3
  have no `source` and count as `real`. Switching mode clears button/ack/delivery history so simulator activity is
  never attributed to hardware.
* Freshness comes from the newest telemetry packet only: **live** ≤ 10 s, **stale** ≤ 60 s, **offline** beyond / never.
* `hardware_confirmed` = real device **and** live **and** not holding (LOCAL_OVERRIDE / FAILSAFE / FAULT_*) **and**
  (it echoes the commanded `mode` **or** acknowledged the current `seq` as applied).

| Situation | `confirmation` | `source` | Dashboard label |
|---|---|---|---|
| No device / never reported (seeded placeholder) | simulated | simulated | AWAITING HARDWARE → SIMULATED |
| Software-only station (Station B) | simulated | simulated | SOFTWARE-SIMULATED |
| Simulated device, live | simulated | simulated | SIMULATED DEVICE |
| Real device stale / offline | simulated | simulated | HARDWARE STALE / OFFLINE → SIMULATED (+ reason) |
| Real, live, not running the command yet (or overriding) | hardware-pending | hardware | HARDWARE PENDING |
| Real, live, echoed/acked | hardware-confirmed | hardware | HARDWARE CONFIRMED (+ DRY-RUN if applicable) |

`fallback_reason` (in `/devices`, `/control/state`, the dashboard) says exactly why control is not hardware-confirmed.
`caveats` lists dry-run, missing/errored sensor (values are placeholders), simulated device, local override.

## Data model additions (requirement F)

`devices` table + `telemetry` columns. Derived fields are computed on read so they can never go stale in the DB.

| Field | Where | Kind |
|---|---|---|
| device_id, device_mode, dry_run, sensor_status, firmware_version, registered | `devices` | stored |
| telemetry_source, last_seen_at, last_polled_at | `devices` | stored |
| last_command_sent {command, seq, at}, last_ack {seq, command, status, detail, at} | `devices` | stored |
| local_override, button_count, last_button_at | `devices` | stored |
| source, dry_run, sensor_status, event, local_override | `telemetry` (per packet) | stored |
| command_generated_at (= when the current command seq first appeared) | `control_states.changed_at` | stored |
| last_telemetry_at, freshness, **stale**, telemetry_age_s | from newest packet | derived |
| **hardware_confirmed**, confirmation, control_source, output_physical | `assess()` | derived |
| **ack_status** none/pending/applied/rejected/failsafe/local_override (for the *current* command) | `assess()` | derived |
| fallback_reason, caveats | `assess()` | derived |

## Upload the firmware

Files: `firmware/esp32_station_a/esp32_station_a.ino` (+ `platformio.ini`). Pin map and wiring: `docs/wiring.md`.

1. Edit the **CONFIG** block at the top of the sketch: `WIFI_SSID`, `WIFI_PASSWORD`, `BACKEND_BASE_URL`
   (`http://<laptop-LAN-IP>:8000`), `DEVICE_ID` (keep `esp32-station-a` for Station A), pins if yours differ.
   **Leave `DRY_RUN = true`** until the MOSFET/bulb are wired and tested (see wiring bring-up order).
2. Find the laptop IP (`ipconfig`) and start the backend with `--host 0.0.0.0`; allow port 8000 through Windows
   Firewall for private networks. ESP32 and laptop must be on the same 2.4 GHz network.
3. **Arduino IDE:** install the *esp32 by Espressif* board package; Library Manager → install **Adafruit INA219**
   (accept Adafruit BusIO) and **ArduinoJson (v7.x)**; Board = *ESP32 Dev Module*; select the port; Upload.
   **PlatformIO:** `cd firmware\esp32_station_a; pio run -t upload; pio device monitor`.
4. Serial monitor at **115200**. Expected: `INA219 ready` (or `NOT FOUND … placeholder`), `[wifi] connected`,
   `[net] register -> HTTP 200`, then a `[cycle] …` line every second and `[net] ack seq=1 applied -> HTTP 200`.

## Test checklists

**A. Simulated mode (no hardware)**
1. Start backend, open the dashboard → header says `hardware: software-simulated`, Station A shows
   *AWAITING HARDWARE → SIMULATED*, Station B *SOFTWARE-SIMULATED*; recommendations/reservations work.
2. `python firmware\tools\fake_esp32.py` → within ~3 s: device **SIMULATED**, **LIVE**, control label
   *SIMULATED DEVICE* (never "hardware confirmed"), ack `ACKED`, tile `SIMULATED`.
3. `--press-button-every 10` → button count increments, `LOCAL OVERRIDE` badge toggles.

**B. Real telemetry mode**
1. Flash the firmware (DRY_RUN true). Dashboard: device **REAL**, **LIVE**, **DRY-RUN**; tile `REAL LIVE`.
2. Control label *HARDWARE CONFIRMED · DRY-RUN*; `Latest sent` and `last ack` show times.
3. INA219 unplugged → `SENSOR MISSING`, cells show `–` with "placeholder"; plugged in → real V/A/W.
4. Wi-Fi/backend down for > 15 s → serial shows `FAILSAFE`, output stays OFF (dry-run: reported only).

**C. Stale telemetry fallback**
1. With the real device live, unplug/reset it. After 10 s: `STALE`; after 60 s: `OFFLINE`; label
   *HARDWARE STALE/OFFLINE → SIMULATED*, fallback reason names the age; header says software-simulated; the app keeps working.
2. Power it back: `LIVE` and *HARDWARE CONFIRMED* again within a few seconds (it re-registers automatically).

**D. Command polling & acknowledgment**
1. Set Station A "Site limit kW" to 26 → Apply → command `REDUCE_LOAD` (80 %), `command #` increases, ack shows `PENDING`.
2. Within ~1 s the device polls it: `Latest sent` updates, serial `ack seq=… applied`, ack `ACKED`.
3. Press the button (short): device shows `LOCAL OVERRIDE`, control `HARDWARE PENDING` (device is holding OFF), ack `local_override`.
4. Reset demo data → command back to `NORMAL`.
- API spot checks: `curl localhost:8000/devices`, `curl localhost:8000/device/esp32-station-a/command`.

## Automated checks
```powershell
cd backend; python -m pytest -q            # 91 tests
python scripts\e2e_milestone3.py           # live, ~45 s, re-seeds the DB, spawns fake_esp32.py
```

## Honest limits / assumptions to confirm
* Pin map (SDA 21, SCL 22, button 27, output 25) is an **assumption** — confirm against your wiring.
* Firmware is compiled, not run on hardware; timing, Wi-Fi, HTTP behaviour on the chip are unproven.
* Chip temperature is not reported (`REPORT_CHIP_TEMPERATURE = false`) because the backend uses `temperature` for its
  over-temperature rule; attach a real sensor before enabling.
* Overcurrent/overvoltage latch is active only when `DRY_RUN = false`. Fuse + gate pull-down are external.
* One device is mapped to Station A; Station B stays a digital twin (software-only).
* HTTP on the LAN, no authentication or TLS — fine for a demo, not for anything else.
* Simulated and real share `device_id` `esp32-station-a`; mode follows the latest packet's `source`, so a simulator
  running against a real device would flip it (by design, visible on the dashboard). Use another `--device` id to run both.

## Next recommended milestone — 4: closed-loop demo hardening
Bring up the real power path (MOSFET + bulb) following `docs/wiring.md`, tune duty ↔ kW mapping and current limit,
feed *measured* power back into the station load model (replace the simulated load for Station A), add a second
physical/simulated device for Station B, an operator "force command" override, and a rehearsed demo script with a
recorded fallback video.
