# Bulb node: ESP32 + relay + button, controlled from the GridPulse dashboard

## Architecture
```
button ─┐                                  ┌─ POST /api/bulb/{id}/status  (boot, heartbeat, manual_button, remote_command)
        ├─ ESP32 (firmware/gridpulse_bulb_node) ─┤
relay ◄─┘   relay OFF at boot, local first  └─ GET  /api/bulb/{id}/command  (polled every 3 s)
                         │ X-Device-Key
FastAPI  services/bulbs.py  ── SQLite: bulb_devices (desired vs reported state), bulb_events (log)
   └─ operator API + WebSocket ─► React: Operator > Hardware > Bulb panel  (status, ON/OFF, source, activity)
```
**Rules:** *desired* = what the backend wants, *reported* = what the device says. A button press becomes the new desired state
(never reverted). A dashboard command sets desired; the device applies it on its next poll and reports `remote_command`. Boot and
heartbeat reports never change desired. The device ignores backend commands for 2.5 s after a button press. Local control never
waits for the network. Node is *online* if it reported within 25 s; offline nodes keep their last state, flagged.

## API contract (device id: `^[a-z0-9][a-z0-9_-]{1,39}$`; conventions: `bulb-01`)
| Who | Call | Body / reply |
|---|---|---|
| device (header `X-Device-Key` if the backend sets `DEVICE_API_KEY`) | `POST /api/bulb/{id}/status` | `{"bulb_on":bool,"source":"boot\|heartbeat\|manual_button\|remote_command","rssi":int,"firmware":str}` -> `{"accepted":true,"bulb_on":desired,"seq":n}` |
| device | `GET /api/bulb/{id}/command` | `{"bulb_on":bool,"seq":n,"commanded_by":str,"commanded_at":iso}` (compact JSON: the firmware matches `"bulb_on":true`) |
| operator | `GET /api/operator/bulbs` | list of nodes (`online, state, sync, last_source, age_s, rssi, ...`); also in the WebSocket `state` as `bulbs` |
| operator | `POST /api/operator/bulbs/{id}/command` | `{"bulb_on":bool}` |
| operator | `GET /api/operator/bulbs/{id}/events` | newest-first activity log |

## Wiring (verified)
Relay IN -> GPIO25, button -> GPIO27 to GND, relay VCC -> VIN/5V, relay GND -> GND. 12 V adapter + -> fuse -> relay COM; relay NO -> bulb +;
bulb - -> adapter -; adapter - -> ESP32 GND. Active-LOW relay by default (`RELAY_ACTIVE_LOW` in config.h). INA219 and the LR7843 MOSFET are not used here.
**Low-voltage loads only.**

## Setup
1. `cd firmware/gridpulse_bulb_node`, copy `config.example.h` to `config.h` (git-ignored) and fill in Wi-Fi, `BACKEND_BASE_URL`, `DEVICE_API_KEY`
   (Render dashboard > Environment), `DEVICE_ID`. **Rotate the Wi-Fi password if it was ever pasted anywhere.**
2. Flash: Arduino IDE (ESP32 Dev Module) or `pio run -t upload`; serial monitor at 115200.
3. Deployed backend needs this code: push to GitHub (Render redeploys), then `cd web && vercel --prod` for the UI.
4. Open the site > sign in as an operator > Hardware tab.

## Test checklist
* Serial shows `[wifi] connected`, `[net] POST status (boot) -> 200`; bulb is OFF at boot.
* Dashboard: node "Online", state OFF. Press **Turn ON**: bulb lights within ~3 s, UI shows "Remote command".
* Press the physical button: bulb toggles instantly, UI shows "Button press on the device" and stays that way.
* Unplug the ESP32: after ~25 s the node shows "Offline" with the last state. Replug: it reconnects and re-syncs.
* `pytest backend/tests/test_bulbs.py` (12 tests) and `python scripts/e2e_bulb.py` (browser, uses a firmware emulator).

## Assumptions and risks
* iPhone hotspots: the laptop and ESP32 must share the hotspot only if you use a *local* backend; the deployed backend works from anywhere.
* Free Render sleeps after 15 idle minutes (first request slow) and resets its database on restart.
* `TLS_INSECURE = true`: https is encrypted but the certificate is not verified (demo setting).
* Polling (3 s) is used, not push: simplest robust option on ESP32; latency up to 3 s. MQTT/WebSocket would cut that.
* The physical bulb path was verified by you (button toggles the relay); the network path is verified here by tests and an emulator, not on your board yet.
