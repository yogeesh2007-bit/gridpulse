"""Driver API (role: driver). A driver only ever sees and touches their own requests and reservations."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import get_db
from ..deps import require_driver
from ..models import DriverRequest, Reservation, User
from ..schemas import DriverRequestIn, DriverRequestOut, LocationUpdateIn, ReservationCreate
from ..services import booking, driver_flow as flow, realtime
from ..services.booking import BookingError
from ..services.state import advance_state, reservation_out

router = APIRouter(prefix="/api/driver", tags=["driver"], dependencies=[Depends(require_driver)])


def own_request(db: DbSession, user: User, request_id: int) -> DriverRequest:
    """404 (not 403) for other people's requests, so ids cannot be probed."""
    req = db.get(DriverRequest, request_id)
    if req is None or req.user_id != user.id:
        raise HTTPException(404, "Driver request not found")
    return req


def own_reservation(db: DbSession, user: User, reservation_id: int) -> Reservation:
    r = db.get(Reservation, reservation_id)
    req = db.get(DriverRequest, r.request_id) if r is not None and r.request_id else None
    if r is None or req is None or req.user_id != user.id:
        raise HTTPException(404, "Reservation not found")
    return r


@router.post("/recommend")
def recommend(body: DriverRequestIn, user: User = Depends(require_driver), db: DbSession = Depends(get_db)):
    """Store the charging need and return the ranked recommendation (deterministic engine)."""
    body = body.model_copy(update={"driver_name": user.name})  # operators see who is who; never trust a client-sent name
    rec = flow.run_recommendation(db, flow.create_driver_request(db, body, user_id=user.id))
    realtime.poke()  # the operator dashboard shows the latest recommendation
    return rec


@router.get("/requests/latest")
def latest_request(user: User = Depends(require_driver), db: DbSession = Depends(get_db)):
    """Restore the driver's most recent request, its recommendation and any open reservation (page reloads)."""
    req = db.scalar(select(DriverRequest).where(DriverRequest.user_id == user.id).order_by(DriverRequest.id.desc()).limit(1))
    if req is None:
        return {"request": None, "recommendation": None, "reservation": None}
    import json

    advance_state(db)
    open_res = db.scalar(
        select(Reservation).where(Reservation.request_id == req.id, Reservation.status.in_(("queued", "active")))
        .order_by(Reservation.id.desc()).limit(1)
    )
    return {
        "request": DriverRequestOut.model_validate(req).model_dump(mode="json"),
        "recommendation": json.loads(req.recommendation_json) if req.recommendation_json else None,
        "reservation": reservation_out(open_res, db) if open_res else None,
    }


@router.post("/requests/{request_id}/refresh")
def refresh_recommendation(request_id: int, user: User = Depends(require_driver), db: DbSession = Depends(get_db)):
    """Re-rank the stations for an existing request using the latest position and live station state."""
    rec = flow.run_recommendation(db, own_request(db, user, request_id))
    realtime.poke()
    return rec


@router.post("/location")
def update_location(body: LocationUpdateIn, user: User = Depends(require_driver), db: DbSession = Depends(get_db)):
    """Live position from watchPosition(); returns route ETAs to every station."""
    req = own_request(db, user, body.request_id)
    out = flow.update_live_location(db, req, body.lat, body.lon, body.accuracy_m, body.source)
    realtime.poke()
    return out


@router.post("/reservations", status_code=201)
def create_reservation(body: ReservationCreate, user: User = Depends(require_driver), db: DbSession = Depends(get_db)):
    req = own_request(db, user, body.request_id)
    try:
        res = booking.create_reservation(db, req, body.station_id)
    except BookingError as e:
        raise HTTPException(e.status, e.message)
    realtime.poke()
    return reservation_out(res, db)


@router.get("/reservations")
def my_reservations(user: User = Depends(require_driver), db: DbSession = Depends(get_db)):
    advance_state(db)
    return realtime.driver_reservations(db, user.id)


@router.post("/reservations/{reservation_id}/cancel")
def cancel_reservation(reservation_id: int, user: User = Depends(require_driver), db: DbSession = Depends(get_db)):
    r = own_reservation(db, user, reservation_id)
    try:
        r = booking.cancel_reservation(db, r)
    except BookingError as e:
        raise HTTPException(e.status, e.message)
    realtime.poke()
    return reservation_out(r, db)


@router.get("/stations")
def stations(db: DbSession = Depends(get_db)):
    """Live availability and load of every station (no other drivers, no hardware internals)."""
    advance_state(db)
    return realtime.public_stations(db)
