"""Operator API (role: operator): live state, stations, reservations, control/hardware overview."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import get_db, utcnow
from ..deps import require_operator
from ..models import Reservation, Station
from ..schemas import StationPatch
from ..services import booking, realtime, stations_admin
from ..services.booking import BookingError
from ..services.control import COMMANDS, recent_events, refresh_control_state
from ..services.dashboard import build_dashboard_state
from ..services.devices import ensure_placeholder_devices, hardware_summary, list_views
from ..services.state import advance_state, iso, reservation_out
from ..services.stations_admin import StationError

router = APIRouter(prefix="/api/operator", tags=["operator"], dependencies=[Depends(require_operator)])


@router.get("/state")
def state(db: DbSession = Depends(get_db)):
    """Everything the operator dashboard renders (the WebSocket pushes this same document)."""
    return build_dashboard_state(db)


@router.patch("/stations/{station_id}")
def patch_station(station_id: int, body: StationPatch, db: DbSession = Depends(get_db)):
    """Change a station's site power limit / base load, or take it offline; its queue is re-planned."""
    try:
        out = stations_admin.patch_station(db, station_id, body.model_dump(exclude_unset=True))
    except StationError as e:
        raise HTTPException(e.status, e.message)
    realtime.poke()
    return out


@router.get("/reservations")
def reservations(status: Optional[str] = None, limit: int = 100, db: DbSession = Depends(get_db)):
    advance_state(db)
    q = select(Reservation).order_by(Reservation.created_at.desc(), Reservation.id.desc()).limit(min(limit, 500))
    if status:
        q = q.where(Reservation.status.in_(status.split(",")))
    return [reservation_out(r, db) for r in db.scalars(q)]


@router.post("/reservations/{reservation_id}/cancel")
def cancel_reservation(reservation_id: int, db: DbSession = Depends(get_db)):
    r = db.get(Reservation, reservation_id)
    if r is None:
        raise HTTPException(404, "Reservation not found")
    try:
        r = booking.cancel_reservation(db, r)
    except BookingError as e:
        raise HTTPException(e.status, e.message)
    realtime.poke()
    return reservation_out(r, db)


@router.post("/seed")
def reset_demo_data(db: DbSession = Depends(get_db)):
    """Reset stations, queue, requests and telemetry to the demo scenario. Accounts are kept."""
    out = stations_admin.reset_demo_data(db, reset=True)
    realtime.poke()
    return out


@router.get("/control")
def control(db: DbSession = Depends(get_db)):
    """Control commands, hardware/device state and the decision log. The manual-override controls are placeholders
    in the UI until the ESP32/MOSFET hardware is connected; this endpoint reports the real state."""
    now = utcnow()
    ensure_placeholder_devices(db)
    views = refresh_control_state(db, now)
    devices = list_views(db, now)
    return {
        "generated_at": iso(now),
        "commands": list(COMMANDS),
        "stations": list(views.values()),
        "devices": devices,
        "hardware_summary": hardware_summary(devices),
        "events": recent_events(db, 20),
    }
