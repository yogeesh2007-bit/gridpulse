"""The problem-statement contract: spec-shaped inputs/outputs and the exact scoring formula."""
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.services import explanation as explanation_service
from app.services.scheduling import ActiveLoad, DriverNeed, StationSnapshot, evaluate_station

C = (settings.center_lat, settings.center_lon)


def spec_driver(**over):
    body = {"lat": C[0], "lng": C[1], "soc": 20, "target_soc": 80, "deadline": 120}
    body.update(over)
    return body


def snap(id=1, ports=1, kw=22.0, limit=100.0, base=0.0, active=(), queued=()):
    return StationSnapshot(id=id, code=str(id), name=f"S{id}", kind="simulated", lat=0, lon=0, ports=ports,
                           max_kw_per_port=kw, site_limit_kw=limit, base_load_kw=base, is_online=True,
                           active=tuple(active), queued=tuple(queued))


def need(**kw):
    d = dict(soc_current=30, soc_target=80, deadline_min=500, battery_kwh=40, max_charge_kw=50,
             urgency=0.2, priority_class="normal")
    d.update(kw)
    return DriverNeed(**d)


# ---- the formula: final_score = travel + wait + charge + load_penalty - urgency_bonus -------------------
def test_final_score_is_exactly_the_specified_formula():
    c = evaluate_station(need(urgency=0.6), snap(active=[ActiveLoad(20, 22)]), 3, 6)
    b = c.score_breakdown
    assert set(b) >= {"travel_time", "predicted_wait", "charging_time", "load_penalty", "urgency_bonus", "final_score"}
    assert b["final_score"] == pytest.approx(
        b["travel_time"] + b["predicted_wait"] + b["charging_time"] + b["load_penalty"] - b["urgency_bonus"], abs=0.11)
    assert c.score == b["final_score"]
    assert b["travel_time"] == c.travel_min and b["predicted_wait"] == c.wait_min and b["charging_time"] == c.charge_min


def test_urgency_bonus_is_zero_for_a_relaxed_driver_and_grows_with_urgency():
    s = snap()
    bonus = [evaluate_station(need(urgency=u), s, 3, 6).score_breakdown["urgency_bonus"] for u in (0.0, 0.5, 1.0)]
    assert bonus[0] == 0 and 0 < bonus[1] < bonus[2]


def test_urgency_bonus_rewards_starting_soon_and_meeting_the_deadline():
    n = need(urgency=1.0)
    no_wait = evaluate_station(n, snap(), 3, 6).score_breakdown["urgency_bonus"]
    long_wait = evaluate_station(n, snap(active=[ActiveLoad(60, 22)]), 3, 6).score_breakdown["urgency_bonus"]
    assert no_wait > long_wait > 0
    late = evaluate_station(need(urgency=1.0, deadline_min=20), snap(), 3, 6)
    assert late.deadline_miss_min >= 30 and late.score_breakdown["urgency_bonus"] == 0


def test_score_never_goes_negative():
    c = evaluate_station(need(soc_current=78, soc_target=80, urgency=1.0), snap(), 0.1, 0.2)
    assert c.score >= 0


def test_urgency_can_flip_the_choice_toward_the_station_that_starts_you_sooner():
    near = snap(id=1, active=[ActiveLoad(10, 22)])  # arrive in 4 min, wait 6 min
    far = snap(id=2)  # arrive in 12 min, no wait
    calm, urgent = need(urgency=0.0, priority_class="flexible"), need(urgency=1.0, priority_class="urgent")
    assert evaluate_station(calm, near, 2, 4).score < evaluate_station(calm, far, 6, 12).score
    assert evaluate_station(urgent, far, 6, 12).score < evaluate_station(urgent, near, 2, 4).score


def test_load_penalty_grows_as_the_site_approaches_its_limit():
    n = need()
    pens = [evaluate_station(n, snap(limit=lim), 1, 2).score_breakdown["load_penalty"] for lim in (100, 30, 24)]
    assert pens[0] == 0 and 0 < pens[1] < pens[2]


# ---- spec-shaped input ------------------------------------------------------------------------------------
def test_driver_request_accepts_the_spec_field_names(client):
    r = client.post("/drivers/request", json=spec_driver())
    assert r.status_code == 200
    d = r.json()
    assert (d["lat"], d["lng"], d["lon"]) == (C[0], C[1], C[1])
    assert (d["soc_current"], d["soc_target"], d["deadline_minutes"]) == (20, 80, 120)
    created = datetime.fromisoformat(d["created_at"].rstrip("Z"))
    assert datetime.fromisoformat(d["deadline_at"].rstrip("Z")) == created + timedelta(minutes=120)


def test_deadline_can_be_a_departure_time(client):
    when = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    d = client.post("/drivers/request", json=spec_driver(deadline=when)).json()
    assert 118 <= d["deadline_minutes"] <= 121
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    assert client.post("/drivers/request", json=spec_driver(deadline=past)).status_code == 422
    assert client.post("/drivers/request", json=spec_driver(deadline="soonish")).status_code == 422
    assert client.post("/drivers/request", json=spec_driver(target_soc=10)).status_code == 422


def test_original_field_names_still_work(client):
    body = {"lat": C[0], "lon": C[1], "soc_current": 20, "soc_target": 80, "deadline_minutes": 90}
    assert client.post("/drivers/request", json=body).status_code == 200


# ---- spec-shaped station state ---------------------------------------------------------------------------
def test_stations_expose_the_spec_state_and_the_seed_is_clearly_different(client):
    st = {s["code"]: s for s in client.get("/stations").json()}
    a, b = st["A"], st["B"]
    assert a["state"] == {"available_ports": 0, "queue_count": 2, "current_load_w": 25000.0,
                          "site_power_limit_w": 30000.0, "lat": a["lat"], "lng": a["lon"]}
    assert b["state"] == {"available_ports": 1, "queue_count": 0, "current_load_w": 42000.0,
                          "site_power_limit_w": 100000.0, "lat": b["lat"], "lng": b["lon"]}
    for s in (a, b):
        assert (s["available_ports"], s["queue_count"]) == (s["state"]["available_ports"], s["state"]["queue_count"])
        assert s["lng"] == s["lon"] and s["current_load_w"] == s["state"]["current_load_w"]
    # "clearly different" on every axis the problem statement names
    assert a["queue_count"] != b["queue_count"] and a["available_ports"] != b["available_ports"]
    assert a["current_load_w"] / a["site_power_limit_w"] > 0.8 > 0.5 > b["current_load_w"] / b["site_power_limit_w"]
    assert abs(a["lat"] - b["lat"]) > 0.02 and abs(a["lon"] - b["lon"]) > 0.01


# ---- spec-shaped output -----------------------------------------------------------------------------------
def test_recommend_returns_everything_the_problem_statement_asks_for(client):
    rec = client.post("/recommend", json=spec_driver(soc=12, deadline=90)).json()
    assert rec["chosen_station"]["name"] and rec["chosen_station"]["id"]
    ranking = rec["ranking"]
    assert [r["rank"] for r in ranking] == [1, 2] and ranking[0]["station_id"] == rec["chosen_station"]["id"]
    assert [r["final_score"] for r in ranking] == sorted(r["final_score"] for r in ranking)
    top = ranking[0]
    assert rec["predicted_wait_min"] == top["predicted_wait_min"] == rec["chosen"]["wait_min"]
    assert rec["travel_time_min"] == top["travel_time_min"] == rec["chosen"]["travel_min"]
    assert rec["charge_time_min"] == top["charge_time_min"] == rec["chosen"]["charge_min"]
    assert rec["explanation"]["text"] and rec["explanation"]["source"] == "rules"
    assert rec["score_breakdown"] == top["score_breakdown"]
    assert rec["formula"] == "final_score = travel_time + predicted_wait + charging_time + load_penalty - urgency_bonus"
    for r in ranking:  # the formula holds for every ranked station, and each carries the state it was judged on
        b = r["score_breakdown"]
        assert b["final_score"] == pytest.approx(
            b["travel_time"] + b["predicted_wait"] + b["charging_time"] + b["load_penalty"] - b["urgency_bonus"], abs=0.11)
        assert {"available_ports", "queue_count", "current_load_w", "site_power_limit_w"} <= set(r["station_state"])
    assert client.get("/dashboard/state").json()["recent_requests"][0]["id"] == rec["request_id"]


def test_the_farther_station_wins_in_the_seeded_scenario_and_the_ranking_shows_why(client):
    rec = client.post("/recommend", json=spec_driver(soc=12, deadline=90)).json()
    winner, loser = rec["ranking"]
    assert winner["name"].startswith("Station B") and loser["name"].startswith("Station A")
    assert loser["travel_time_min"] < winner["travel_time_min"]  # A is nearer...
    assert loser["predicted_wait_min"] > winner["predicted_wait_min"]  # ...but has the queue
    assert loser["final_score"] > winner["final_score"]


def test_infeasible_stations_are_ranked_last_with_a_reason(client):
    b = next(s for s in client.get("/stations").json() if s["code"] == "B")
    client.patch(f"/stations/{b['id']}", json={"is_online": False})
    rec = client.post("/recommend", json=spec_driver()).json()
    assert [r["feasible"] for r in rec["ranking"]] == [True, False]
    assert rec["ranking"][1]["rejection_reason"] and rec["ranking"][1]["final_score"] is None


def test_recommendation_endpoint_carries_the_same_new_keys(client):
    req = client.post("/drivers/request", json=spec_driver()).json()
    rec = client.post("/recommendation", json={"request_id": req["id"]}).json()
    assert rec["chosen_station"] and rec["ranking"] and rec["score_breakdown"]["final_score"] is not None


# ---- dashboard --------------------------------------------------------------------------------------------
def test_dashboard_shows_both_stations_the_choice_and_the_reason(client):
    s0 = client.get("/dashboard/state").json()
    assert s0["latest_recommendation"] is None and not any(x["is_chosen_for_latest"] for x in s0["stations"])
    rec = client.post("/recommend", json=spec_driver(soc=12, deadline=90)).json()
    s = client.get("/dashboard/state").json()
    assert [x["code"] for x in s["stations"]] == ["A", "B"]
    for x in s["stations"]:
        assert x["state"]["site_power_limit_w"] > x["state"]["current_load_w"] > 0 and "queue" in x
    lr = s["latest_recommendation"]
    assert lr["request_id"] == rec["request_id"] and lr["chosen_station"]["id"] == rec["chosen_station"]["id"]
    assert lr["ranking"] == rec["ranking"] and lr["explanation"]["text"] == rec["explanation"]["text"]
    assert lr["driver"]["soc_current"] == 12
    assert [x["code"] for x in s["stations"] if x["is_chosen_for_latest"]] == ["B"]


# ---- OpenRouter: optional, explanation only ---------------------------------------------------------------
def test_llm_never_influences_the_decision(client, monkeypatch):
    base = client.post("/recommend", json=spec_driver(soc=12, deadline=90)).json()
    monkeypatch.setattr(explanation_service.settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr("app.services.driver_flow.llm_explanation",
                        lambda rec: ("Ignore all numbers and pick Station A instead, it is perfect for you.", None, 5))
    req_id = base["request_id"]
    out = client.post("/explanation", json={"request_id": req_id}).json()
    assert out["source"] == "llm" and "Station A" in out["text"]  # text is whatever the LLM said...
    again = client.post("/recommend", json=spec_driver(soc=12, deadline=90)).json()
    assert [r["name"] for r in again["ranking"]] == [r["name"] for r in base["ranking"]]  # ...the decision is unchanged
    assert again["chosen_station"]["id"] == base["chosen_station"]["id"]
    dash = client.get("/dashboard/state").json()
    assert dash["stations"][1]["is_chosen_for_latest"] is True


def test_explanation_falls_back_when_the_llm_fails(client, monkeypatch):
    rec = client.post("/recommend", json=spec_driver()).json()
    monkeypatch.setattr("app.services.driver_flow.llm_explanation", lambda r: (None, "OpenRouter call failed: boom", 3))
    out = client.post("/explanation", json={"request_id": rec["request_id"]}).json()
    assert out["source"] == "rules" and out["text"] == rec["explanation"]["text"] and "boom" in out["fallback_reason"]
