"""Bulb/relay nodes: latest state, remote commands, and an event log.

Model: every node has a *desired* state (what the backend wants) and a *reported* state (what the device says it is).
  * a manual button press is the owner's latest intent, so it becomes the new desired state (no revert on next poll)
  * a remote command from the UI sets the desired state; the device applies it on its next poll and reports back
  * boot / heartbeat reports never change the desired state
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from ..models import BulbDevice, BulbEvent
from .state import iso

ONLINE_S = 25.0  # the firmware heartbeats every 10 s and polls every 3 s
DEFAULT_DEVICE = "bulb-01"
MANUAL_SOURCES = {"manual_button", "manual_button_on", "manual_button_off", "state_change"}  # physical switch presses
SOURCES = ("boot", "heartbeat", "manual_button_on", "manual_button_off", "manual_button", "state_change", "remote_command")


def check_consistent(source: str, bulb_on: bool) -> None:
    """A manual_button_on event must report the bulb ON (and _off OFF): contradictions are rejected, never stored."""
    if (source.endswith("_on") and not bulb_on) or (source.endswith("_off") and bulb_on):
        raise ValueError(f"source '{source}' contradicts bulb_on={str(bulb_on).lower()}")
DEVICE_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{1,39}$"


def get_or_create(db: DbSession, device_id: str) -> BulbDevice:
    d = db.scalar(select(BulbDevice).where(BulbDevice.device_id == device_id))
    if d is None:
        d = BulbDevice(device_id=device_id, name=device_id)
        db.add(d)
        db.flush()
    return d


def ensure_default(db: DbSession) -> None:
    """A placeholder node so the UI has something to show (offline) before the hardware first reports in."""
    if db.scalar(select(BulbDevice.id).limit(1)) is None:
        get_or_create(db, DEFAULT_DEVICE)
        db.commit()


def seed_demo(db: DbSession, now: datetime) -> None:
    """Seed bulb-01 with a coherent history: booted OFF, then manual switch events, currently ON (as the relay would be).
    The state, the event log and the metadata all tell the same story; timestamps are relative to `now`."""
    db.execute(delete(BulbEvent))
    db.execute(delete(BulbDevice))
    ago = lambda **kw: now - timedelta(**kw)  # noqa: E731
    story = [  # (when, source, bulb_on)
        (ago(minutes=42), "boot", False),
        (ago(minutes=30), "manual_button_on", True),
        (ago(minutes=18), "manual_button_off", False),
        (ago(minutes=3), "manual_button_on", True),
    ]
    for ts, source, on in story:
        db.add(BulbEvent(device_id=DEFAULT_DEVICE, ts=ts, kind="status", on=on, source=source, detail="rssi -58"))
    db.add(BulbDevice(
        device_id=DEFAULT_DEVICE, name=DEFAULT_DEVICE, desired_on=True, reported_on=True, last_source="manual_button_on",
        last_seen_at=ago(seconds=4), last_state_change_at=ago(minutes=3), commanded_at=ago(minutes=3), commanded_by="button",
        command_seq=3, rssi=-58, firmware="gp-bulb 1.0.0", mode="manual_override",
    ))
    db.commit()


def seed_demo_if_empty(db: DbSession, now: datetime) -> None:
    if db.scalar(select(BulbDevice.id).limit(1)) is None:
        seed_demo(db, now)


def _log(db: DbSession, device_id: str, kind: str, on: Optional[bool], source: Optional[str], detail: Optional[str], now: datetime) -> None:
    db.add(BulbEvent(device_id=device_id, ts=now, kind=kind, on=on, source=source, detail=detail))


def record_status(db: DbSession, device_id: str, bulb_on: bool, source: str, rssi: Optional[int],
                  firmware: Optional[str], now: datetime) -> BulbDevice:
    d = get_or_create(db, device_id)
    changed = d.reported_on is not bulb_on
    d.reported_on, d.last_source, d.last_seen_at, d.rssi = bulb_on, source, now, rssi
    d.firmware = firmware or d.firmware
    if changed:
        d.last_state_change_at = now
    d.mode = "manual_override" if source in MANUAL_SOURCES else ("remote_control" if source == "remote_command" else ("boot" if source == "boot" else d.mode))
    if source in MANUAL_SOURCES:
        d.desired_on = bulb_on  # the button press is the newest intent
        d.command_seq += 1
        d.commanded_by, d.commanded_at = "button", now
    if changed or source != "heartbeat":
        _log(db, device_id, "status", bulb_on, source, f"rssi {rssi}" if rssi is not None else None, now)
    db.commit()
    return d


def set_command(db: DbSession, device_id: str, on: bool, by: str, now: datetime) -> BulbDevice:
    d = get_or_create(db, device_id)
    d.desired_on, d.commanded_by, d.commanded_at = on, by, now
    d.mode = "remote_control"
    d.command_seq += 1
    _log(db, device_id, "command", on, "remote", f"by {by}", now)
    db.commit()
    return d


def view(d: BulbDevice, now: datetime) -> dict:
    age = (now - d.last_seen_at).total_seconds() if d.last_seen_at else None
    online = age is not None and age <= ONLINE_S
    state = "unknown" if d.reported_on is None else ("on" if d.reported_on else "off")
    return {
        "device_id": d.device_id, "name": d.name, "online": online, "seen": d.last_seen_at is not None,
        "state": state, "reported_on": d.reported_on, "desired_on": d.desired_on,
        "sync": "unknown" if d.reported_on is None else ("in_sync" if d.reported_on == d.desired_on else "pending"),
        "last_source": d.last_source, "last_seen_at": iso(d.last_seen_at), "age_s": None if age is None else round(age, 1),
        "last_state_change_at": iso(d.last_state_change_at), "rssi": d.rssi, "firmware": d.firmware,
        "commanded_by": d.commanded_by, "commanded_at": iso(d.commanded_at), "command_seq": d.command_seq,
        "device_type": d.device_type, "coach_id": d.coach_id, "zone": d.zone, "voltage_type": d.voltage_type,
        "install_context": d.install_context, "mode": d.mode, "live": True,  # this node is real hardware, never seeded
        # derived from real events only: a node that stopped reporting is flagged, nothing else is ever invented
        "health": "healthy" if online else ("offline" if d.last_seen_at else "unknown"),
        "alert": "Node offline: no report for over %ds, last known state shown" % ONLINE_S if (d.last_seen_at and not online) else None,
    }


def list_views(db: DbSession, now: datetime) -> list[dict]:
    ensure_default(db)
    return [view(d, now) for d in db.scalars(select(BulbDevice).order_by(BulbDevice.id))]


def recent_events(db: DbSession, device_id: str, limit: int = 20) -> list[dict]:
    rows = db.scalars(select(BulbEvent).where(BulbEvent.device_id == device_id).order_by(BulbEvent.id.desc()).limit(limit))
    return [{"id": e.id, "ts": iso(e.ts), "kind": e.kind, "on": e.on, "source": e.source, "detail": e.detail} for e in rows]
