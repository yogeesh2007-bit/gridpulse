"""Driver-side use cases shared by the authenticated API and the legacy endpoints:
create a request, rank stations, explain the decision, track live location."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..config import settings
from ..db import utcnow
from ..models import DriverRequest, ExplanationLog, LiveLocation, Station
from ..schemas import DriverRequestIn, ExplanationOut
from .explanation import llm_explanation, rule_based_explanation
from .recommendation import build_recommendation
from .routing import route_many
from .scheduling import compute_urgency
from .state import iso

ETA_REUSE_S = 8.0  # do not hammer the routing service: reuse ETAs computed in the last few seconds


def create_driver_request(db: DbSession, body: DriverRequestIn, user_id: Optional[int] = None) -> DriverRequest:
    """Store a driver's charging need. Urgency and priority class are computed deterministically."""
    urgency, cls = compute_urgency(
        body.soc_current, body.soc_target, body.deadline_minutes, body.battery_kwh, body.max_charge_kw
    )
    now = utcnow()
    req = DriverRequest(
        **body.model_dump(), urgency=urgency, priority_class=cls, user_id=user_id,
        created_at=now, deadline_at=now + timedelta(minutes=body.deadline_minutes),
    )
    db.add(req)
    db.commit()
    return req


def run_recommendation(db: DbSession, req: DriverRequest) -> dict:
    """Rank all stations for a stored request. Deterministic; the explanation here is rule-based."""
    rec = build_recommendation(db, req)
    req.recommendation_json = json.dumps(rec)
    req.recommended_station_id = rec["chosen"]["station_id"] if rec["chosen"] else None
    db.commit()
    return rec


def explain_request(db: DbSession, req: DriverRequest) -> ExplanationOut:
    """Optionally rephrase the rule-based explanation with OpenRouter. Always returns usable text.

    Raises LookupError if the request has no stored recommendation. The decision itself is never touched.
    """
    if not req.recommendation_json:
        raise LookupError("No recommendation stored for this request")
    rec = json.loads(req.recommendation_json)
    text, reason, latency = llm_explanation(rec)
    if text:
        out = ExplanationOut(request_id=req.id, text=text, source="llm",
                             model=settings.openrouter_model, latency_ms=latency)
    else:
        out = ExplanationOut(request_id=req.id, text=rule_based_explanation(rec), source="rules",
                             fallback_reason=reason, latency_ms=latency)
    db.add(ExplanationLog(request_id=req.id, source=out.source, model=out.model, text=out.text,
                          fallback_reason=out.fallback_reason, latency_ms=latency))
    db.commit()
    return out


def update_live_location(
    db: DbSession, req: DriverRequest, lat: float, lon: float, accuracy_m: Optional[float], source: str
) -> dict:
    """Store a live position and return fresh route ETAs to every station.

    The request's own lat/lon are also updated, so the next recommendation uses the newest position.
    """
    now = utcnow()
    live = db.scalar(select(LiveLocation).where(LiveLocation.request_id == req.id))
    if live is None:
        live = LiveLocation(request_id=req.id, lat=lat, lon=lon, updates=0)
        db.add(live)
    live.lat, live.lon, live.accuracy_m, live.source = lat, lon, accuracy_m, source
    live.updates = (live.updates or 0) + 1
    live.updated_at = now
    req.lat, req.lon, req.location_source = lat, lon, source

    cached = json.loads(live.etas_json) if live.etas_json else None
    reuse = bool(cached) and (
        now - datetime.fromisoformat(cached["computed_at"].rstrip("Z"))
    ).total_seconds() < ETA_REUSE_S
    if reuse:
        etas = cached["items"]
    else:
        stations = list(db.scalars(select(Station).order_by(Station.id)))
        routes = route_many((lat, lon), [(s.lat, s.lon) for s in stations])
        etas = [
            {
                "station_id": s.id, "station_code": s.code, "station_name": s.name, "is_online": s.is_online,
                "distance_km": r.distance_km, "travel_min": r.duration_min, "route_source": r.source,
                "route_fallback": "fallback" in r.source,
            }
            for s, r in zip(stations, routes)
        ]
        live.etas_json = json.dumps({"computed_at": iso(now), "items": etas})
    db.commit()
    return {
        "request_id": req.id,
        "lat": live.lat, "lon": live.lon, "accuracy_m": live.accuracy_m, "source": live.source,
        "updates": live.updates, "updated_at": iso(now),
        "etas": etas, "etas_reused": reuse,
        "routing_fallback_used": any(e["route_fallback"] for e in etas),
    }
