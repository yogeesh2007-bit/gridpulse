# GridPulse

Smart EV-charging recommendation, reservation and grid-aware control, as **one web app on one URL**.

* **Frontend:** React + Vite + TypeScript + Tailwind (`web/`), served by FastAPI in production
* **Backend:** FastAPI + SQLite, JWT access + rotating refresh tokens, WebSockets (`backend/`)
* **Decisions are deterministic** (`final_score = travel_time + predicted_wait + charging_time + load_penalty - urgency_bonus`).
  OpenRouter is an optional layer that only rewords the explanation.
* **Hardware:** ESP32 firmware + simulator share one device protocol (`firmware/`, `docs/wiring.md`). Low-voltage demo only.

## Run it (one URL)

```powershell
# 1) build the web app (once, and after frontend changes)
cd web
npm install
npm run build

# 2) run the API + web app
cd ..\backend
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000
```
Open **http://localhost:8000**  ·  API docs: http://localhost:8000/docs

| Route | What |
|---|---|
| `/` | landing page |
| `/signin`, `/signup` | authentication |
| `/app` | redirects to your role's area |
| `/app/driver` | driver experience (drivers only) |
| `/app/operator` | operator dashboard (operators only) |

**Development accounts** (created automatically when `APP_ENV=development`):
`driver@gridpulse.local / Driver123!` and `operator@gridpulse.local / Operator123!`.
Sign up as an operator with the invite code `operator-demo` (set `OPERATOR_INVITE_CODE` to change it).

**Frontend hot-reload:** run the backend as above, then `cd web && npm run dev` and open http://localhost:5173
(Vite proxies `/api` and the WebSocket to :8000).

**On a phone:** browser location needs HTTPS or localhost: `cloudflared tunnel --url http://localhost:8000`.

## Configuration
Copy `.env.example` to `.env`. Production (`APP_ENV=production`) refuses to start without a strong `JWT_SECRET` and an operator invite
code, and with `LEGACY_API_ENABLED=true`. Set `COOKIE_SECURE=true` behind HTTPS and `DEVICE_API_KEY` for devices.

## Tests
```powershell
cd backend; python -m pytest -q                 # backend: auth, API, realtime, engine, devices
cd ..\web;  npm run typecheck                   # frontend types
cd ..;      pip install playwright; python scripts\e2e_browser.py   # real-browser end-to-end (server must be running)
```

## Hardware code (ESP32)

There are two ESP32 sketches in `firmware/`. Both are **low-voltage demos** (12 V DC at most). Never connect mains.

| Sketch | What it is | Talks to |
|---|---|---|
| `firmware/esp32_station_a/` | The GridPulse station device: INA219 current sensing, PWM/MOSFET output, button, failsafes, dry-run mode | the backend's device protocol (`/device/register`, `/device/{id}/command`, `/device/{id}/ack`, `/telemetry/update`) |
| `firmware/gridpulse_bulb_node/` | Relay + push-button bulb node, **integrated with the dashboard** | `/api/bulb/{id}/status` and `/command` |
| `firmware/relay_bulb_node/` | The original standalone relay + button sketch (`bulb-01`) | two URLs you configure (`POST_URL`, `GET_URL`) |

**Pointing `esp32_station_a` at the deployed backend:** set `BACKEND_BASE_URL` to your `https://...onrender.com` address and
`DEVICE_API_KEY` to the key Render generated (Render dashboard, Environment). The sketch speaks both `http://` (LAN) and `https://`;
with `TLS_INSECURE = true` the traffic is encrypted but the server certificate is not verified (demo setting).

### `gridpulse_bulb_node`: the bulb node wired into GridPulse (recommended)

The relay + button node, integrated end to end: the operator dashboard (**Hardware** tab) shows the bulb's live state, sends ON/OFF, and
shows whether the last change came from the physical button or a remote command. Full architecture, API contract, wiring, setup and
test checklist: **[docs/bulb-node.md](docs/bulb-node.md)**. Secrets live in a git-ignored `config.h` (copy `config.example.h`).

### `relay_bulb_node`: relay + button bulb node

A small standalone node that switches a bulb through a relay, from either a physical button or a remote command.

**Wiring**

| Part | ESP32 pin | Notes |
|---|---|---|
| Relay module input | GPIO 25 | **active-LOW**: `LOW` = bulb ON, `HIGH` = bulb OFF |
| Push button | GPIO 27 to GND | uses the internal pull-up, pressed = `LOW` |

**How it works**

1. **Boot:** the relay is set OFF first (before Wi-Fi), then it connects to Wi-Fi and reports `boot`.
2. **Button:** a 50 ms software debounce; each press toggles the bulb and immediately reports `state_change`.
3. **Remote control:** every 3 s it polls `GET_URL`. If the reply contains `"bulb_on":true` or `"bulb_on":false` and that differs from the current state, it switches the relay and reports `remote_command`.
4. **Heartbeat:** every 10 s it reports its state so a server can tell the node is alive.
5. **Reconnect:** if Wi-Fi drops it reconnects in the main loop (the relay keeps its last state meanwhile).

**What it sends** (`POST` to `POST_URL`, JSON):

```json
{"device_id":"bulb-01","bulb_on":true,"source":"state_change","rssi":-58}
```

`source` is one of `boot`, `state_change`, `remote_command`, `heartbeat`. The server answers `GET_URL` with `{"bulb_on":true}` or `{"bulb_on":false}`.

**Set up and flash**

1. Edit the top of `relay_bulb_node.ino`: `WIFI_SSID`, `WIFI_PASS`, `POST_URL`, `GET_URL` (they are placeholders; do not commit real passwords).
2. Arduino IDE: board *ESP32 Dev Module*, upload. Or PlatformIO: `cd firmware/relay_bulb_node && pio run -t upload && pio device monitor` (115200 baud). It needs no extra libraries and compiles cleanly.

**Things to know**

* It does **not** speak the GridPulse device protocol. It uses its own two URLs and `bulb_on` payloads, so the GridPulse backend does not serve them out of the box. Point the URLs at any small server you control, or use it standalone with the button.
* GPIO 25 is also the MOSFET output pin in `esp32_station_a`. Do not wire both sketches to the same board at once without changing a pin.
* The URLs use plain `http` with no authentication, which is fine on a private network for a demo, not for anything else.
* A relay can switch mains. Keep this project to low-voltage loads only.

## Project layout
```
backend/app/  main.py config.py db.py models.py security.py deps.py
              api/       auth, driver, operator, geo, explain, ws     (authenticated product API + WebSocket)
              routers/   device protocol + legacy open API (LEGACY_API_ENABLED)
              services/  scheduling (pure engine) recommendation state booking dashboard control devices
                         realtime (WebSocket manager) scheduler (background clock) geocode routing explanation auth_service
web/src/      App.tsx main.tsx  auth/  realtime/  hooks/  lib/  components/{ui,layout,driver,operator}  pages/
firmware/     esp32_station_a (GridPulse device)  relay_bulb_node (relay + button bulb)  tools/fake_esp32.py (simulator)
docs/         milestone notes, wiring, problem-statement alignment      legacy_ui/  (old static UI, no longer served)
```
