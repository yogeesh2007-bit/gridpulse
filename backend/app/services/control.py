"""Station control layer: deterministic command decisions + persisted control state.

Commands are *simulated* until hardware exists, but they are real backend state: they are stored, logged,
served to devices (`GET /control/command/{device_id}`) and shown on the dashboard. When an ESP32 reports
telemetry with `mode == command` the command is marked hardware-confirmed. No LLM is involved here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import utcnow
from ..models import ControlEvent, ControlState, Station
from .devices import assess, get_device
from .state import advance_state, iso, station_live
from .telemetry import STALE_AFTER_S, latest_packet

COMMANDS = ("NORMAL", "REDUCE_LOAD", "PRIORITIZE_URGENT", "PAUSE_FLEX")

REDUCE_UTIL_PCT = 85.0  # site power threshold: at/above this, throttle to protect headroom
PAUSE_UTIL_PCT = 90.0  # at/above this with an urgent driver present, pause flexible sessions
REDUCE_FRACTION = 0.8
OVERTEMP_C = 70.0
OVERTEMP_FRACTION = 0.5
MIN_FRACTION, MAX_OVERLOAD_FRACTION = 0.3, 0.95
QUEUE_PRESSURE = 2  # this many drivers waiting counts as queue pressure
COMMAND_VALID_FOR_S = 15  # device must fall back to OFF if it hears nothing newer for this long


@dataclass(frozen=True)
class ControlDecision:
    command: str
    reason: str
    power_fraction: float  # share (0..1) of the station's current EV load that should keep running
    flex_paused: bool = False
    urgent_first: bool = False


def decide_command(view: dict, temperature_c: Optional[float] = None) -> ControlDecision:
    """Derive a station command from its live view. Pure and deterministic; rules are evaluated in order."""
    if not view["is_online"]:
        return ControlDecision("REDUCE_LOAD", "Station offline - charging output disabled", 0.0)
    if temperature_c is not None and temperature_c >= OVERTEMP_C:
        return ControlDecision(
            "REDUCE_LOAD",
            f"Over-temperature ({temperature_c:.0f} C >= {OVERTEMP_C:.0f} C) - cutting power to {OVERTEMP_FRACTION:.0%}",
            OVERTEMP_FRACTION,
        )

    util = view["utilization_pct"]
    active, queue = view["active"], view["queue"]
    ev_load = sum(a["kw"] for a in active)
    urgent_active = any(a["priority_class"] == "urgent" for a in active)
    urgent_queued = any(q["priority_class"] == "urgent" for q in queue)
    urgent_present = urgent_active or urgent_queued
    flex_active = [a for a in active if a["priority_class"] == "flexible"]
    urgent_waiting = urgent_queued and len(active) >= view["ports"]
    queue_pressure = view["queue_length"] >= QUEUE_PRESSURE

    if urgent_present and flex_active and (view["over_limit"] or util >= PAUSE_UTIL_PCT):
        kept = sum(a["kw"] for a in active if a["priority_class"] != "flexible")
        fraction = kept / ev_load if ev_load > 0 else 1.0
        return ControlDecision(
            "PAUSE_FLEX",
            f"Urgent driver present and site at {util:.0f}% of limit - pausing {len(flex_active)} flexible session(s)",
            round(fraction, 3), flex_paused=True, urgent_first=True,
        )
    if view["over_limit"]:
        allowed = max(0.0, view["site_limit_kw"] - view["base_load_kw"])
        fraction = min(MAX_OVERLOAD_FRACTION, max(MIN_FRACTION, allowed / ev_load)) if ev_load > 0 else MIN_FRACTION
        return ControlDecision(
            "REDUCE_LOAD",
            f"Overload risk: site at {util:.0f}% of its {view['site_limit_kw']:.0f} kW limit - scaling EV load to {fraction:.0%}",
            round(fraction, 3),
        )
    if urgent_present and (urgent_waiting or queue_pressure or util >= REDUCE_UTIL_PCT or flex_active):
        why = "urgent driver waiting for a port" if urgent_waiting else (
            "queue pressure" if queue_pressure else "limited spare power" if util >= REDUCE_UTIL_PCT else
            "flexible sessions can yield")
        return ControlDecision(
            "PRIORITIZE_URGENT", f"Urgent driver present ({why}) - urgent sessions get full power, flexible ones yield",
            1.0, urgent_first=True,
        )
    if util >= REDUCE_UTIL_PCT:
        return ControlDecision(
            "REDUCE_LOAD",
            f"Site power threshold: {util:.0f}% >= {REDUCE_UTIL_PCT:.0f}% of limit - reducing to {REDUCE_FRACTION:.0%} to keep headroom",
            REDUCE_FRACTION,
        )
    return ControlDecision("NORMAL", "Load and queue within limits", 1.0)


# ---- persisted state ---------------------------------------------------------------------------------
def control_view(cs: ControlState, station: Station, db: DbSession, now: datetime) -> dict:
    """A station's current command plus an honest statement of how (and whether) it is confirmed by hardware."""
    dev = get_device(db, station.device_id) if station.device_id else None
    if dev is None:
        dev_part = {
            "confirmation": "simulated", "source": "simulated", "hardware_confirmed": False, "device_mode": None,
            "freshness": "none", "hardware_mode": None, "telemetry_age_s": None, "ack_status": "none",
            "dry_run": None, "sensor_status": None, "local_override": False, "caveats": [],
            "fallback_reason": "Software-only station: no device is assigned - control is simulated by the backend",
        }
    else:
        a = assess(db, dev, cs, now)
        dev_part = {
            "confirmation": a["confirmation"],  # simulated | hardware-pending | hardware-confirmed
            "source": a["source"],  # "hardware" only for a real device with live telemetry
            "hardware_confirmed": a["hardware_confirmed"], "device_mode": a["device_mode"],
            "freshness": a["freshness"], "hardware_mode": a["reported_mode"],
            "telemetry_age_s": a["telemetry_age_s"], "ack_status": a["ack_status"], "dry_run": dev.dry_run,
            "sensor_status": dev.sensor_status, "local_override": dev.local_override, "caveats": a["caveats"],
            "fallback_reason": a["fallback_reason"],
        }
    return {
        "station_id": station.id,
        "station_code": station.code,
        "station_name": station.name,
        "device_id": station.device_id,
        "command": cs.command,
        "reason": cs.reason,
        "power_fraction": cs.power_fraction,
        "duty_pct": round(cs.power_fraction * 100),
        "seq": cs.seq,
        "valid_for_s": COMMAND_VALID_FOR_S,
        "command_generated_at": iso(cs.changed_at),
        "changed_at": iso(cs.changed_at),
        "updated_at": iso(cs.updated_at),
        **dev_part,
    }


def refresh_control_state(db: DbSession, now: Optional[datetime] = None) -> dict[int, dict]:
    """Recompute every station's command from live state, persist it, log changes. Returns views by station id."""
    now = now or utcnow()
    advance_state(db, now)
    views: dict[int, dict] = {}
    for st in db.scalars(select(Station).order_by(Station.id)):
        live = station_live(db, st, now)
        temp = None
        if st.device_id:
            pkt = latest_packet(db, st.device_id)
            if pkt and pkt.temperature is not None and (now - pkt.received_at).total_seconds() <= STALE_AFTER_S:
                temp = pkt.temperature
        decision = decide_command(live, temp)

        cs = db.scalar(select(ControlState).where(ControlState.station_id == st.id))
        if cs is None:
            cs = ControlState(station_id=st.id, command=decision.command, reason=decision.reason,
                              power_fraction=decision.power_fraction, seq=1, changed_at=now, updated_at=now)
            db.add(cs)
            db.add(ControlEvent(station_id=st.id, ts=now, command=decision.command, previous=None,
                                reason=decision.reason, power_fraction=decision.power_fraction))
        else:
            if cs.command != decision.command:
                db.add(ControlEvent(station_id=st.id, ts=now, command=decision.command, previous=cs.command,
                                    reason=decision.reason, power_fraction=decision.power_fraction))
                cs.command = decision.command
                cs.seq += 1
                cs.changed_at = now
            cs.reason = decision.reason
            cs.power_fraction = decision.power_fraction
            cs.updated_at = now
        db.flush()
        views[st.id] = control_view(cs, st, db, now)
    db.commit()
    return views


def recent_events(db: DbSession, limit: int = 10) -> list[dict]:
    out = []
    for ev in db.scalars(select(ControlEvent).order_by(ControlEvent.id.desc()).limit(limit)):
        st = db.get(Station, ev.station_id)
        out.append({
            "id": ev.id, "ts": iso(ev.ts), "station_id": ev.station_id, "station_code": st.code if st else None,
            "command": ev.command, "previous": ev.previous, "reason": ev.reason, "power_fraction": ev.power_fraction,
        })
    return out
