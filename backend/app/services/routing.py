"""Route distance/time estimation.

Primary source is the public OSRM demo server. If it is unreachable, slow, or ROUTING_MODE=haversine,
we fall back to straight-line distance * detour factor at an average urban speed. Callers always get a
result and can see which source produced it.
"""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Sequence

import httpx

from ..config import settings

DETOUR_FACTOR = 1.3
AVG_SPEED_KMH = 30.0
CACHE_TTL_S = 300.0
OSRM_COOLDOWN_S = 60.0

Point = tuple[float, float]  # (lat, lon)


@dataclass(frozen=True)
class RouteResult:
    distance_km: float
    duration_min: float
    source: str  # "osrm" | "haversine" | "haversine-fallback"


_cache: dict[tuple, tuple[float, RouteResult]] = {}
_osrm_down_until = 0.0
_stats = {"osrm_ok": 0, "fallbacks": 0, "last_error": None, "last_error_at": None}


def status() -> dict:
    """Routing health for the dashboard: which mode is active and whether OSRM is currently usable."""
    remaining = max(0.0, _osrm_down_until - time.monotonic())
    return {
        "mode": settings.routing_mode.lower(),
        "osrm_available": settings.routing_mode.lower() == "osrm" and remaining == 0.0,
        "cooldown_s": round(remaining),
        "osrm_ok": _stats["osrm_ok"],
        "fallbacks": _stats["fallbacks"],
        "last_error": _stats["last_error"],
    }


def reset_state() -> None:
    """Clear cache/cooldown/counters (used by tests)."""
    global _osrm_down_until
    _cache.clear()
    _osrm_down_until = 0.0
    _stats.update(osrm_ok=0, fallbacks=0, last_error=None, last_error_at=None)


def haversine_km(a: Point, b: Point) -> float:
    r = 6371.0088
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def estimate_route(origin: Point, dest: Point, source: str = "haversine") -> RouteResult:
    dist = haversine_km(origin, dest) * DETOUR_FACTOR
    return RouteResult(round(dist, 3), round(dist / AVG_SPEED_KMH * 60.0, 2), source)


def _osrm_route(origin: Point, dest: Point) -> RouteResult:
    url = (
        f"{settings.osrm_url.rstrip('/')}/route/v1/driving/"
        f"{origin[1]:.6f},{origin[0]:.6f};{dest[1]:.6f},{dest[0]:.6f}"
    )
    resp = httpx.get(
        url,
        params={"overview": "false", "alternatives": "false"},
        timeout=settings.osrm_timeout_s,
        headers={"User-Agent": "GridPulse-hackathon-prototype"},
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError(f"OSRM returned {data.get('code')}")
    route = data["routes"][0]
    return RouteResult(
        round(route["distance"] / 1000.0, 3), round(route["duration"] / 60.0, 2), "osrm"
    )


def route(origin: Point, dest: Point) -> RouteResult:
    global _osrm_down_until
    if settings.routing_mode.lower() != "osrm":
        return estimate_route(origin, dest, "haversine")

    key = (round(origin[0], 4), round(origin[1], 4), round(dest[0], 4), round(dest[1], 4))
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL_S:
        return hit[1]
    if now < _osrm_down_until:
        _stats["fallbacks"] += 1
        return estimate_route(origin, dest, "haversine-fallback")
    try:
        result = _osrm_route(origin, dest)
        _cache[key] = (now, result)
        _stats["osrm_ok"] += 1
        return result
    except Exception as exc:  # timeout, DNS, 429 rate limit, bad payload: degrade, never fail the request
        rate_limited = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429
        _osrm_down_until = now + (OSRM_COOLDOWN_S * (2 if rate_limited else 1))
        _stats["fallbacks"] += 1
        _stats["last_error"] = "OSRM rate-limited (429)" if rate_limited else f"{type(exc).__name__}: {str(exc)[:80]}"
        _stats["last_error_at"] = time.time()
        return estimate_route(origin, dest, "haversine-fallback")


def route_many(origin: Point, dests: Sequence[Point]) -> list[RouteResult]:
    """Route from one origin to several destinations in parallel."""
    if not dests:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(dests))) as pool:
        return list(pool.map(lambda d: route(origin, d), dests))
