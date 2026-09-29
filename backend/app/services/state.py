"""Database-backed station state: lifecycle transitions, snapshots for the engine, serializers."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import utcnow
from ..models import Reservation, Session, Station
from .scheduling import (
    PRIORITY_RANK,
    ActiveLoad,
    QueueJob,
    QueuedLoad,
    StationSnapshot,
    simulate_queue,
)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return None if dt is None else dt.isoformat() + "Z"


def _minutes(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 60.0


# ---- lifecycle -------------------------------------------------------------------------------------
def advance_state(db: DbSession, now: Optional[datetime] = None) -> None:
    """Move reservations through queued -> active -> done according to their planned times."""
    now = now or utcnow()
    changed = False

    finishing = db.scalars(
        select(Reservation).where(Reservation.status == "active", Reservation.planned_end_at <= now)
    ).all()
    for r in finishing:
        r.status = "done"
        for s in db.scalars(
            select(Session).where(Session.reservation_id == r.id, Session.ended_at.is_(None))
        ):
            s.ended_at = r.planned_end_at
            hours = max(0.0, _minutes(s.ended_at, s.started_at)) / 60.0
            s.energy_kwh = round(s.allocated_kw * hours, 2)
        changed = True
    if changed:
        db.flush()

    starting = db.scalars(
        select(Reservation)
        .where(Reservation.status == "queued", Reservation.planned_start_at <= now)
        .order_by(Reservation.planned_start_at, Reservation.id)
    ).all()
    for r in starting:
        used = set(
            db.scalars(
                select(Session.port_index).where(
                    Session.station_id == r.station_id, Session.ended_at.is_(None)
                )
            ).all()
        )
        port = next(i for i in range(len(used) + 1) if i not in used)
        r.status = "active"
        db.add(
            Session(
                reservation_id=r.id, station_id=r.station_id, port_index=port,
                started_at=r.planned_start_at, allocated_kw=r.allocated_kw,
            )
        )
        db.flush()
        changed = True
    if changed:
        db.commit()


def reschedule_station(db: DbSession, station_id: int, now: Optional[datetime] = None) -> None:
    """Recompute planned start/end for every queued reservation at a station (priority + power aware)."""
    now = now or utcnow()
    st = db.get(Station, station_id)
    actives = db.scalars(
        select(Reservation).where(Reservation.station_id == station_id, Reservation.status == "active")
    ).all()
    queued = db.scalars(
        select(Reservation).where(Reservation.station_id == station_id, Reservation.status == "queued")
    ).all()
    if not queued:
        return
    running = [(-1e9, max(0.0, _minutes(a.planned_end_at, now)), a.allocated_kw) for a in actives]
    port_free = [e for _, e, _ in running][: st.ports]
    port_free += [0.0] * (st.ports - len(port_free))
    jobs = [
        QueueJob(
            f"r{q.id}", _minutes(q.arrival_at, now), _minutes(q.planned_end_at, q.planned_start_at),
            PRIORITY_RANK[q.priority_class], q.allocated_kw,
        )
        for q in queued
    ]
    slots = simulate_queue(port_free, jobs, running, st.site_limit_kw - st.base_load_kw)
    for q in queued:
        slot = slots[f"r{q.id}"]
        q.planned_start_at = now + timedelta(minutes=slot.start_min)
        q.planned_end_at = now + timedelta(minutes=slot.end_min)
    db.commit()


# ---- snapshots for the engine ------------------------------------------------------------------------
def load_snapshots(db: DbSession, now: Optional[datetime] = None) -> list[StationSnapshot]:
    now = now or utcnow()
    snaps: list[StationSnapshot] = []
    for st in db.scalars(select(Station).order_by(Station.id)):
        res = db.scalars(
            select(Reservation).where(
                Reservation.station_id == st.id, Reservation.status.in_(("active", "queued"))
            )
        ).all()
        active = tuple(
            ActiveLoad(max(0.0, _minutes(r.planned_end_at, now)), r.allocated_kw)
            for r in res if r.status == "active"
        )
        queued = tuple(
            QueuedLoad(
                f"r{r.id}", _minutes(r.arrival_at, now), _minutes(r.planned_end_at, r.planned_start_at),
                PRIORITY_RANK[r.priority_class], r.allocated_kw,
            )
            for r in res if r.status == "queued"
        )
        snaps.append(
            StationSnapshot(
                id=st.id, code=st.code, name=st.name, kind=st.kind, lat=st.lat, lon=st.lon,
                ports=st.ports, max_kw_per_port=st.max_kw_per_port, site_limit_kw=st.site_limit_kw,
                base_load_kw=st.base_load_kw, is_online=st.is_online, active=active, queued=queued,
            )
        )
    return snaps


# ---- serializers -------------------------------------------------------------------------------------
def reservation_out(r: Reservation, db: DbSession, now: Optional[datetime] = None) -> dict:
    now = now or utcnow()
    position = None
    if r.status == "queued":
        ahead = db.scalars(
            select(Reservation).where(
                Reservation.station_id == r.station_id, Reservation.status == "queued"
            ).order_by(Reservation.planned_start_at, Reservation.id)
        ).all()
        position = next((i + 1 for i, q in enumerate(ahead) if q.id == r.id), None)
    return {
        "id": r.id,
        "request_id": r.request_id,
        "station_id": r.station_id,
        "station_code": r.station.code,
        "station_name": r.station.name,
        "driver_name": r.driver_name,
        "priority_class": r.priority_class,
        "urgency": r.urgency,
        "soc_arrival": r.soc_arrival,
        "soc_target": r.soc_target,
        "allocated_kw": r.allocated_kw,
        "status": r.status,
        "queue_position": position,
        "arrival_at": iso(r.arrival_at),
        "planned_start_at": iso(r.planned_start_at),
        "planned_end_at": iso(r.planned_end_at),
        "minutes_to_start": round(max(0.0, _minutes(r.planned_start_at, now)), 1),
        "minutes_to_end": round(max(0.0, _minutes(r.planned_end_at, now)), 1),
        "created_at": iso(r.created_at),
    }


def station_live(db: DbSession, st: Station, now: Optional[datetime] = None) -> dict:
    now = now or utcnow()
    res = db.scalars(
        select(Reservation).where(
            Reservation.station_id == st.id, Reservation.status.in_(("active", "queued"))
        ).order_by(Reservation.planned_start_at, Reservation.id)
    ).all()
    active = [r for r in res if r.status == "active"]
    queued = [r for r in res if r.status == "queued"]
    ports = {
        s.reservation_id: s.port_index
        for s in db.scalars(
            select(Session).where(Session.station_id == st.id, Session.ended_at.is_(None))
        )
    }
    ev_kw = sum(r.allocated_kw for r in active)
    load = st.base_load_kw + ev_kw
    return {
        "id": st.id,
        "code": st.code,
        "name": st.name,
        "kind": st.kind,
        "device_id": st.device_id,
        "lat": st.lat,
        "lon": st.lon,
        "lng": st.lon,
        "ports": st.ports,
        "max_kw_per_port": st.max_kw_per_port,
        "site_limit_kw": st.site_limit_kw,
        "base_load_kw": st.base_load_kw,
        "is_online": st.is_online,
        # ---- problem-statement shape: available_ports, queue_count, current_load_w, site_power_limit_w, lat, lng
        "available_ports": max(0, st.ports - len(active)),
        "queue_count": len(queued),
        "current_load_w": round(load * 1000.0, 1),
        "site_power_limit_w": round(st.site_limit_kw * 1000.0, 1),
        "state": {
            "available_ports": max(0, st.ports - len(active)),
            "queue_count": len(queued),
            "current_load_w": round(load * 1000.0, 1),
            "site_power_limit_w": round(st.site_limit_kw * 1000.0, 1),
            "lat": st.lat,
            "lng": st.lon,
        },
        "ev_load_kw": round(ev_kw, 1),
        "current_load_kw": round(load, 1),
        "headroom_kw": round(max(0.0, st.site_limit_kw - load), 1),
        "utilization_pct": round(min(100.0, load / st.site_limit_kw * 100.0), 1) if st.site_limit_kw else 0.0,
        "over_limit": load > st.site_limit_kw + 1e-6,
        "ports_busy": len(active),
        "queue_length": len(queued),
        "active": [
            {
                "reservation_id": r.id,
                "driver_name": r.driver_name,
                "priority_class": r.priority_class,
                "kw": r.allocated_kw,
                "port_index": ports.get(r.id),
                "soc_target": r.soc_target,
                "ends_at": iso(r.planned_end_at),
                "remaining_min": round(max(0.0, _minutes(r.planned_end_at, now)), 1),
            }
            for r in active
        ],
        "queue": [
            {
                "reservation_id": r.id,
                "position": i + 1,
                "driver_name": r.driver_name,
                "priority_class": r.priority_class,
                "urgency": r.urgency,
                "kw": r.allocated_kw,
                "arrival_at": iso(r.arrival_at),
                "planned_start_at": iso(r.planned_start_at),
                "starts_in_min": round(max(0.0, _minutes(r.planned_start_at, now)), 1),
            }
            for i, r in enumerate(queued)
        ],
    }
