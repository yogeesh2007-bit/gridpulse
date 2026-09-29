# Milestone 1 — Working software app (no hardware needed)

Status: **done and verified** (32 automated tests pass; live end-to-end run against the real server with real OSRM
routing and a real OpenRouter call).

## Run it

```powershell
cd C:\Users\yogee\GridPulse\backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

- Driver app: <http://localhost:8000/>
- Operator dashboard: <http://localhost:8000/dashboard>
- API docs (Swagger): <http://localhost:8000/docs>

The database (`backend/gridpulse.db`) is created and seeded automatically on first start.

Optional config: copy `.env.example` to `.env` (project root) and set `OPENROUTER_API_KEY`. `.env` is gitignored.

### Phone / HTTPS (geolocation)
Browser geolocation only works in a **secure context**: `https://…` or `http://localhost`. On a phone the laptop's
`http://192.168.x.x:8000` is *not* secure, so GPS is blocked (the app then shows the manual-location fallback).
Use a tunnel:

```powershell
cloudflared tunnel --url http://localhost:8000
```
Open the printed `https://….trycloudflare.com` URL on the phone.

## Tests

```powershell
cd C:\Users\yogee\GridPulse\backend
python -m pytest -q          # 32 tests: engine math, queue/power simulation, full API flow
```

## Manual test checklist

| # | Action | Expected |
|---|---|---|
| 1 | `GET /health` | `status: ok`, shows `openrouter_configured` true/false |
| 2 | Open `/dashboard` | 2 station cards (A physical: 1 port, 1 active + 2 queued; B digital twin: 2 ports, 1 active), tiles, empty request table |
| 3 | Open `/`, click **Use my location** (localhost/HTTPS) | Browser asks permission; lat/lon/accuracy appear and update live |
| 4 | Deny permission (or use plain http on a phone) | Clear message; manual coordinates box opens; entering coords works |
| 5 | Enter SOC 12 → 80, deadline 90, submit | Recommended station, travel/wait/charge/total, finish time, reason text; comparison table for both stations |
| 6 | With the seeded state near the default centre | Station B (farther) is recommended over nearer Station A because A has a queue; text says "not the nearest" |
| 7 | Reason text | Starts rule-based; within seconds is replaced by AI-phrased text if a key is set (else stays rule-based, label says so) |
| 8 | **Reserve** | Reservation card with queue position/times; dashboard shows it within 3 s |
| 9 | Dashboard → set Station B "Site limit" to 20 → Apply | B's load bar turns red/over-limit as needed, queue re-planned; new requests show reduced kW |
| 10 | Dashboard → **Take offline** on B, submit another request | B is never recommended (shown "Station is offline") |
| 11 | SOC 6% at a point ~100 km away | "No usable station" (stranded-risk guard), reservation refused |
| 12 | **Reset demo data** | Back to the seeded scenario |

## What is implemented

- **Engine** (`services/scheduling.py`, pure/deterministic): SOC-after-drive, taper charge time, urgency
  (low SOC + tight deadline), priority classes, non-preemptive priority queue simulation over N ports, site
  power-headroom gating, station scoring `travel + (1+urgency)·wait + charge + 2·minutes_past_deadline`,
  stranded-risk and offline rejection.
- **State** (`services/state.py`): reservations move queued → active → done by wall-clock; sessions are created/closed;
  queue is re-planned after every booking, cancellation and operator change.
- **Routing** (`services/routing.py`): OSRM public API with cache + cooldown; haversine fallback.
- **Explanations** (`services/explanation.py`): deterministic text always first; optional OpenRouter rephrasing with
  guards (must mention the chosen station, be long enough, and contain only numbers present in the facts; up to 3
  attempts) — otherwise the rule-based text is kept. The LLM never influences ranking.
- **API**: `GET /health`, `POST /seed`, `GET /stations`, `GET /stations/{id}`, `PATCH /stations/{id}`,
  `POST /drivers/request`, `POST /recommendation`, `POST /explanation`, `POST /reservations`,
  `GET /reservations`, `GET /reservations/{id}`, `POST /reservations/{id}/cancel`, `GET /dashboard/state`.
- **DB tables**: stations, driver_requests, reservations, sessions, explanation_logs.

## Known limits (deliberate, for later milestones)

- Station B is a *static* digital twin (its queue evolves only through reservations and wall-clock time); no
  background load simulator yet.
- Power gating is checked at the moment a session starts; there is no mid-session throttling of active sessions yet
  (that is the control layer, Milestone 3).
- Vehicle consumption (0.18 kWh/km), 5% reserve and 80% taper are constants in `scheduling.py`.
- No auth; single demo operator.
- Free OpenRouter models vary per call; some return unusable text — the guard rejects those and falls back.
- Seed station coordinates are placed around `CENTER_LAT/CENTER_LON` (default: Chennai). Change in `.env` or call
  `POST /seed?center_lat=..&center_lon=..`.

## Next milestone recommendation — Milestone 2: telemetry path (ESP32 + INA219)

1. `POST /telemetry` + `telemetry` table; `GET /stations/{id}/telemetry` for the latest values.
2. ESP32 sketch reading INA219 (V/I/W), serial + WiFi HTTP POST every second.
3. Dashboard live V/I/W panel on Station A, stale/offline detection.
4. A software telemetry simulator (same schema) so the UI works before hardware arrives.
5. Then Milestone 3: command endpoint, MOSFET PWM control, failsafe, button event, closed-loop demo.
