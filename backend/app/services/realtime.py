"""WebSocket connection manager and broadcaster.

Design: connections are authenticated with an access token. A single background task wakes up every
`ws_tick_s` seconds - or immediately when something calls `poke()` after a change - builds the snapshots that
are needed, and pushes them:

  * operators receive the full dashboard state   {"type": "state",  "data": {...}}
  * drivers receive their own reservations and the public station view, only when it changed
                                                  {"type": "driver", "data": {"reservations": [...], "stations": [...]}}

Database work runs in the thread pool so the event loop is never blocked. A connection is closed with code 4401
when its access token expires; the browser refreshes the token and reconnects.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal, utcnow
from ..models import DriverRequest, Reservation, Station
from .dashboard import build_dashboard_state
from .state import advance_state, iso, reservation_out, station_live

WS_TOKEN_EXPIRED = 4401
PUBLIC_STATION_KEYS = (
    "id", "code", "name", "kind", "lat", "lon", "lng", "ports", "max_kw_per_port", "site_limit_kw", "is_online",
    "available_ports", "queue_count", "current_load_w", "site_power_limit_w", "utilization_pct", "over_limit",
    "ev_load_kw", "current_load_kw", "headroom_kw", "ports_busy", "state",
)


# ---- snapshots (run in worker threads, own DB session) -----------------------------------------------------
def public_station_view(live: dict) -> dict:
    """What a driver may see about a station: availability and load - not other drivers or hardware internals."""
    return {k: live[k] for k in PUBLIC_STATION_KEYS}


def driver_reservations(db, user_id: int, limit: int = 30) -> list[dict]:
    now = utcnow()
    rows = db.scalars(
        select(Reservation).join(DriverRequest, DriverRequest.id == Reservation.request_id)
        .where(DriverRequest.user_id == user_id).order_by(Reservation.id.desc()).limit(limit)
    ).all()
    return [reservation_out(r, db, now) for r in rows]


def public_stations(db) -> list[dict]:
    now = utcnow()
    return [public_station_view(station_live(db, s, now)) for s in db.scalars(select(Station).order_by(Station.id))]


def _operator_snapshot() -> dict:
    with SessionLocal() as db:
        return build_dashboard_state(db)


def _driver_snapshot(user_id: int) -> dict:
    with SessionLocal() as db:
        advance_state(db)
        return {"reservations": driver_reservations(db, user_id), "stations": public_stations(db)}


def _stable_hash(snapshot: dict) -> str:
    """Hash of the parts of a driver snapshot that matter; volatile 'minutes_to' counters are excluded."""
    core = {
        "r": [(r["id"], r["status"], r["queue_position"], r["planned_start_at"], r["planned_end_at"])
              for r in snapshot["reservations"]],
        "s": [(s["id"], s["available_ports"], s["queue_count"], s["current_load_w"], s["site_power_limit_w"],
               s["is_online"]) for s in snapshot["stations"]],
    }
    return hashlib.sha1(json.dumps(core, sort_keys=True).encode()).hexdigest()


# ---- connections -----------------------------------------------------------------------------------------------
@dataclass
class Connection:
    ws: WebSocket
    user_id: int
    role: str
    expires_at: float  # unix time the access token expires
    last_hash: Optional[str] = None
    connected_at: float = field(default_factory=time.time)


class ConnectionManager:
    def __init__(self) -> None:
        self._conns: dict[WebSocket, Connection] = {}

    def add(self, conn: Connection) -> None:
        self._conns[conn.ws] = conn

    def remove(self, ws: WebSocket) -> None:
        self._conns.pop(ws, None)

    def count(self, role: Optional[str] = None) -> int:
        return sum(1 for c in self._conns.values() if role is None or c.role == role)

    def clear(self) -> None:
        self._conns.clear()

    async def _send(self, conn: Connection, message: dict) -> bool:
        try:
            await conn.ws.send_text(json.dumps(message, default=str))
            return True
        except Exception:  # client went away mid-send
            self.remove(conn.ws)
            return False

    async def close_expired(self) -> None:
        now = time.time()
        for conn in [c for c in self._conns.values() if c.expires_at <= now]:
            self.remove(conn.ws)
            try:
                await conn.ws.close(code=WS_TOKEN_EXPIRED, reason="access token expired")
            except Exception:
                pass

    async def push_updates(self) -> None:
        await self.close_expired()
        operators = [c for c in self._conns.values() if c.role == "operator"]
        if operators:
            state = await run_in_threadpool(_operator_snapshot)
            message = {"type": "state", "ts": iso(utcnow()), "data": state}
            for conn in operators:
                await self._send(conn, message)

        by_user: dict[int, list[Connection]] = {}
        for c in self._conns.values():
            if c.role == "driver":
                by_user.setdefault(c.user_id, []).append(c)
        for user_id, conns in by_user.items():
            snapshot = await run_in_threadpool(_driver_snapshot, user_id)
            digest = _stable_hash(snapshot)
            message = {"type": "driver", "ts": iso(utcnow()), "data": snapshot}
            for conn in conns:
                if conn.last_hash != digest:
                    if await self._send(conn, message):
                        conn.last_hash = digest


manager = ConnectionManager()

_loop: Optional[asyncio.AbstractEventLoop] = None
_event: Optional[asyncio.Event] = None


def poke() -> None:
    """Ask the broadcaster to push right now. Safe to call from any thread, and when nothing is running."""
    if _loop is not None and _event is not None and not _loop.is_closed():
        _loop.call_soon_threadsafe(_event.set)


async def broadcaster() -> None:
    """Background task: push updates every tick, or sooner when poked."""
    global _loop, _event
    _loop, _event = asyncio.get_running_loop(), asyncio.Event()
    try:
        while True:
            try:
                await asyncio.wait_for(_event.wait(), timeout=settings.ws_tick_s)
            except asyncio.TimeoutError:
                pass
            _event.clear()
            if manager.count() == 0:
                continue
            try:
                await manager.push_updates()
            except Exception as exc:  # never let one bad tick kill the loop
                print(f"[gridpulse] realtime tick failed: {type(exc).__name__}: {exc}")
    finally:
        _loop = _event = None
