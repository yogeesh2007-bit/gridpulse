"""Reservation use cases shared by the authenticated API and the legacy endpoints."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import utcnow
from ..models import DriverRequest, Reservation, Session, Station
from .control import refresh_control_state
from .recommendation import evaluate_single
from .state import advance_state, reschedule_station


class BookingError(Exception):
    """Client-visible booking problem; routers translate it to an HTTP error."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def create_reservation(db: DbSession, req: DriverRequest, station_id: Optional[int]) -> Reservation:
    """Book a slot. The plan is recomputed from live state at booking time (never trusted from the client)."""
    station_id = station_id or req.recommended_station_id
    if station_id is None:
        raise BookingError(422, "No station specified and no recommendation stored for this request")
    if not db.get(Station, station_id):
        raise BookingError(404, "Station not found")
    existing = db.scalar(
        select(Reservation).where(Reservation.request_id == req.id, Reservation.status.in_(("queued", "active")))
    )
    if existing:
        raise BookingError(409, f"Request already has open reservation #{existing.id}")

    now = utcnow()
    cand = evaluate_single(db, req, station_id, now)
    if cand is None or not cand.feasible:
        raise BookingError(409, f"Station not usable: {cand.rejection_reason if cand else 'unknown'}")

    start = now + timedelta(minutes=cand.start_min)
    res = Reservation(
        request_id=req.id, station_id=station_id, driver_name=req.driver_name,
        priority_class=req.priority_class, urgency=req.urgency, soc_arrival=cand.soc_arrival,
        soc_target=req.soc_target, battery_kwh=req.battery_kwh,
        arrival_at=now + timedelta(minutes=cand.travel_min), planned_start_at=start,
        planned_end_at=start + timedelta(minutes=cand.charge_min), allocated_kw=cand.charge_kw,
        status="queued",
    )
    db.add(res)
    db.commit()
    reschedule_station(db, station_id, now)  # may push lower-priority queued drivers back
    advance_state(db, now)
    refresh_control_state(db, now)  # a new (e.g. urgent) driver may change the station command
    db.refresh(res)
    return res


def cancel_reservation(db: DbSession, r: Reservation) -> Reservation:
    if r.status not in ("queued", "active"):
        raise BookingError(409, f"Cannot cancel a {r.status} reservation")
    was_active = r.status == "active"
    r.status = "cancelled"
    if was_active:
        now = utcnow()
        for s in db.scalars(select(Session).where(Session.reservation_id == r.id, Session.ended_at.is_(None))):
            s.ended_at = now
            s.energy_kwh = round(s.allocated_kw * max(0.0, (now - s.started_at).total_seconds()) / 3600.0, 2)
    db.commit()
    reschedule_station(db, r.station_id)
    advance_state(db)
    refresh_control_state(db)
    db.refresh(r)
    return r
