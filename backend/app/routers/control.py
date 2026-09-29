from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from ..db import get_db, utcnow
from ..deps import device_auth, legacy_guard
from ..services.control import COMMANDS, recent_events, refresh_control_state
from ..services.state import iso
from .devices import deliver_command

router = APIRouter(tags=["control"])


@router.get("/control/state", dependencies=[Depends(legacy_guard)])
def control_state(db: DbSession = Depends(get_db)):
    """Current command per station (simulated until hardware confirms it) plus the recent decision log."""
    now = utcnow()
    views = refresh_control_state(db, now)
    return {
        "generated_at": iso(now),
        "commands": list(COMMANDS),
        "stations": list(views.values()),
        "events": recent_events(db, 12),
    }


@router.get("/control/command/{device_id}", dependencies=[Depends(device_auth)])
def control_command(device_id: str, db: DbSession = Depends(get_db)):
    """Milestone 2 path, kept for compatibility. Same as GET /device/{device_id}/command."""
    return deliver_command(db, device_id)
