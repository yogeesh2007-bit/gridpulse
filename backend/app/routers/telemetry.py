from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from ..db import get_db, utcnow
from ..deps import device_auth, legacy_guard
from ..models import Station
from ..schemas import TelemetryIn
from ..services import realtime
from ..services.control import refresh_control_state
from ..services.devices import device_view, get_device
from ..services.state import iso
from ..services.telemetry import latest_all, store_packet

router = APIRouter(tags=["telemetry"])


@router.post("/telemetry/update", status_code=201, dependencies=[Depends(device_auth)])
def telemetry_update(body: TelemetryIn, db: DbSession = Depends(get_db)):
    """Accept one ESP32 packet. The response carries the device's current command so one round trip is enough."""
    now = utcnow()
    pkt = store_packet(db, body, now)
    command = None
    db.commit()
    if pkt.station_id:
        views = refresh_control_state(db, now)
        v = views.get(pkt.station_id)
        if v:
            command = {k: v[k] for k in ("command", "power_fraction", "duty_pct", "seq", "valid_for_s", "reason",
                                         "confirmation")}
    station = db.get(Station, pkt.station_id) if pkt.station_id else None
    dev = get_device(db, pkt.device_id)
    realtime.poke()  # operators see new telemetry immediately
    return {
        "accepted": True,
        "id": pkt.id,
        "device_id": pkt.device_id,
        "station_code": station.code if station else None,
        "received_at": iso(pkt.received_at),
        "registered_device": station is not None,
        "control": command,
        "device": device_view(db, dev, now) if dev else None,
    }


@router.get("/telemetry/latest", dependencies=[Depends(legacy_guard)])
def telemetry_latest(device_id: Optional[str] = None, db: DbSession = Depends(get_db)):
    """Newest packet per device (or for one device). `is_stale` flips after 10 s without a packet."""
    devices = latest_all(db, utcnow(), device_id)
    return {"count": len(devices), "devices": devices}
