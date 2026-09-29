"""Legacy, unauthenticated reservation endpoints (only when LEGACY_API_ENABLED=true). Use /api/* in the app."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import get_db
from ..deps import legacy_guard
from ..models import DriverRequest, Reservation
from ..schemas import ReservationCreate
from ..services import booking
from ..services.booking import BookingError
from ..services.state import advance_state, reservation_out

router = APIRouter(tags=["legacy"], dependencies=[Depends(legacy_guard)])


@router.post("/reservations", status_code=201)
def create_reservation(body: ReservationCreate, db: DbSession = Depends(get_db)):
    """Book a slot. The plan is recomputed from live state at booking time (not trusted from the client)."""
    req = db.get(DriverRequest, body.request_id)
    if not req:
        raise HTTPException(404, "Driver request not found")
    try:
        res = booking.create_reservation(db, req, body.station_id)
    except BookingError as e:
        raise HTTPException(e.status, e.message)
    return reservation_out(res, db)


@router.get("/reservations")
def list_reservations(status: Optional[str] = None, limit: int = 100, db: DbSession = Depends(get_db)):
    advance_state(db)
    q = select(Reservation).order_by(Reservation.created_at.desc(), Reservation.id.desc()).limit(min(limit, 500))
    if status:
        q = q.where(Reservation.status.in_(status.split(",")))
    return [reservation_out(r, db) for r in db.scalars(q)]


@router.get("/reservations/{reservation_id}")
def get_reservation(reservation_id: int, db: DbSession = Depends(get_db)):
    advance_state(db)
    r = db.get(Reservation, reservation_id)
    if not r:
        raise HTTPException(404, "Reservation not found")
    return reservation_out(r, db)


@router.post("/reservations/{reservation_id}/cancel")
def cancel_reservation(reservation_id: int, db: DbSession = Depends(get_db)):
    r = db.get(Reservation, reservation_id)
    if not r:
        raise HTTPException(404, "Reservation not found")
    try:
        r = booking.cancel_reservation(db, r)
    except BookingError as e:
        raise HTTPException(e.status, e.message)
    return reservation_out(r, db)
