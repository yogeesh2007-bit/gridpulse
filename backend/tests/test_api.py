from app.config import settings

CENTER = (settings.center_lat, settings.center_lon)


def driver_body(**over):
    body = {
        "driver_name": "Test Driver",
        "lat": CENTER[0], "lon": CENTER[1],
        "soc_current": 20, "soc_target": 80, "deadline_minutes": 120,
        "battery_kwh": 40, "max_charge_kw": 50, "location_source": "manual",
    }
    body.update(over)
    return body


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_seed_and_stations(client):
    r = client.post("/seed", params={"reset": True})
    assert r.json()["seeded"] is True
    stations = client.get("/stations").json()
    assert [s["code"] for s in stations] == ["A", "B"]
    a = stations[0]
    assert a["queue_length"] == 2 and a["ports_busy"] == 1
    assert client.get(f"/stations/{a['id']}").json()["code"] == "A"
    assert client.get("/stations/999").status_code == 404


def test_request_validation(client):
    assert client.post("/drivers/request", json=driver_body(soc_target=10)).status_code == 422
    assert client.post("/drivers/request", json=driver_body(lat=200)).status_code == 422
    assert client.post("/drivers/request", json=driver_body(deadline_minutes=0)).status_code == 422


def test_full_flow_recommend_reserve_dashboard(client):
    req = client.post("/drivers/request", json=driver_body()).json()
    assert req["id"] and req["priority_class"] in {"urgent", "normal", "flexible"}

    rec = client.post("/recommendation", json={"request_id": req["id"]}).json()
    assert rec["chosen"] is not None
    assert len(rec["candidates"]) == 2
    chosen = rec["chosen"]
    assert chosen["total_min"] == round(chosen["travel_min"] + chosen["wait_min"] + chosen["charge_min"], 1) \
        or abs(chosen["total_min"] - (chosen["travel_min"] + chosen["wait_min"] + chosen["charge_min"])) < 0.3
    assert rec["explanation"]["source"] == "rules" and rec["explanation"]["text"]

    # Seeded state: A is nearer but has a queue, so B (farther) must win for this driver.
    assert rec["nearest_station_id"] != chosen["station_id"]
    assert rec["comparison_with_nearest"]["minutes_saved"] > 0

    res = client.post("/reservations", json={"request_id": req["id"]})
    assert res.status_code == 201
    body = res.json()
    assert body["station_id"] == chosen["station_id"] and body["status"] in {"queued", "active"}
    assert body["allocated_kw"] == chosen["charge_kw"]

    assert client.post("/reservations", json={"request_id": req["id"]}).status_code == 409

    listed = client.get("/reservations", params={"status": "queued,active"}).json()
    assert any(r["id"] == body["id"] for r in listed)

    state = client.get("/dashboard/state").json()
    assert state["totals"]["stations"] == 2
    assert any(r["id"] == body["id"] for r in state["reservations"])
    assert state["recent_requests"][0]["id"] == req["id"]
    assert state["recent_requests"][0]["recommended_station"] == chosen["name"]


def test_explanation_falls_back_without_api_key(client):
    req = client.post("/drivers/request", json=driver_body()).json()
    client.post("/recommendation", json={"request_id": req["id"]})
    out = client.post("/explanation", json={"request_id": req["id"]}).json()
    assert out["source"] == "rules" and out["text"]
    assert "OPENROUTER_API_KEY" in out["fallback_reason"]


def test_explanation_requires_recommendation(client):
    req = client.post("/drivers/request", json=driver_body()).json()
    assert client.post("/explanation", json={"request_id": req["id"]}).status_code == 404


def test_offline_station_is_never_recommended(client):
    stations = client.get("/stations").json()
    b = next(s for s in stations if s["code"] == "B")
    assert client.patch(f"/stations/{b['id']}", json={"is_online": False}).json()["is_online"] is False
    req = client.post("/drivers/request", json=driver_body()).json()
    rec = client.post("/recommendation", json={"request_id": req["id"]}).json()
    assert rec["chosen"]["code"] == "A"
    offline = next(c for c in rec["candidates"] if c["code"] == "B")
    assert offline["feasible"] is False


def test_low_soc_far_away_is_rejected_as_stranded_risk(client):
    # ~150 km away with 6% battery: neither station is reachable above the reserve.
    req = client.post("/drivers/request", json=driver_body(lat=CENTER[0] + 1.2, soc_current=6)).json()
    rec = client.post("/recommendation", json={"request_id": req["id"]}).json()
    assert rec["chosen"] is None and rec["warnings"]
    assert all(not c["feasible"] for c in rec["candidates"])
    assert client.post("/reservations", json={"request_id": req["id"], "station_id": 1}).status_code == 409


def test_urgent_reservation_jumps_queue_and_reschedules(client):
    a = next(s for s in client.get("/stations").json() if s["code"] == "A")
    before = {q["driver_name"]: q["planned_start_at"] for q in a["queue"]}
    req = client.post(
        "/drivers/request", json=driver_body(soc_current=6, deadline_minutes=60, lat=CENTER[0] + 0.009,
                                             lon=CENTER[1] + 0.01),
    ).json()
    assert req["priority_class"] == "urgent"
    res = client.post("/reservations", json={"request_id": req["id"], "station_id": a["id"]})
    assert res.status_code == 201
    after = client.get(f"/stations/{a['id']}").json()
    starts = {q["driver_name"]: q["planned_start_at"] for q in after["queue"]}
    # the flexible queued driver was pushed back by the urgent one
    assert starts["Karthik R."] > before["Karthik R."]
    assert after["queue"][0]["driver_name"] == "Test Driver"


def test_cancel_reservation(client):
    req = client.post("/drivers/request", json=driver_body()).json()
    client.post("/recommendation", json={"request_id": req["id"]})
    res = client.post("/reservations", json={"request_id": req["id"]}).json()
    out = client.post(f"/reservations/{res['id']}/cancel").json()
    assert out["status"] == "cancelled"
    assert client.post(f"/reservations/{res['id']}/cancel").status_code == 409
