"""Telemetry storage and lookup for ESP32 (or simulated) devices."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from ..db import utcnow
from ..models import Station, Telemetry
from ..schemas import TelemetryIn
from .devices import LIVE_S as STALE_AFTER_S  # no packet for this long => no longer 'live'
from .devices import note_packet
from .state import iso

HISTORY_PER_DEVICE = 500


def _naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def store_packet(db: DbSession, body: TelemetryIn, now: Optional[datetime] = None) -> Telemetry:
    now = now or utcnow()
    station = db.scalar(select(Station).where(Station.device_id == body.device_id))
    pkt = Telemetry(
        device_id=body.device_id,
        station_id=station.id if station else None,
        voltage=body.voltage, current=body.current, power=body.power,
        temperature=body.temperature,
        device_ts=_naive_utc(body.timestamp),
        mode=body.mode.strip().upper() if body.mode else None,
        note=body.note,
        received_at=now,
        source=body.source, dry_run=body.dry_run, sensor_status=body.sensor_status,
        event=body.event, local_override=body.local_override,
    )
    db.add(pkt)
    db.flush()
    note_packet(db, body, station.id if station else None, now)
    # keep the table small: drop everything but the newest packets for this device
    cutoff = db.scalar(
        select(Telemetry.id).where(Telemetry.device_id == body.device_id)
        .order_by(Telemetry.id.desc()).offset(HISTORY_PER_DEVICE).limit(1)
    )
    if cutoff:
        db.execute(delete(Telemetry).where(Telemetry.device_id == body.device_id, Telemetry.id <= cutoff))
    db.commit()
    return pkt


def latest_packet(db: DbSession, device_id: str) -> Optional[Telemetry]:
    return db.scalar(
        select(Telemetry).where(Telemetry.device_id == device_id).order_by(Telemetry.id.desc()).limit(1)
    )


def serialize(pkt: Telemetry, station: Optional[Station], now: Optional[datetime] = None) -> dict:
    now = now or utcnow()
    age = max(0.0, (now - pkt.received_at).total_seconds())
    return {
        "device_id": pkt.device_id,
        "station_id": pkt.station_id,
        "station_code": station.code if station else None,
        "voltage": pkt.voltage,
        "current": pkt.current,
        "power": pkt.power,
        "temperature": pkt.temperature,
        "timestamp": iso(pkt.device_ts),
        "mode": pkt.mode,
        "note": pkt.note,
        "source": pkt.source,
        "dry_run": pkt.dry_run,
        "sensor_status": pkt.sensor_status,
        "event": pkt.event,
        "local_override": pkt.local_override,
        "received_at": iso(pkt.received_at),
        "age_s": round(age, 1),
        "is_stale": age > STALE_AFTER_S,
    }


def latest_all(db: DbSession, now: Optional[datetime] = None, device_id: Optional[str] = None) -> list[dict]:
    """Newest packet for every device (or just one device)."""
    now = now or utcnow()
    newest = select(func.max(Telemetry.id)).group_by(Telemetry.device_id)
    if device_id:
        newest = newest.where(Telemetry.device_id == device_id)
    out = []
    for pkt in db.scalars(select(Telemetry).where(Telemetry.id.in_(newest)).order_by(Telemetry.device_id)):
        station = db.get(Station, pkt.station_id) if pkt.station_id else None
        out.append(serialize(pkt, station, now))
    return out
