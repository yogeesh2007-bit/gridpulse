"""Operator dashboard state builder."""
import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..config import settings
from ..db import utcnow
from ..models import DriverRequest, ExplanationLog, LiveLocation, Reservation, Station
from . import bulbs, routing
from .control import recent_events, refresh_control_state
from .devices import ensure_placeholder_devices, hardware_summary, list_views
from .telemetry import latest_all
from .state import advance_state, iso, reservation_out, station_live

TIMELINE_HORIZON_MIN = 120.0
LIVE_WINDOW_MIN = 15  # show drivers whose location was updated within this window
LIVE_FRESH_S = 20  # ...and flag them "live" if the last update is this recent


def _timeline(reservations: list[dict], now) -> list[dict]:
    """Per-station upcoming schedule in minutes-from-now, clipped to the horizon (for the timeline bars)."""
    from datetime import datetime

    def minutes(iso_str: str) -> float:
        return (datetime.fromisoformat(iso_str.rstrip("Z")) - now).total_seconds() / 60.0

    out = []
    for r in reservations:
        start, end = max(0.0, minutes(r["planned_start_at"])), minutes(r["planned_end_at"])
        if end <= 0 or start >= TIMELINE_HORIZON_MIN:
            continue
        out.append({
            "reservation_id": r["id"], "station_id": r["station_id"], "driver_name": r["driver_name"],
            "priority_class": r["priority_class"], "status": r["status"], "allocated_kw": r["allocated_kw"],
            "start_min": round(start, 1), "end_min": round(min(end, TIMELINE_HORIZON_MIN), 1),
            "truncated": end > TIMELINE_HORIZON_MIN,
        })
    return out


def _live_drivers(db, now) -> list[dict]:
    cutoff = now - timedelta(minutes=LIVE_WINDOW_MIN)
    rows = db.scalars(
        select(LiveLocation).where(LiveLocation.updated_at >= cutoff).order_by(LiveLocation.updated_at.desc()).limit(10)
    ).all()
    out = []
    for loc in rows:
        req = db.get(DriverRequest, loc.request_id)
        age = max(0.0, (now - loc.updated_at).total_seconds())
        etas = json.loads(loc.etas_json)["items"] if loc.etas_json else []
        out.append({
            "request_id": loc.request_id, "driver_name": req.driver_name if req else "?",
            "priority_class": req.priority_class if req else None,
            "lat": loc.lat, "lon": loc.lon, "accuracy_m": loc.accuracy_m, "source": loc.source,
            "updates": loc.updates, "updated_at": iso(loc.updated_at), "age_s": round(age, 1),
            "is_live": age <= LIVE_FRESH_S, "etas": etas,
        })
    return out


def _latest_recommendation(db) -> dict | None:
    """The newest recommendation: chosen station, full ranking with score breakdown, and the reason."""
    req = db.scalar(
        select(DriverRequest).where(DriverRequest.recommendation_json.is_not(None))
        .order_by(DriverRequest.id.desc()).limit(1)
    )
    if req is None:
        return None
    rec = json.loads(req.recommendation_json)
    explanation = rec["explanation"]  # deterministic text...
    llm = db.scalar(  # ...unless an optional OpenRouter rewrite of it exists
        select(ExplanationLog).where(ExplanationLog.request_id == req.id, ExplanationLog.source == "llm")
        .order_by(ExplanationLog.id.desc()).limit(1)
    )
    if llm:
        explanation = {"text": llm.text, "source": "llm", "model": llm.model}
    return {
        "request_id": req.id, "created_at": iso(req.created_at), "generated_at": rec["generated_at"],
        "driver": rec["driver"], "chosen_station": rec["chosen_station"], "ranking": rec["ranking"],
        "explanation": explanation, "warnings": rec["warnings"], "routing": rec["routing"],
        "formula": rec["formula"],
    }


def _latest_route_etas(db) -> dict | None:
    """Route ETAs to every station for the newest request (from its recommendation, plus live ETAs if any)."""
    req = db.scalar(select(DriverRequest).order_by(DriverRequest.id.desc()).limit(1))
    if req is None:
        return None
    items, generated = [], None
    if req.recommendation_json:
        rec = json.loads(req.recommendation_json)
        generated = rec["generated_at"]
        items = [
            {k: c[k] for k in ("station_id", "code", "name", "distance_km", "travel_min", "wait_min", "charge_min",
                                "total_min", "feasible", "rejection_reason", "route_source", "route_fallback")}
            for c in rec["candidates"]
        ]
    loc = db.scalar(select(LiveLocation).where(LiveLocation.request_id == req.id))
    live = json.loads(loc.etas_json) if loc and loc.etas_json else None
    return {
        "request_id": req.id, "driver_name": req.driver_name, "recommendation_at": generated, "items": items,
        "live_etas": live["items"] if live else [], "live_computed_at": live["computed_at"] if live else None,
    }


def build_dashboard_state(db: DbSession) -> dict:
    """Everything the operator dashboard renders, in one call (shared by the REST and WebSocket APIs)."""
    now = utcnow()
    advance_state(db, now)
    stations = [station_live(db, s, now) for s in db.scalars(select(Station).order_by(Station.id))]
    ensure_placeholder_devices(db)
    controls = refresh_control_state(db, now)
    telemetry = latest_all(db, now)
    by_device = {t["device_id"]: t for t in telemetry}
    device_views = list_views(db, now)
    dev_by_id = {d["device_id"]: d for d in device_views}
    latest_rec = _latest_recommendation(db)
    chosen_id = latest_rec["chosen_station"]["id"] if latest_rec and latest_rec["chosen_station"] else None
    for s in stations:
        s["is_chosen_for_latest"] = s["id"] == chosen_id
        s["control"] = controls.get(s["id"])
        s["telemetry"] = by_device.get(s["device_id"]) if s["device_id"] else None
        s["device"] = dev_by_id.get(s["device_id"]) if s["device_id"] else None

    reservations = [
        reservation_out(r, db, now)
        for r in db.scalars(
            select(Reservation)
            .where(Reservation.status.in_(("active", "queued")))
            .order_by(Reservation.station_id, Reservation.planned_start_at)
        )
    ]
    recent_done = [
        reservation_out(r, db, now)
        for r in db.scalars(
            select(Reservation).where(Reservation.status.in_(("done", "cancelled")))
            .order_by(Reservation.planned_end_at.desc()).limit(5)
        )
    ]

    requests = []
    for req in db.scalars(select(DriverRequest).order_by(DriverRequest.id.desc()).limit(8)):
        rec = json.loads(req.recommendation_json) if req.recommendation_json else None
        chosen = rec["chosen"] if rec else None
        requests.append(
            {
                "id": req.id,
                "created_at": iso(req.created_at),
                "driver_name": req.driver_name,
                "lat": req.lat,
                "lon": req.lon,
                "location_source": req.location_source,
                "soc_current": req.soc_current,
                "soc_target": req.soc_target,
                "deadline_minutes": req.deadline_minutes,
                "urgency": req.urgency,
                "priority_class": req.priority_class,
                "recommended_station": chosen["name"] if chosen else None,
                "wait_min": chosen["wait_min"] if chosen else None,
                "total_min": chosen["total_min"] if chosen else None,
                "charge_kw": chosen["charge_kw"] if chosen else None,
                "was_nearest": bool(chosen and rec["nearest_station_id"] == chosen["station_id"]),
                "explanation": rec["explanation"]["text"] if rec else None,
                "reserved": db.scalar(
                    select(Reservation.id).where(Reservation.request_id == req.id)
                    .order_by(Reservation.id.desc()).limit(1)
                ),
            }
        )

    last_expl = db.scalar(select(ExplanationLog).order_by(ExplanationLog.id.desc()).limit(1))
    return {
        "now": iso(now),
        "totals": {
            "stations": len(stations),
            "stations_online": sum(1 for s in stations if s["is_online"]),
            "active_sessions": sum(s["ports_busy"] for s in stations),
            "queued": sum(s["queue_length"] for s in stations),
            "ev_load_kw": round(sum(s["ev_load_kw"] for s in stations), 1),
        },
        "stations": stations,
        "reservations": reservations,
        "recent_finished": recent_done,
        "latest_recommendation": latest_rec,
        "recent_requests": requests,
        "telemetry": telemetry,
        "bulbs": bulbs.list_views(db, now),
        "devices": device_views,
        "hardware_summary": hardware_summary(device_views),
        "control_events": recent_events(db, 10),
        "live_drivers": _live_drivers(db, now),
        "latest_route_etas": _latest_route_etas(db),
        "timeline": {"horizon_min": TIMELINE_HORIZON_MIN, "items": _timeline(reservations, now)},
        "system": {
            "routing": routing.status(),
            "routing_mode": settings.routing_mode,
            "openrouter_configured": bool(settings.openrouter_api_key),
            "openrouter_model": settings.openrouter_model,
            "last_explanation_source": last_expl.source if last_expl else None,
            "center": {"lat": settings.center_lat, "lon": settings.center_lon},
        },
    }
