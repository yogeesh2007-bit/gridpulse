"""Operator actions on stations and demo data, shared by the authenticated and legacy APIs."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session as DbSession

from ..models import Station
from ..seed import seed_database
from .control import refresh_control_state
from .devices import ensure_placeholder_devices
from .state import advance_state, reschedule_station, station_live


class StationError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def patch_station(db: DbSession, station_id: int, changes: dict) -> dict:
    """Change the grid limit / base load or take a station offline, then re-plan its queue."""
    st = db.get(Station, station_id)
    if not st:
        raise StationError(404, "Station not found")
    if not changes:
        raise StationError(422, "Nothing to update")
    for k, v in changes.items():
        setattr(st, k, v)
    db.commit()
    advance_state(db)
    reschedule_station(db, st.id)
    refresh_control_state(db)  # log any command change caused by this operator action
    return station_live(db, st)


def reset_demo_data(
    db: DbSession, reset: bool = True, center_lat: Optional[float] = None, center_lon: Optional[float] = None
) -> dict:
    """(Re)seed the two demo stations and their starting queue. Accounts are never touched."""
    result = seed_database(db, reset=reset, center_lat=center_lat, center_lon=center_lon)
    ensure_placeholder_devices(db)
    refresh_control_state(db)  # record the baseline command for every station
    return result
