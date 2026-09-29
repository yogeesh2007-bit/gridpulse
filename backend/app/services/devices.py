"""Device model: real vs simulated devices, telemetry freshness, command delivery and acknowledgments.

The single most important rule here is honesty about what is real:

* ``device_mode`` is "real" or "simulated". It follows the *source declared by the latest packet*, so a
  simulated tool can never make a real device look confirmed (or vice versa).
* ``hardware_confirmed`` is True only for a **real** device with **live** telemetry that either echoes the
  commanded mode or acknowledged the current command. Everything else is control simulated by the backend,
  and ``fallback_reason`` says exactly why.
* ``dry_run`` and ``sensor_status`` are reported separately: a real device in dry-run confirms commands but does
  not switch a physical output (``output_physical`` False).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..models import ControlState, Device, Station, Telemetry
from ..schemas import AckIn, DeviceRegisterIn, TelemetryIn
from .state import iso

LIVE_S = 10.0  # newest telemetry younger than this => "live"
OFFLINE_AFTER_S = 60.0  # older than this (or never) => "offline"; in between => "stale"


class DeviceError(Exception):
    """Raised for client-visible problems; routers translate it to an HTTP error."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _reset_activity(dev: Device) -> None:
    """Forget button/command/ack history. Called when a device changes between real and simulated, so activity
    produced by a simulator is never attributed to real hardware (or the other way round)."""
    dev.local_override = False
    dev.button_count = 0
    dev.last_button_at = None
    dev.last_poll_at = None
    dev.last_sent_seq = dev.last_sent_command = dev.last_sent_at = None
    dev.last_ack_seq = dev.last_ack_command = dev.last_ack_status = dev.last_ack_detail = dev.last_ack_at = None


# ---- lookup / registration -------------------------------------------------------------------------
def get_device(db: DbSession, device_id: str) -> Optional[Device]:
    return db.scalar(select(Device).where(Device.device_id == device_id))


def ensure_placeholder_devices(db: DbSession) -> None:
    """Every station that names a device gets a device row, so the dashboard can show 'expected, not seen yet'.

    These rows are placeholders (registered=False) until the device registers or sends telemetry.
    """
    changed = False
    for st in db.scalars(select(Station).where(Station.device_id.is_not(None))):
        dev = get_device(db, st.device_id)
        if dev is None:
            db.add(Device(device_id=st.device_id, station_id=st.id, device_mode="real", registered=False))
            changed = True
        elif dev.station_id is None:
            dev.station_id = st.id
            changed = True
    if changed:
        db.commit()


def register_device(db: DbSession, body: DeviceRegisterIn, now: datetime) -> Device:
    dev = get_device(db, body.device_id)
    if dev is None:
        dev = Device(device_id=body.device_id)
        db.add(dev)

    station: Optional[Station] = None
    if body.station_code:
        station = db.scalar(select(Station).where(Station.code == body.station_code))
        if station is None:
            raise DeviceError(404, f"Station '{body.station_code}' not found")
        if station.device_id and station.device_id != body.device_id:
            raise DeviceError(409, f"Station {station.code} is already bound to device '{station.device_id}'")
        station.device_id = body.device_id
    else:
        station = db.scalar(select(Station).where(Station.device_id == body.device_id))
    dev.station_id = station.id if station else dev.station_id

    if dev.device_mode != body.device_mode and dev.last_seen_at is not None:
        _reset_activity(dev)
    dev.device_mode = body.device_mode
    dev.dry_run = body.dry_run
    dev.sensor_status = body.sensor_status
    dev.firmware_version = body.firmware_version or dev.firmware_version
    if not dev.registered:
        dev.registered = True
        dev.registered_at = now
    dev.last_seen_at = now
    db.commit()
    return dev


def note_packet(db: DbSession, body: TelemetryIn, station_id: Optional[int], now: datetime) -> Device:
    """Update the device row from a telemetry packet (auto-registering unknown devices)."""
    dev = get_device(db, body.device_id)
    if dev is None:
        dev = Device(device_id=body.device_id, registered_at=now)
        db.add(dev)
    dev.registered = True
    dev.registered_at = dev.registered_at or now
    dev.station_id = station_id or dev.station_id
    if dev.device_mode != body.source and dev.last_seen_at is not None:
        _reset_activity(dev)
    dev.telemetry_source = body.source
    dev.device_mode = body.source  # mode follows what the device itself declares
    dev.dry_run = body.dry_run
    dev.sensor_status = body.sensor_status
    dev.last_telemetry_at = dev.last_seen_at = now
    if body.local_override is not None:
        dev.local_override = body.local_override
    if body.event == "button_press":
        dev.button_count = (dev.button_count or 0) + 1
        dev.last_button_at = now
    db.flush()
    return dev


def record_poll(db: DbSession, dev: Device, seq: int, command: str, now: datetime) -> None:
    dev.last_poll_at = dev.last_seen_at = now
    dev.last_sent_seq, dev.last_sent_command, dev.last_sent_at = seq, command, now
    db.commit()


def record_ack(db: DbSession, dev: Device, body: AckIn, current_seq: int, now: datetime) -> bool:
    """Store an acknowledgment. Returns True if it was stale (for an older command) and therefore ignored."""
    dev.last_seen_at = now
    if body.dry_run is not None:
        dev.dry_run = body.dry_run
    if body.seq != current_seq:
        db.commit()
        return True
    dev.last_ack_seq, dev.last_ack_command = body.seq, body.command
    dev.last_ack_status, dev.last_ack_detail, dev.last_ack_at = body.status, body.detail, now
    if body.status == "local_override":
        dev.local_override = True
    db.commit()
    return False


# ---- derived state ---------------------------------------------------------------------------------
def last_telemetry(db: DbSession, dev: Device) -> tuple[Optional[datetime], Optional[str]]:
    """(received_at, mode) of the newest packet. The telemetry table is the single source of truth for freshness."""
    row = db.execute(
        select(Telemetry.received_at, Telemetry.mode).where(Telemetry.device_id == dev.device_id)
        .order_by(Telemetry.id.desc()).limit(1)
    ).first()
    return (row[0], row[1]) if row else (None, None)


def freshness(last_at: Optional[datetime], now: datetime) -> tuple[str, Optional[float]]:
    if last_at is None:
        return "offline", None
    age = max(0.0, (now - last_at).total_seconds())
    if age <= LIVE_S:
        return "live", round(age, 1)
    return ("stale" if age <= OFFLINE_AFTER_S else "offline"), round(age, 1)


def assess(db: DbSession, dev: Device, cs: Optional[ControlState], now: datetime) -> dict:
    """Everything the control layer and dashboard need to say about this device, honestly."""
    last_at, reported_mode = last_telemetry(db, dev)
    fresh, age = freshness(last_at, now)
    mode = dev.device_mode

    echo = bool(cs) and reported_mode == cs.command
    acked = bool(cs) and dev.last_ack_seq == cs.seq and dev.last_ack_status == "applied"
    real_live = mode == "real" and fresh == "live"
    # A device that reports a safety/hold mode is NOT running the command, whatever it acknowledged earlier.
    holding = (bool(dev.local_override) or reported_mode in ("LOCAL_OVERRIDE", "FAILSAFE")
               or (reported_mode or "").startswith("FAULT_"))
    hardware_confirmed = real_live and not holding and (echo or acked)
    if real_live:
        confirmation = "hardware-confirmed" if hardware_confirmed else "hardware-pending"
        source = "hardware"
    else:
        confirmation, source = "simulated", "simulated"

    if not dev.registered and last_at is None:
        reason = (f"Device '{dev.device_id}' has not reported yet (placeholder) - "
                  "control is simulated by the backend")
    elif mode == "simulated":
        reason = f"Device is a simulated device ({fresh}) - not real hardware; control is simulated"
    elif fresh == "stale":
        reason = f"Real device telemetry is stale ({age:.0f} s old) - falling back to simulated control"
    elif fresh == "offline":
        seen = f"last telemetry {age:.0f} s ago" if age is not None else "no telemetry received"
        reason = f"Real device is offline ({seen}) - falling back to simulated control"
    else:
        reason = None

    if cs is not None and dev.last_ack_seq == cs.seq:
        ack_status = dev.last_ack_status
    elif dev.last_sent_seq is not None or dev.last_ack_seq is not None:
        ack_status = "pending"
    else:
        ack_status = "none"

    caveats = []
    if dev.dry_run:
        caveats.append("Dry-run: output pin is not driven; commands are computed and acknowledged only")
    if dev.sensor_status in ("missing", "error"):
        caveats.append(f"INA219 sensor {dev.sensor_status}: telemetry values are placeholders, not measurements")
    elif dev.sensor_status == "simulated":
        caveats.append("Simulated sensor values")
    if mode == "simulated":
        caveats.append("Simulated device: packets are synthetic")
    if dev.local_override:
        caveats.append("Local override active (button): device output is held OFF regardless of commands")

    return {
        "freshness": fresh, "telemetry_age_s": age, "last_telemetry_at": last_at, "device_mode": mode,
        "reported_mode": reported_mode,
        "confirmation": confirmation, "source": source, "hardware_confirmed": hardware_confirmed,
        "fallback_reason": reason, "ack_status": ack_status, "caveats": caveats,
        "output_physical": mode == "real" and not dev.dry_run,
    }


def device_view(db: DbSession, dev: Device, now: datetime) -> dict:
    station = db.get(Station, dev.station_id) if dev.station_id else None
    cs = db.scalar(select(ControlState).where(ControlState.station_id == dev.station_id)) if dev.station_id else None
    a = assess(db, dev, cs, now)
    return {
        "device_id": dev.device_id,
        "device_mode": dev.device_mode,
        "registered": dev.registered,
        "placeholder": not dev.registered,
        "station_id": dev.station_id,
        "station_code": station.code if station else None,
        "telemetry_source": dev.telemetry_source,
        "freshness": a["freshness"],
        "stale": a["freshness"] != "live",
        "telemetry_age_s": a["telemetry_age_s"],
        "last_telemetry_at": iso(a["last_telemetry_at"]),
        "last_seen_at": iso(dev.last_seen_at),
        "last_polled_at": iso(dev.last_poll_at),
        "reported_mode": a["reported_mode"],
        "hardware_confirmed": a["hardware_confirmed"],
        "confirmation": a["confirmation"],
        "control_source": a["source"],
        "ack_status": a["ack_status"],
        "command_generated_at": iso(cs.changed_at) if cs else None,
        "current_command": (
            {"command": cs.command, "seq": cs.seq, "power_fraction": cs.power_fraction,
             "generated_at": iso(cs.changed_at)} if cs else None
        ),
        "last_command_sent": (
            {"command": dev.last_sent_command, "seq": dev.last_sent_seq, "at": iso(dev.last_sent_at)}
            if dev.last_sent_seq is not None else None
        ),
        "last_ack": (
            {"seq": dev.last_ack_seq, "command": dev.last_ack_command, "status": dev.last_ack_status,
             "detail": dev.last_ack_detail, "at": iso(dev.last_ack_at)}
            if dev.last_ack_seq is not None else None
        ),
        "dry_run": dev.dry_run,
        "sensor_status": dev.sensor_status,
        "output_physical": a["output_physical"],
        "local_override": dev.local_override,
        "button_count": dev.button_count,
        "last_button_at": iso(dev.last_button_at),
        "firmware_version": dev.firmware_version,
        "caveats": a["caveats"],
        "fallback_reason": a["fallback_reason"],
    }


def list_views(db: DbSession, now: datetime) -> list[dict]:
    return [device_view(db, d, now) for d in db.scalars(select(Device).order_by(Device.id))]


def hardware_summary(views: list[dict]) -> dict:
    """One-glance status for the dashboard header: are we running on real hardware, a simulator, or software only?"""
    s = {"real_live": 0, "simulated_live": 0, "stale": 0, "offline": 0, "placeholder": 0, "total": len(views)}
    for v in views:
        if v["placeholder"]:
            s["placeholder"] += 1
        elif v["freshness"] == "live":
            s["real_live" if v["device_mode"] == "real" else "simulated_live"] += 1
        elif v["freshness"] == "stale":
            s["stale"] += 1
        else:
            s["offline"] += 1
    s["mode"] = "real" if s["real_live"] else "simulated" if s["simulated_live"] else "software"
    return s
