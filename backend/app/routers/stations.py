"""Legacy, unauthenticated station endpoints (only when LEGACY_API_ENABLED=true). Use /api/operator in the app."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import get_db
from ..deps import legacy_guard
from ..models import Station
from ..schemas import StationPatch
from ..services import stations_admin
from ..services.state import advance_state, station_live
from ..services.stations_admin import StationError

router = APIRouter(tags=["legacy"], dependencies=[Depends(legacy_guard)])


@router.post("/seed")
def seed(
    reset: bool = True,
    center_lat: Optional[float] = None,
    center_lon: Optional[float] = None,
    db: DbSession = Depends(get_db),
):
    """(Re)seed the two demo stations and starting queue. reset=false only seeds an empty database."""
    return stations_admin.reset_demo_data(db, reset=reset, center_lat=center_lat, center_lon=center_lon)


@router.get("/stations")
def list_stations(db: DbSession = Depends(get_db)):
    advance_state(db)
    return [station_live(db, s) for s in db.scalars(select(Station).order_by(Station.id))]


@router.get("/stations/{station_id}")
def get_station(station_id: int, db: DbSession = Depends(get_db)):
    advance_state(db)
    st = db.get(Station, station_id)
    if not st:
        raise HTTPException(404, "Station not found")
    return station_live(db, st)


@router.patch("/stations/{station_id}")
def patch_station(station_id: int, body: StationPatch, db: DbSession = Depends(get_db)):
    """Operator lever: change the grid limit / base load or take a station offline, then re-plan its queue."""
    try:
        return stations_admin.patch_station(db, station_id, body.model_dump(exclude_unset=True))
    except StationError as e:
        raise HTTPException(e.status, e.message)
