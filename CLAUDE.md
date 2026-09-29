# CLAUDE.md — GridPulse Project Brief

> Read this first. It is the source of truth for product intent, scope, architecture and build order.
> If a request conflicts with this file, flag the conflict before changing direction.

---

## 1. Project Overview

**GridPulse** is a smart EV-charging recommendation and control system. It uses live driver location, battery urgency, queue prediction and station power constraints to (a) recommend the station that finishes charging the driver **earliest and safely**, and (b) control charging priority/power at the station.

It is a **hackathon prototype** made of three connected layers:

1. **Driver App** — mobile-friendly web app using real phone geolocation.
2. **Backend + Operator Dashboard** — deterministic recommendation, reservation, queue and power-allocation engine, with a live dashboard.
3. **Hardware Prototype** — low-voltage ESP32 charging *emulator* (INA219 sensing + MOSFET-driven 12 V bulb) that physically proves the backend's control decisions.

The demo's punch line: **decision → actuation → sensing** in a closed loop. Not just UI.

## 2. Problem Statement

Charger apps show "nearest charger." That is not what a driver needs. A driver needs to know:
- Which station can **finish charging me earliest**?
- Is the **queue** long?
- Does the station have **spare power capacity** right now?
- Should an **urgent low-battery** driver get priority?
- Can a **flexible** user be delayed/throttled safely?

Problems solved: nearest-only choice, unpredictable waits, poor prioritization, no power-aware scheduling, no closed loop between recommendation and control.

## 3. Solution Summary

- Driver submits: live location, current SOC, target SOC, departure deadline.
- Backend evaluates every station: route time (OSRM), queue wait, available power, charge time, deadline risk, urgency.
- Backend returns a ranked recommendation + expected travel / wait / charge / completion + explanation.
- Backend creates a reservation; dashboard updates live.
- Station-level power allocator decides per-session power (urgent full, flexible throttled) within the station power limit; the decision is sent to the ESP32, which drives the MOSFET; INA219 reports the real response.

**Core principle: deterministic, engineered logic is the controller. AI is never in the decision path.**

## 4. Final MVP Scope

In scope:
- FastAPI backend + SQLite.
- 2 seeded stations: **Station A** (physical-ready, backed by ESP32 rig) and **Station B** (simulated digital twin).
- Driver web app with real browser geolocation, SOC/target/deadline form, recommendation card.
- Deterministic scoring/recommendation engine, reservation + queue model.
- Power-aware allocation (priority classes, station power limit).
- Operator dashboard: stations, queues, reservations, urgency, load, power limit, control decisions, live telemetry.
- Optional OpenRouter endpoint for explanation/summary text only (with deterministic template fallback).
- ESP32 telemetry (INA219) → backend → dashboard.
- Later: ESP32 MOSFET control (PWM/switch), button event, final demo.

## 5. Non-Goals / Out of Scope

- NOT a real high-voltage EV charger, EVSE, or AC/mains switching. **Never design for mains.**
- NOT full OCPP (only conceptually aligned; may name fields OCPP-style).
- NOT vehicle-to-vehicle charging.
- NOT a chatbot / AI assistant. NOT a "nearest charger map" app.
- NOT user auth, payments, multi-tenant, or production hardening.
- NOT real-world charger-availability data ingestion (stations are seeded).
- NOT battery-physics accuracy (simple taper model is enough).
- LLM must never do ranking, safety, scheduling priority, or hardware control policy.

## 6. User Flow (Driver)

1. Open app on phone (HTTPS tunnel URL) → grant location permission.
2. Enter current SOC %, target SOC %, departure deadline (time or "minutes from now"). Optional: vehicle battery kWh (default 40).
3. Tap "Find best charger" → `POST /api/recommend`.
4. See best station with: travel ETA, wait, charge duration, completion time, deadline OK/at-risk, alternatives, "why".
5. Tap "Reserve" → `POST /api/reservations`. Status page polls reservation state (queued / charging / throttled / done).

## 7. Demo Flow (Judges)

1. Phone opens app, shares live location.
2. Enter SOC (e.g. 12%), target 80%, deadline (e.g. 90 min).
3. Backend compares Station A (physical) vs Station B (digital twin); recommends by **earliest safe completion**, not distance (demo should include a case where the *farther* station wins because of queue/power).
4. Dashboard updates in real time (reservation appears, queue/load change, decision logged).
5. Add a flexible driver → dashboard shows it throttled/delayed while urgent driver gets full power.
6. (Hardware ready) Backend control decision changes the physical bulb brightness via ESP32 + MOSFET.
7. INA219 voltage/current/power on dashboard confirms the change. Button press = local event (e.g. "vehicle plugged in" / "session stop").

## 8. System Architecture

```
 Phone (Driver App, HTTPS via Cloudflare Quick Tunnel)
        │  POST /api/recommend, /api/reservations
        ▼
 ┌───────────────────── Laptop ─────────────────────┐
 │ FastAPI backend                                   │
 │  ├─ routing service  (OSRM + haversine fallback)  │
 │  ├─ recommendation engine (deterministic)         │
 │  ├─ queue/reservation model                       │
 │  ├─ power allocator (priority + station limit)    │
 │  ├─ telemetry ingest + control command queue      │
 │  ├─ explain service (OpenRouter, optional)        │
 │  └─ SQLite                                        │
 │ Operator Dashboard (static HTML/JS, polls/WS)     │
 └───────────────▲───────────────────────────────────┘
                 │ HTTP (or MQTT later) over WiFi
            ESP32 (Station A)
       INA219 ── sense ── MOSFET ── 12 V bulb   (12 V adapter, fuse)
```

Station A = real telemetry/control. Station B = simulated: its load, queue and telemetry are generated by a backend simulator so the same engine treats both identically.

## 9. Hardware Architecture (low-voltage only)

- **ESP32** dev board: WiFi, reads INA219 over I2C, drives MOSFET gate (PWM), reads button (GPIO with pull-up + debounce).
- **INA219**: bus voltage, current, power (high-side, in series with the load). Note its 26 V bus / ~3.2 A range at 0.1 Ω shunt — fine for 12 V bulb.
- **LR7843 MOSFET module**: low-side switching/PWM of the bulb (logic-level gate OK for 3.3 V drive on the module).
- **12 V bulb + holder**: visible "charging" load. Brightness ≈ power delivered.
- **12 V adapter** + **fuse holder with ≥2 A fuse** on the positive supply line.
- **Push button**: local event input.
- Common ground between adapter, MOSFET module, INA219, ESP32.

Power mapping: backend allocates station kW → normalized `power_fraction` (0–1) → ESP32 PWM duty (capped, e.g. `max_duty`). One firmware constant maps kW ↔ duty for demo scaling.

**Hardware status (as of project start):** ESP32 and INA219 available. **Pending delivery:** LR7843 MOSFET, 12 V bulb, bulb holder, 12 V adapter, fuse holder + fuse (≥2 A), button. → Phases 1–2 must not depend on the output power path.

## 10. Software Architecture

- **Backend:** FastAPI, SQLite (via SQLAlchemy or plain `sqlite3`; keep simple), Pydantic models, pure-Python engine modules that are unit-testable with no I/O.
- **Engine purity rule:** `engine/` contains pure functions (inputs in, decisions out). Network/DB lives in `services/`, `routers/`. Routing (OSRM) is injected so tests use a fake.
- **Frontend:** plain HTML/CSS/JS first (no build step): `frontend/driver/` and `frontend/dashboard/`, served by FastAPI `StaticFiles`. React/Vite only if a real need appears.
- **ESP32 firmware:** Arduino framework (PlatformIO or Arduino IDE): telemetry loop → later command polling + PWM.
- **Real-time:** dashboard polls `GET /api/dashboard/state` every 1–2 s (MVP). Upgrade to WebSocket `/ws/dashboard` later. ESP32 posts telemetry via HTTP every ~1 s and polls `GET /api/stations/{id}/command` (MQTT optional, later).

## 11. API Dependencies

| API | Use | Notes |
|---|---|---|
| Browser Geolocation API | live phone location | Needs secure context (HTTPS or localhost) + permission. Use `watchPosition`/`getCurrentPosition` with `enableHighAccuracy`. |
| OSM Nominatim | reverse geocode / place label | Public usage policy: ≤1 req/s, send a User-Agent, cache results. Cosmetic only. |
| OSRM public (`router.project-osrm.org`) | route distance + duration | `GET /route/v1/driving/{lon},{lat};{lon},{lat}?overview=false`. Coordinates are **lon,lat**. Timeout ~3 s → fall back to haversine × 1.3 ÷ 30 km/h. Demo server, not for load. |
| OpenRouter | explanation text only | `POST https://openrouter.ai/api/v1/chat/completions`, model `openrouter/free` or a `:free` variant. Key in `.env` (`OPENROUTER_API_KEY`). Must degrade gracefully. |
| Cloudflare Quick Tunnel | HTTPS for phone | `cloudflared tunnel --url http://localhost:8000` |

All external calls: short timeout, cached where possible, never block the core decision (fallbacks required).

## 12. Data Model (SQLite)

- **drivers**: `id, name, vehicle_battery_kwh, max_charge_kw, created_at`
- **stations**: `id, name, kind ('physical'|'simulated'), lat, lon, ports, max_kw, power_limit_kw, base_load_kw, is_online, device_id`
- **reservations**: `id, driver_id, station_id, status ('queued'|'active'|'throttled'|'done'|'cancelled'), soc_start, soc_target, deadline_ts, urgency, priority_class ('urgent'|'normal'|'flexible'), arrival_ts, planned_start_ts, planned_end_ts, allocated_kw, created_at`
- **telemetry**: `id, station_id, ts, bus_v, current_a, power_w, duty_pct, button_state, source ('esp32'|'sim')`
- **control_events**: `id, station_id, reservation_id, ts, kind ('set_power'|'pause'|'resume'|'failsafe'|'button'), target_kw, target_duty_pct, reason, acked_at`
- **decisions**: `id, ts, driver_id, request_json, candidates_json, chosen_station_id, score_breakdown_json, explanation_text, explanation_source ('template'|'llm')`

## 13. Scheduling / Recommendation Logic (deterministic)

Per candidate station `s`, for driver `d`:

1. **Travel:** `travel_min` and `dist_km` from OSRM (fallback haversine).
2. **Feasibility:** `soc_arrival = soc_now − dist_km × kwh_per_km / battery_kwh × 100` (default 0.18 kWh/km, 40 kWh). If `soc_arrival < reserve_soc (5%)` → station **infeasible** (stranded risk); never recommend it unless all are infeasible (then warn).
3. **Arrival time:** `t_arr = now + travel_min`.
4. **Wait:** stations have `ports`; each port has a "free at" time derived from active sessions + earlier reservations (priority-ordered). `wait_min = max(0, earliest_free_port − t_arr)`. Urgent drivers may jump ahead of flexible *queued* (not active) reservations; active sessions are never preempted, only throttled.
5. **Power available:** `avail_kw = min(station.max_kw, d.max_charge_kw, station.power_limit_kw − station.other_load_kw)`, floored at `min_kw` (else station is "power-blocked" → adds wait).
6. **Charge time:** `energy = (soc_target − soc_arrival)/100 × battery_kwh`; `charge_min = energy / avail_kw × 60`, with a simple taper: energy above 80% SOC charged at 50% power.
7. **Completion:** `t_done = t_arr + wait_min + charge_min`.
8. **Urgency** `u ∈ [0,1]` = `max(soc_urgency, deadline_urgency)`:
   - `soc_urgency`: 1.0 at ≤10% SOC, linearly → 0 at ≥50%.
   - `deadline_urgency`: from slack = `deadline − earliest_possible_completion`; tight/negative slack → near 1.
   - Class: `u ≥ 0.7 urgent`, `u ≤ 0.3 flexible`, else `normal`.
9. **Score (lower is better)** - the problem-statement formula, in minutes:
   `final_score = travel_time + predicted_wait + charging_time + load_penalty - urgency_bonus`
   - `load_penalty = 60 x max(0, projected_site_utilisation - 0.70)` (projected = site load once this driver is charging / site limit).
   - `urgency_bonus = 30 x urgency x immediacy x deadline_factor`, `immediacy = 1/(1 + wait/15)`, `deadline_factor` = 1 if the deadline is met,
     fading to 0 when missed by >= 30 min; capped so the score never goes negative. Urgent drivers are therefore drawn to stations that can start them soon *and* on time.
   - Rounded components add up exactly to `final_score`. Constants live at the top of `services/scheduling.py`.
10. **Output:** ranked candidates, each with full breakdown; chosen = min score among feasible.

### Station power allocation (control)
Given active sessions at a station and `power_limit_kw`:
- Sort by priority class then urgency then arrival.
- Allocate greedily: urgent → up to their max; normal → next; flexible → remainder, but never below `min_kw` unless paused; total ≤ `power_limit_kw − base_load_kw`.
- Output per session `allocated_kw`; emit `control_events` only when an allocation **changes** (with `reason`).
- For Station A, the session's allocation → `power_fraction` → ESP32 duty.

All constants live in one `engine/config.py` and are surfaced in the dashboard for tuning. Every formula has unit tests.

## 14. OpenRouter Role & Limits

Allowed: natural-language "why this station" for the driver, operator summary of current state, optional Q&A fallback.
Forbidden: ranking, scoring, safety, priority scheduling, hardware control, anything the deterministic engine must own.
Rules: LLM receives the **already-computed** score breakdown as JSON and only rephrases it; never invents numbers. Always produce a template-based explanation first (`explanation_source='template'`); LLM output replaces it only if it returns in time (≈4 s timeout). Missing key / failure = silent fallback. Never put secrets in the repo.

## 15. Real-Time Communication Plan

- MVP: HTTP polling (dashboard 1–2 s; driver status 3 s; ESP32 telemetry POST 1 s and command GET 1 s).
- Next: WebSocket for dashboard push.
- Optional: MQTT (`gridpulse/{station}/telemetry`, `gridpulse/{station}/cmd`) — only if HTTP polling is a problem.
- Serial (USB) telemetry on ESP32 always kept as a debug path.

## 16. Development Phases

**Phase 1 (no hardware needed):** backend skeleton, SQLite + seed 2 stations, engine (scoring, queue, allocation) with tests, `/api/recommend`, `/api/reservations`, `/api/dashboard/state`, driver app with geolocation, dashboard UI, Station B simulator, optional OpenRouter explain, Cloudflare tunnel test on a real phone.

**Phase 2 (ESP32 + INA219 only):** firmware reading INA219, serial print, WiFi POST telemetry, `/api/telemetry`, dashboard live V/I/W for Station A, offline/stale detection.

**Phase 3 (parts arrived):** MOSFET wiring + PWM, command endpoint + ESP32 command polling, failsafes, button events, end-to-end closed-loop demo, rehearse + record fallback video.

## 17. Current Hardware Status

Pending: LR7843 MOSFET, 12 V bulb, bulb holder, 12 V adapter, fuse holder + fuse (≥2 A), button. Until then: Station A runs with **simulated telemetry** (same schema, `source='sim'`), swapped for real ESP32 data with no engine changes.

## 18. Safety Constraints

- Low voltage only (12 V DC max). No mains, ever. Do not claim real EVSE safety.
- Fuse (≥2 A, sized above bulb current) on positive supply.
- Firmware **failsafe**: no valid command within N seconds (e.g. 5 s) → output OFF. Boot state = OFF. WiFi loss = OFF.
- Firmware caps duty (`MAX_DUTY`) and trips OFF if INA219 current > limit (e.g. 1.8 A) or voltage out of range.
- Backend never sends duty directly as raw truth: it sends `target_kw`/`power_fraction`; the ESP32 clamps locally.
- Common ground, gate pull-down resistor on MOSFET so it's OFF when ESP32 floats/resets.
- Don't touch wiring while powered. Verify polarity before connecting INA219.

## 19. Immediate Next Tasks

1. Scaffold backend + config + seed data (Task 1).
2. Engine: scoring + queue + allocation with unit tests (Task 2).
3. `/api/recommend` + `/api/dashboard/state` + Station B simulator.
4. Driver app + dashboard UIs.
5. Tunnel test on phone.
6. ESP32 INA219 telemetry sketch.

## 20. File / Folder Structure (as built, Milestone 1)

```
GridPulse/
├─ CLAUDE.md   .env.example   .gitignore        (.env holds the OpenRouter key; never commit)
├─ backend/
│  ├─ requirements.txt  pytest.ini
│  ├─ app/
│  │  ├─ main.py  config.py  db.py  models.py  schemas.py  seed.py
│  │  ├─ services/
│  │  │  ├─ scheduling.py     PURE engine: urgency, queue sim, power gating, scoring
│  │  │  ├─ recommendation.py orchestration: snapshots -> routes -> candidates -> ranking
│  │  │  ├─ state.py          lifecycle (queued/active/done), reschedule, serializers
│  │  │  ├─ routing.py        OSRM + haversine fallback
│  │  │  └─ explanation.py    rule-based text + optional guarded OpenRouter rephrasing
│  │  └─ routers/  stations.py  drivers.py  reservations.py  dashboard.py
│  └─ tests/  conftest.py  test_scheduling.py  test_api.py
├─ frontend/  driver.html  dashboard.html  app.js  styles.css
├─ firmware/esp32_station_a/   (Milestone 2)
└─ docs/  milestone-1-notes.md   (run + test instructions)
```

**Status:** Milestones 1-3 complete in software. M1: driver app, dashboard, deterministic engine, reservations, guarded
OpenRouter explanations. M2: live location push, OSRM health + fallback, load-aware scoring, telemetry API, control layer
(`NORMAL | REDUCE_LOAD | PRIORITIZE_URGENT | PAUSE_FLEX`). M3: real-vs-simulated device model (`devices` table,
`/device/register|{id}|{id}/command|{id}/ack`, `/devices`), honest confirmation/freshness/fallback reporting,
real ESP32 firmware (`firmware/esp32_station_a/`, compiled but NOT yet run on hardware), simulated device kept
(`firmware/tools/fake_esp32.py`). 91 tests pass; live checks in `scripts/e2e_milestone3.py`. Docs: docs/milestone-{1,2,3}-notes.md,
docs/wiring.md. Run: `cd backend && python -m uvicorn app.main:app --reload --port 8000`.
Next: Milestone 4 = bring up the real power path (MOSFET + bulb), closed-loop demo hardening (see milestone-3 notes).

**Decisions/naming to preserve:** command names above; confirmation states `simulated | hardware-pending | hardware-confirmed`
(never label simulated-device or stale-hardware control as hardware-confirmed); freshness `live (<=10 s) | stale (<=60 s) |
offline`; `device_mode` follows the `source` of the latest packet (`real|simulated`, missing = real) and switching mode
clears activity history; `hardware_confirmed` requires real + live + not holding (LOCAL_OVERRIDE/FAILSAFE/FAULT_*) + mode
echo or applied ack; ESP32 device id for Station A is `esp32-station-a`; firmware boots OUTPUT OFF, fails safe after
`valid_for_s`, has `DRY_RUN` (default true) and reports it; INA219 missing => placeholder values flagged `sensor_status=missing`.
LLM output is validated and never used for decisions. **Rejected:** LLM-driven ranking; MQTT/WebSocket for now; chip
temperature as load temperature; tripping faults in dry-run; two sources of truth for telemetry freshness.
**Hardware still pending:** MOSFET, bulb, holder, 12 V adapter, fuse, button (firmware supports all; unverified).

**Milestone 5 - unified web app (current architecture).** One URL: FastAPI serves the built React app (`web/`, Vite + TS + Tailwind) and
the API. Routes `/`, `/signin`, `/signup`, `/app`, `/app/driver`, `/app/operator`. Auth: scrypt passwords, JWT access token (15 min, in memory) +
rotating refresh token (httpOnly cookie, reuse detection with a 10 s two-tab grace, family revocation), roles `driver|operator`
(operator sign-up needs `OPERATOR_INVITE_CODE`). API under `/api/{auth,driver,operator,geo,explain,ws}`; WebSocket `/api/ws?token=`
(operators get full dashboard `state`, drivers get own reservations + public stations; closed with 4401 on token expiry).
Background `services/scheduler.py` ticks the reservation lifecycle + control commands; `services/realtime.py` broadcasts. Geocoding:
Nominatim with DB cache, 1 req/s throttle, coordinate fallback. Legacy open endpoints exist only with `LEGACY_API_ENABLED=true`
(tests/scripts); device endpoints use optional `DEVICE_API_KEY` (`X-Device-Key`). Production refuses unsafe config at startup.
206 backend tests + `scripts/e2e_browser.py` (Playwright, real Chrome). Run: build `web/` then `uvicorn app.main:app`. See README.md.
**Preserve:** drivers only ever see their own data (404 not 403 for others' ids); request driver_name comes from the account, never the client;
AI only rewords explanations; blank `.env` values use defaults (comments must not follow blank values).

**Bulb node (relay + button):** device id convention `bulb-01`; pins relay=GPIO25 (active-LOW, `RELAY_ACTIVE_LOW`), button=GPIO27 (INPUT_PULLUP);
API `/api/bulb/{id}/status|command` (device key) + `/api/operator/bulbs*`; desired-vs-reported model, button press wins, boot/heartbeat never
change desired; secrets only in git-ignored `firmware/gridpulse_bulb_node/config.h`. See docs/bulb-node.md. Unresolved: not yet flashed/verified on
the real board; Wi-Fi password was shared in chat (rotate); free Render sleeps/resets; poll latency up to 3 s.

## 21. Build Priorities

1. Deterministic engine correct + tested (this is the product).
2. End-to-end driver → recommendation → dashboard on a real phone.
3. Demo scenario where farther station wins (seed data + simulator tuned for it).
4. Telemetry path.
5. Physical actuation.
6. Polish: explanations, visuals. LLM last.

Rule: never block on hardware; never let a nice-to-have (LLM, MQTT, WebSocket) delay the closed-loop demo.

## 22. Future Upgrades

Real OCPP 1.6/2.0.1 adapter, more stations/ports, real charger availability feeds, forecasted station load, user accounts, ML-based wait prediction (still gated by deterministic safety rules), V2G, tariff-aware scheduling, mobile PWA/native app.

---

## Working Agreements for Claude Sessions

- Keep the engine pure and tested; do not sneak I/O or LLM calls into it.
- Prefer simple, buildable code; match existing style; no premature frameworks.
- Update this file when scope, endpoints, schema or hardware status change.
- Ask before adding dependencies beyond FastAPI/uvicorn/pydantic/httpx/pytest.
- Never commit `.env` or secrets.
