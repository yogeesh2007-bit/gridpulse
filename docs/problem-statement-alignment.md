# Problem-statement alignment

**Input** - `POST /recommend` (one call) or `POST /drivers/request` + `POST /recommendation`. Accepted field names:
`lat`, `lng` (or `lon`), `soc` (or `soc_current`), `target_soc` (or `soc_target`), `deadline` (or `deadline_minutes`).
`deadline` is minutes from now **or** an ISO-8601 departure time (stored as `deadline_minutes` and absolute `deadline_at`).

```json
{ "lat": 13.0067, "lng": 80.0037, "soc": 12, "target_soc": 80, "deadline": 90 }
```

**Station state** - every station in `GET /stations`, `GET /stations/{id}` and `/dashboard/state` carries
`state: { available_ports, queue_count, current_load_w, site_power_limit_w, lat, lng }` (also flattened on the station).
These are *derived live* from active sessions, the queue and the site's base load (they cannot drift out of date);
internal values stay in kW.

**Seed** - Station A: 1 port, 0 free, queue 2, 25 / 30 kW (83 %), nearby. Station B: 2 ports, 1 free, queue 0,
42 / 100 kW (42 %), ~4.4 km away. So the nearer station is the worse choice for most drivers until A's queue clears.

**Score** - `final_score = travel_time + predicted_wait + charging_time + load_penalty - urgency_bonus`
(minutes, lower is better; details in CLAUDE.md section 13). Infeasible stations (offline, would arrive below the 5 %
reserve, no site power) are excluded and ranked last with a reason.

**Output** (`/recommend`, `/recommendation`):
`chosen_station`, `ranking[]` (rank, final_score, travel_time_min, predicted_wait_min, charge_time_min, score_breakdown,
station_state), `predicted_wait_min`, `travel_time_min`, `charge_time_min`, `score_breakdown`, `explanation {text, source}`,
`formula`, plus `warnings`, `routing` (confidence / fallback) and the earlier `chosen`, `candidates`, `summary`.

**Dashboard** - both stations (ports free, queue, load vs limit, chosen badge) and a "Latest recommendation" panel: the
ranking with every score term, and the reason.

**OpenRouter** - optional; `POST /explanation` only rewrites the already-computed explanation text (guarded: must name the
chosen station and use only numbers from the facts, else the rule-based text is kept). The ranking is computed before and
independently of it (covered by `test_llm_never_influences_the_decision`).
