"""Reverse geocoding: Nominatim with a persistent cache, throttling, and graceful fallback."""
import httpx
import pytest

from app.config import settings
from app.db import SessionLocal, init_db
from app.services import geocode

NOMINATIM_REPLY = {
    "display_name": "Sample Road, Thandalam, Chennai, Tamil Nadu, 602105, India",
    "address": {"road": "Sample Road", "suburb": "Thandalam", "city": "Chennai", "state": "Tamil Nadu"},
}


@pytest.fixture(autouse=True)
def fresh_geocoder(monkeypatch):
    init_db()
    with SessionLocal() as db:
        geocode.clear_cache(db)
    geocode.reset_state()
    monkeypatch.setattr(geocode, "MIN_INTERVAL_S", 0.0)  # do not sleep in tests
    yield
    geocode.reset_state()


def fake_get(calls):
    def _get(url, **kw):
        calls.append((url, kw))
        return httpx.Response(200, json=NOMINATIM_REPLY, request=httpx.Request("GET", url))
    return _get


def rev(client, headers, lat=13.0067, lon=80.0037):
    return client.get("/api/geo/reverse", params={"lat": lat, "lon": lon}, headers=headers)


def test_reverse_geocode_returns_a_readable_place_and_identifies_itself(client, driver, monkeypatch):
    calls = []
    monkeypatch.setattr(geocode.httpx, "get", fake_get(calls))
    r = rev(client, driver[0])
    assert r.status_code == 200
    body = r.json()
    assert body["short_name"] == "Sample Road, Chennai" and body["name"].startswith("Sample Road, Thandalam")
    assert body["source"] == "nominatim" and body["cached"] is False
    url, kw = calls[0]
    assert url.endswith("/reverse") and kw["params"]["format"] == "jsonv2"
    assert kw["headers"]["User-Agent"] == settings.nominatim_user_agent  # Nominatim's usage policy requires this


def test_results_are_cached_across_requests_and_nearby_points(client, driver, monkeypatch):
    calls = []
    monkeypatch.setattr(geocode.httpx, "get", fake_get(calls))
    rev(client, driver[0])
    second = rev(client, driver[0]).json()
    nearby = rev(client, driver[0], lat=13.006701, lon=80.003701).json()  # ~0.1 m away: same cache cell
    assert second["cached"] is True and second["source"] == "cache" and nearby["cached"] is True
    assert len(calls) == 1
    far = rev(client, driver[0], lat=13.5, lon=80.5).json()
    assert far["cached"] is False and len(calls) == 2


def test_upstream_failure_falls_back_to_coordinates_and_backs_off(client, driver, monkeypatch):
    calls = []

    def boom(url, **kw):
        calls.append(url)
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(geocode.httpx, "get", boom)
    r = rev(client, driver[0])
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "fallback" and body["name"] == "13.0067, 80.0037" and body["cached"] is False
    rev(client, driver[0], lat=13.1, lon=80.1)
    assert len(calls) == 1  # cooldown: the failing upstream is not hammered
    assert client.get("/api/geo/reverse", params={"lat": 13.0, "lon": 80.0}, headers=driver[0]).status_code == 200


def test_bad_upstream_payload_and_rate_limit_also_fall_back(client, driver, monkeypatch):
    monkeypatch.setattr(geocode.httpx, "get", lambda url, **kw: httpx.Response(429, request=httpx.Request("GET", url)))
    assert rev(client, driver[0]).json()["source"] == "fallback"
    geocode.reset_state()
    monkeypatch.setattr(geocode.httpx, "get", lambda url, **kw: httpx.Response(200, json={"error": "Unable to geocode"}, request=httpx.Request("GET", url)))
    assert rev(client, driver[0]).json()["source"] == "fallback"


def test_coordinates_are_validated(client, driver):
    for lat, lon in ((91, 0), (-91, 0), (0, 181), (0, -181)):
        assert rev(client, driver[0], lat, lon).status_code == 422
    assert client.get("/api/geo/reverse", headers=driver[0]).status_code == 422
