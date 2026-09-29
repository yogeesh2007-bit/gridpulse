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

## Project layout
```
backend/app/  main.py config.py db.py models.py security.py deps.py
              api/       auth, driver, operator, geo, explain, ws     (authenticated product API + WebSocket)
              routers/   device protocol + legacy open API (LEGACY_API_ENABLED)
              services/  scheduling (pure engine) recommendation state booking dashboard control devices
                         realtime (WebSocket manager) scheduler (background clock) geocode routing explanation auth_service
web/src/      App.tsx main.tsx  auth/  realtime/  hooks/  lib/  components/{ui,layout,driver,operator}  pages/
firmware/     esp32_station_a (real device)  tools/fake_esp32.py (simulated device)
docs/         milestone notes, wiring, problem-statement alignment      legacy_ui/  (old static UI, no longer served)
```
