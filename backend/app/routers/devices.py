"""Device endpoints: registration, listing, command polling and acknowledgments.

Both real ESP32 firmware and the fake/simulated device use these. What distinguishes them is only what they
declare (`device_mode` at registration, `source` in every telemetry packet) - the backend never assumes.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import get_db, utcnow
from ..deps import device_auth, legacy_guard
from ..models import Device, Station
from ..schemas import AckIn, DeviceRegisterIn
from ..services import realtime
from ..services.control import refresh_control_state
from ..services.devices import (
    DeviceError,
    ensure_placeholder_devices,
    get_device,
    device_view,
    hardware_summary,
    list_views,
    record_ack,
    record_poll,
    register_device,
)
from ..services.state import iso

router = APIRouter(tags=["devices"])


def _require_device(db: DbSession, device_id: str) -> Device:
    dev = get_device(db, device_id)
    if dev is None:
        raise HTTPException(
            404, f"Unknown device '{device_id}'. Register it with POST /device/register (or send telemetry) first."
        )
    return dev


def _require_station(db: DbSession, dev: Device) -> Station:
    st = db.get(Station, dev.station_id) if dev.station_id else None
    if st is None:
        raise HTTPException(409, f"Device '{dev.device_id}' is not bound to a station; register it with a station_code")
    return st


@router.post("/device/register", dependencies=[Depends(device_auth)])
def register(body: DeviceRegisterIn, db: DbSession = Depends(get_db)):
    """A device announces itself: real or simulated, dry-run or not, firmware version, optional station binding."""
    now = utcnow()
    try:
        dev = register_device(db, body, now)
    except DeviceError as e:
        raise HTTPException(e.status, e.message)
    refresh_control_state(db, now)
    realtime.poke()
    return device_view(db, dev, now)


@router.get("/devices", dependencies=[Depends(legacy_guard)])
def devices(db: DbSession = Depends(get_db)):
    """All known devices with their honest state, plus stations that have no device (software-only)."""
    now = utcnow()
    ensure_placeholder_devices(db)
    refresh_control_state(db, now)
    views = list_views(db, now)
    without = [s.code for s in db.scalars(select(Station).where(Station.device_id.is_(None)).order_by(Station.id))]
    return {"count": len(views), "devices": views, "stations_without_device": without,
            "summary": hardware_summary(views)}


@router.get("/device/{device_id}", dependencies=[Depends(legacy_guard)])
def get_one_device(device_id: str, db: DbSession = Depends(get_db)):
    now = utcnow()
    dev = _require_device(db, device_id)
    refresh_control_state(db, now)
    return device_view(db, dev, now)


def deliver_command(db: DbSession, device_id: str) -> dict:
    """Return the device's current command and record that it was delivered (used by two URLs)."""
    now = utcnow()
    dev = _require_device(db, device_id)
    st = _require_station(db, dev)
    v = refresh_control_state(db, now)[st.id]
    record_poll(db, dev, v["seq"], v["command"], now)
    return {
        "device_id": dev.device_id,
        "station_code": st.code,
        "device_mode": dev.device_mode,
        "dry_run": dev.dry_run,
        "command": v["command"],
        "power_fraction": v["power_fraction"],
        "duty_pct": v["duty_pct"],
        "seq": v["seq"],
        "valid_for_s": v["valid_for_s"],
        "reason": v["reason"],
        "confirmation": v["confirmation"],
        "generated_at": v["command_generated_at"],
        "updated_at": v["updated_at"],
        "server_time": iso(now),
    }


@router.get("/device/{device_id}/command", dependencies=[Depends(device_auth)])
def device_command(device_id: str, db: DbSession = Depends(get_db)):
    """Polled by the ESP32 every ~1 s. The device must fail safe (output OFF) if this stops arriving for longer
    than `valid_for_s`."""
    return deliver_command(db, device_id)


@router.post("/device/{device_id}/ack", dependencies=[Depends(device_auth)])
def device_ack(device_id: str, body: AckIn, db: DbSession = Depends(get_db)):
    """The device reports what it did with a command (applied / rejected / failsafe / local_override)."""
    now = utcnow()
    dev = _require_device(db, device_id)
    st = _require_station(db, dev)
    current = refresh_control_state(db, now)[st.id]
    stale = record_ack(db, dev, body, current["seq"], now)
    view = device_view(db, dev, now)
    realtime.poke()
    return {
        "accepted": True,
        "device_id": dev.device_id,
        "seq": body.seq,
        "current_seq": current["seq"],
        "stale_ack": stale,  # True => ack was for an older command and did not change device state
        "ack_status": view["ack_status"],
        "hardware_confirmed": view["hardware_confirmed"],
    }
