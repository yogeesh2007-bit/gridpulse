"""Scheduler service: keeps the charging schedule moving without anyone calling the API.

The deterministic scheduling logic lives in `scheduling.py` (queue simulation, power gating, scoring) and
`state.py` (reservation lifecycle, re-planning). This service is the clock that drives it: every tick it
advances reservations (queued -> active -> done) and recomputes each station's control command, then pokes
the WebSocket broadcaster if anything changed. No AI is involved anywhere in this loop.
"""
from __future__ import annotations

import asyncio

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..models import ControlState, Reservation
from . import realtime
from .control import refresh_control_state
from .state import advance_state


def _signature(db) -> tuple:
    res = db.execute(select(Reservation.id, Reservation.status).order_by(Reservation.id)).all()
    ctl = db.execute(select(ControlState.station_id, ControlState.seq).order_by(ControlState.station_id)).all()
    return tuple(map(tuple, res)), tuple(map(tuple, ctl))


def tick() -> bool:
    """Advance the schedule once. Returns True if reservations or control commands changed."""
    with SessionLocal() as db:
        before = _signature(db)
        advance_state(db)
        refresh_control_state(db)
        return _signature(db) != before


async def run() -> None:
    """Background loop (started by the app's lifespan)."""
    while True:
        try:
            if await run_in_threadpool(tick):
                realtime.poke()
        except Exception as exc:  # keep the clock alive through transient errors (e.g. a locked DB)
            print(f"[gridpulse] scheduler tick failed: {type(exc).__name__}: {exc}")
        await asyncio.sleep(settings.scheduler_tick_s)
