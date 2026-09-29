"""Recommendation orchestration: load state, route, evaluate every station, rank deterministically."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session as DbSession

from ..db import utcnow
from ..models import DriverRequest
from .explanation import rule_based_explanation
from .routing import route_many
from .scheduling import FORMULA, Candidate, DriverNeed, StationSnapshot, evaluate_station
from .state import advance_state, iso, load_snapshots


def need_from_request(req: DriverRequest) -> DriverNeed:
    return DriverNeed(
        soc_current=req.soc_current,
        soc_target=req.soc_target,
        deadline_min=req.deadline_minutes,
        battery_kwh=req.battery_kwh,
        max_charge_kw=req.max_charge_kw,
        urgency=req.urgency,
        priority_class=req.priority_class,
    )


def evaluate_all(
    db: DbSession, req: DriverRequest, now: datetime
) -> tuple[list[Candidate], list[StationSnapshot]]:
    advance_state(db, now)
    snaps = load_snapshots(db, now)
    routes = route_many((req.lat, req.lon), [(s.lat, s.lon) for s in snaps])
    need = need_from_request(req)
    cands = [
        evaluate_station(need, s, r.distance_km, r.duration_min, r.source)
        for s, r in zip(snaps, routes)
    ]
    return cands, snaps


def evaluate_single(
    db: DbSession, req: DriverRequest, station_id: int, now: datetime
) -> Optional[Candidate]:
    cands, _ = evaluate_all(db, req, now)
    return next((c for c in cands if c.station_id == station_id), None)


def _cand_dict(c: Candidate, now: datetime) -> dict:
    d = asdict(c)
    d["completion_at"] = iso(now + timedelta(minutes=c.total_min)) if c.feasible else None
    if d["score"] == float("inf"):
        d["score"] = None
    d["final_score"] = d["score"]
    return d


def _ranking_entry(rank: int, c: Candidate, snap: StationSnapshot, now: datetime) -> dict:
    """One line of the station ranking: the score, its breakdown, and the station state it was judged on."""
    return {
        "rank": rank,
        "station_id": c.station_id, "code": c.code, "name": c.name, "kind": c.kind,
        "feasible": c.feasible, "rejection_reason": c.rejection_reason,
        "final_score": c.score if c.feasible else None,
        "travel_time_min": c.travel_min, "predicted_wait_min": c.wait_min, "charge_time_min": c.charge_min,
        "total_time_min": c.total_min if c.feasible else None,
        "ready_at": iso(now + timedelta(minutes=c.total_min)) if c.feasible else None,
        "charge_kw": c.charge_kw, "distance_km": c.distance_km,
        "deadline_ok": c.deadline_ok if c.feasible else None,
        "score_breakdown": c.score_breakdown if c.feasible else None,
        "station_state": {
            "available_ports": c.available_ports, "queue_count": c.queue_count,
            "current_load_w": round(snap.current_load_kw * 1000.0, 1),
            "site_power_limit_w": round(snap.site_limit_kw * 1000.0, 1),
            "lat": snap.lat, "lng": snap.lon,
        },
    }


def build_recommendation(db: DbSession, req: DriverRequest, now: Optional[datetime] = None) -> dict:
    """Rank all stations by score (lower is better), infeasible stations last.

    final_score = travel_time + predicted_wait + charging_time + load_penalty - urgency_bonus
    Stations that are unreachable safely, offline or without power are excluded (ranked last with a reason).
    The winner is the station with the lowest final score: the earliest safe completion, adjusted for how
    close each station is to its power limit and, for urgent drivers, how soon it can start them -- not
    the nearest station.
    """
    now = now or utcnow()
    cands, snaps = evaluate_all(db, req, now)
    snap_by_id = {s.id: s for s in snaps}
    ranked = sorted(
        cands,
        key=lambda c: (not c.feasible, c.score if c.feasible else 0.0, c.total_min, c.station_id),
    )
    chosen = ranked[0] if ranked and ranked[0].feasible else None
    online = [c for c in cands if c.rejection_reason != "Station is offline"]
    nearest = min(online, key=lambda c: c.travel_min) if online else None

    estimated = any(c.route_estimated for c in cands)
    fallback = any(c.route_fallback for c in cands)
    routing = {
        "fallback_used": fallback,
        "estimated": estimated,
        "sources": sorted({c.route_source for c in cands if c.route_source}),
        "confidence": "reduced" if estimated else "high",
        "note": (
            "Road routing was unavailable, so travel times are straight-line estimates (x1.3 detour at 30 km/h) "
            "and may be off."
            if fallback
            else "Travel times are straight-line estimates (x1.3 detour at 30 km/h), not road routes."
            if estimated else None
        ),
    }

    warnings: list[str] = []
    if routing["note"] and chosen is not None:
        warnings.append("Lower confidence: " + routing["note"])
    if chosen is None:
        warnings.append(
            "No station can be reached safely and used right now. Consider a closer charger or roadside help."
        )
    else:
        if not chosen.deadline_ok:
            warnings.append(
                f"Deadline cannot be met: best option finishes {chosen.deadline_miss_min:.0f} min late."
            )
        if req.soc_current <= 10:
            warnings.append("Very low battery: drive efficiently and avoid detours.")
        if chosen.power_limited:
            warnings.append(
                f"Charging power is limited to {chosen.charge_kw:.0f} kW by site power capacity."
            )

    comparison = None
    if chosen and nearest and nearest.station_id != chosen.station_id:
        comparison = {
            "nearest_station_id": nearest.station_id,
            "nearest_station_name": nearest.name,
            "nearest_travel_min": nearest.travel_min,
            "nearest_wait_min": nearest.wait_min,
            "nearest_feasible": nearest.feasible,
            "nearest_rejection_reason": nearest.rejection_reason,
            "nearest_total_min": nearest.total_min if nearest.feasible else None,
            "extra_travel_min": round(chosen.travel_min - nearest.travel_min, 1),
            "minutes_saved": round(nearest.total_min - chosen.total_min, 1) if nearest.feasible else None,
        }

    rec = {
        "request_id": req.id,
        "generated_at": iso(now),
        "driver": {
            "name": req.driver_name,
            "soc_current": req.soc_current,
            "soc_target": req.soc_target,
            "deadline_minutes": req.deadline_minutes,
            "urgency": req.urgency,
            "priority_class": req.priority_class,
        },
        "chosen": _cand_dict(chosen, now) if chosen else None,
        "chosen_station": (
            {"id": chosen.station_id, "code": chosen.code, "name": chosen.name, "kind": chosen.kind,
             "lat": snap_by_id[chosen.station_id].lat, "lng": snap_by_id[chosen.station_id].lon}
            if chosen else None
        ),
        "ranking": [_ranking_entry(i + 1, c, snap_by_id[c.station_id], now) for i, c in enumerate(ranked)],
        "predicted_wait_min": chosen.wait_min if chosen else None,
        "travel_time_min": chosen.travel_min if chosen else None,
        "charge_time_min": chosen.charge_min if chosen else None,
        "score_breakdown": chosen.score_breakdown if chosen else None,
        "formula": FORMULA,
        "candidates": [_cand_dict(c, now) for c in ranked],
        "nearest_station_id": nearest.station_id if nearest else None,
        "comparison_with_nearest": comparison,
        "warnings": warnings,
        "routing": routing,
        "method": FORMULA + " (lower is better)",
    }
    rec["explanation"] = {"text": rule_based_explanation(rec), "source": "rules", "model": None}
    rec["summary"] = (
        {
            "station_id": chosen.station_id,
            "station_name": chosen.name,
            "route_distance_km": chosen.distance_km,
            "route_travel_min": chosen.travel_min,
            "predicted_wait_min": chosen.wait_min,
            "predicted_charge_min": chosen.charge_min,
            "predicted_total_min": chosen.total_min,
            "ready_at": iso(now + timedelta(minutes=chosen.total_min)),
            "route_source": chosen.route_source,
            "fallback_routing_used": chosen.route_fallback,
            "routing_confidence": routing["confidence"],
            "reason_summary": rec["explanation"]["text"],
        }
        if chosen else None
    )
    return rec
