"""Seed data: two stations and a realistic starting queue, placed around a demo centre point.

Station A (physical rig): 1 port, close to the centre, but busy with a queue.
Station B (simulated digital twin): 2 ports, farther away, plenty of power and a free port.
So a driver near the centre is often better served by the *farther* station B.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from .config import settings
from .db import utcnow
from .services.devices import ensure_placeholder_devices
from .models import (
    ControlEvent, ControlState, Device, DriverRequest, ExplanationLog, LiveLocation, Reservation, Session,
    Station, Telemetry,
)


def _add_res(db, station, name, cls, urgency, status, start_off, dur, kw, soc_target, arrival_off, now):
    start = now + timedelta(minutes=start_off)
    r = Reservation(
        station_id=station.id, driver_name=name, priority_class=cls, urgency=urgency,
        soc_arrival=20.0, soc_target=soc_target, battery_kwh=40.0,
        arrival_at=now + timedelta(minutes=arrival_off), planned_start_at=start,
        planned_end_at=start + timedelta(minutes=dur), allocated_kw=kw, status=status,
    )
    db.add(r)
    db.flush()
    if status == "active":
        db.add(Session(reservation_id=r.id, station_id=station.id, port_index=0,
                       started_at=start, allocated_kw=kw))
    return r


def seed_database(
    db: DbSession, reset: bool = True,
    center_lat: Optional[float] = None, center_lon: Optional[float] = None,
) -> dict:
    """Create stations + demo queue. reset=True wipes everything first; reset=False only seeds an empty DB."""
    if not reset and db.scalar(select(func.count()).select_from(Station)):
        return {"seeded": False, "reason": "database already has stations"}

    lat0 = settings.center_lat if center_lat is None else center_lat
    lon0 = settings.center_lon if center_lon is None else center_lon
    now = utcnow()

    for model in (ControlEvent, ControlState, Telemetry, Device, LiveLocation, ExplanationLog, Session,
                  Reservation, DriverRequest, Station):
        db.execute(delete(model))
    db.flush()

    a = Station(code="A", name="Station A (physical rig)", kind="physical",
                lat=lat0 + 0.0090, lon=lon0 + 0.0100, ports=1, max_kw_per_port=22.0,
                site_limit_kw=30.0, base_load_kw=3.0, is_online=True,
                device_id="esp32-station-a")
    b = Station(code="B", name="Station B (digital twin)", kind="simulated",
                lat=lat0 - 0.0300, lon=lon0 + 0.0250, ports=2, max_kw_per_port=50.0,
                site_limit_kw=100.0, base_load_kw=12.0, is_online=True)
    db.add_all([a, b])
    db.flush()

    # Station A: one active session ending in ~38 min, two drivers queued behind it.
    _add_res(db, a, "Arun K.", "flexible", 0.15, "active", -22, 60, 22.0, 90, -30, now)
    _add_res(db, a, "Divya S.", "normal", 0.45, "queued", 38, 30, 22.0, 80, -6, now)
    _add_res(db, a, "Karthik R.", "flexible", 0.20, "queued", 68, 25, 22.0, 80, -3, now)
    # Station B: one active 30 kW session on one of two ports.
    _add_res(db, b, "Meena P.", "normal", 0.40, "active", -14, 38, 30.0, 85, -20, now)

    db.commit()
    ensure_placeholder_devices(db)  # Station A expects an ESP32 that has not reported yet
    return {
        "seeded": True,
        "center": {"lat": lat0, "lon": lon0},
        "stations": db.scalar(select(func.count()).select_from(Station)),
        "reservations": db.scalar(select(func.count()).select_from(Reservation)),
    }
