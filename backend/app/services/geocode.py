"""Reverse geocoding via OpenStreetMap Nominatim, with a persistent cache, throttling and a safe fallback.

Nominatim's usage policy: at most 1 request/second, an identifying User-Agent, and cache results. This module
does all three. Geocoding is cosmetic (a readable place name) - it must never break a request, so every failure
degrades to the plain coordinates.
"""
from __future__ import annotations

import threading
import time
from datetime import timedelta
from typing import Optional

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from ..config import settings
from ..db import utcnow
from ..models import GeocodeCache

MIN_INTERVAL_S = 1.0  # Nominatim policy: max 1 request per second
FAILURE_COOLDOWN_S = 60.0  # after an upstream failure, do not try again for a minute

_lock = threading.Lock()
_last_call = 0.0
_down_until = 0.0


def reset_state() -> None:
    """Forget throttling/cooldown state (used by tests)."""
    global _last_call, _down_until
    _last_call = 0.0
    _down_until = 0.0


def clear_cache(db: DbSession) -> None:
    db.execute(delete(GeocodeCache))
    db.commit()


def cache_key(lat: float, lon: float) -> str:
    return f"{round(lat, 4):.4f},{round(lon, 4):.4f}"  # ~11 m cells


def _fallback(lat: float, lon: float) -> dict:
    label = f"{lat:.4f}, {lon:.4f}"
    return {"name": label, "short_name": label, "lat": lat, "lon": lon, "source": "fallback", "cached": False}


def _short_name(data: dict) -> str:
    """'Sample Road, Chennai' from Nominatim's structured address (falls back to the first display_name part)."""
    a = data.get("address") or {}
    street = next((a[k] for k in ("road", "pedestrian", "neighbourhood", "suburb", "hamlet") if a.get(k)), None)
    town = next((a[k] for k in ("city", "town", "village", "municipality", "county", "state_district") if a.get(k)), None)
    parts = [p for p in (street, town) if p]
    if parts:
        return ", ".join(parts)
    return (data.get("display_name") or "").split(",")[0].strip()


def _query_upstream(lat: float, lon: float) -> Optional[dict]:
    global _last_call, _down_until
    with _lock:  # serialises calls so the 1 req/s policy holds across threads
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
        try:
            resp = httpx.get(
                f"{settings.nominatim_url.rstrip('/')}/reverse",
                params={"format": "jsonv2", "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "zoom": 18, "addressdetails": 1},
                headers={"User-Agent": settings.nominatim_user_agent, "Accept-Language": "en"},
                timeout=settings.geocode_timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict) or "display_name" not in data:
                raise ValueError(data.get("error", "no result") if isinstance(data, dict) else "bad payload")
            return data
        except Exception:  # timeout, DNS, 429/5xx, no result: back off and let the caller fall back
            _down_until = time.monotonic() + FAILURE_COOLDOWN_S
            return None


def reverse_geocode(db: DbSession, lat: float, lon: float) -> dict:
    key = cache_key(lat, lon)
    row = db.scalar(select(GeocodeCache).where(GeocodeCache.key == key))
    if row is not None and utcnow() - row.fetched_at < timedelta(days=settings.geocode_ttl_days):
        return {"name": row.display_name, "short_name": row.short_name, "lat": lat, "lon": lon,
                "source": "cache", "cached": True}
    if time.monotonic() < _down_until:
        return _fallback(lat, lon)

    data = _query_upstream(lat, lon)
    if data is None:
        return _fallback(lat, lon)
    name, short = data["display_name"][:400], _short_name(data)[:160] or data["display_name"][:160]
    if row is None:
        db.add(GeocodeCache(key=key, display_name=name, short_name=short, fetched_at=utcnow()))
    else:
        row.display_name, row.short_name, row.fetched_at = name, short, utcnow()
    db.commit()
    return {"name": name, "short_name": short, "lat": lat, "lon": lon, "source": "nominatim", "cached": False}
