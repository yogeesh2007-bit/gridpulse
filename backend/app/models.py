"""SQLAlchemy ORM models. All datetimes are naive UTC."""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20))  # "physical" | "simulated"
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    ports: Mapped[int] = mapped_column(Integer)
    max_kw_per_port: Mapped[float] = mapped_column(Float)
    site_limit_kw: Mapped[float] = mapped_column(Float)  # grid connection limit for the whole site
    base_load_kw: Mapped[float] = mapped_column(Float)  # non-EV load on the same connection
    is_online: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    device_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # ESP32 bound to this station


class DriverRequest(Base):
    __tablename__ = "driver_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    driver_name: Mapped[str] = mapped_column(String(60), default="Driver")
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    location_source: Mapped[str] = mapped_column(String(10), default="gps")
    location_accuracy_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    soc_current: Mapped[float] = mapped_column(Float)
    soc_target: Mapped[float] = mapped_column(Float)
    deadline_minutes: Mapped[float] = mapped_column(Float)  # minutes from request time (the working value)
    deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # departure deadline, absolute
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)  # owner (auth), if signed in
    battery_kwh: Mapped[float] = mapped_column(Float, default=40.0)
    max_charge_kw: Mapped[float] = mapped_column(Float, default=50.0)
    urgency: Mapped[float] = mapped_column(Float, default=0.0)
    priority_class: Mapped[str] = mapped_column(String(10), default="normal")
    recommended_station_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("stations.id"), nullable=True
    )
    recommendation_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("driver_requests.id"), nullable=True
    )
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    driver_name: Mapped[str] = mapped_column(String(60))
    priority_class: Mapped[str] = mapped_column(String(10))  # urgent | normal | flexible
    urgency: Mapped[float] = mapped_column(Float, default=0.0)
    soc_arrival: Mapped[float] = mapped_column(Float)
    soc_target: Mapped[float] = mapped_column(Float)
    battery_kwh: Mapped[float] = mapped_column(Float)
    arrival_at: Mapped[datetime] = mapped_column(DateTime)
    planned_start_at: Mapped[datetime] = mapped_column(DateTime)
    planned_end_at: Mapped[datetime] = mapped_column(DateTime)
    allocated_kw: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued|active|done|cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    station: Mapped[Station] = relationship(Station, lazy="joined")


class Session(Base):
    """A charging session: created when a reservation becomes active."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reservation_id: Mapped[int] = mapped_column(ForeignKey("reservations.id"))
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    port_index: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    allocated_kw: Mapped[float] = mapped_column(Float)
    energy_kwh: Mapped[float] = mapped_column(Float, default=0.0)


class ExplanationLog(Base):
    __tablename__ = "explanation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("driver_requests.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source: Mapped[str] = mapped_column(String(12))  # "llm" | "rules"
    model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    fallback_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)


class LiveLocation(Base):
    """Latest live position of a driver (one row per request, upserted by /driver/location/update)."""

    __tablename__ = "live_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("driver_requests.id"), unique=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    accuracy_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="gps")
    updates: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    etas_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # route ETA to every station


class Telemetry(Base):
    """One packet from an ESP32 (or the fake-ESP32 tool). Kept as history; latest is queried."""

    __tablename__ = "telemetry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    station_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stations.id"), nullable=True)
    voltage: Mapped[float] = mapped_column(Float)
    current: Mapped[float] = mapped_column(Float)
    power: Mapped[float] = mapped_column(Float)
    temperature: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    device_ts: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # device clock, if sent
    mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    # Milestone 3: honesty fields. `source` is what the packet itself declares ("real" | "simulated").
    source: Mapped[str] = mapped_column(String(12), default="real")
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    sensor_status: Mapped[str] = mapped_column(String(16), default="ok")
    event: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # e.g. "button_press"
    local_override: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)


class ControlState(Base):
    """Latest control command per station (simulated until hardware confirms it via telemetry)."""

    __tablename__ = "control_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), unique=True)
    command: Mapped[str] = mapped_column(String(24), default="NORMAL")
    reason: Mapped[str] = mapped_column(String(300), default="")
    power_fraction: Mapped[float] = mapped_column(Float, default=1.0)
    seq: Mapped[int] = mapped_column(Integer, default=1)  # increments on every command change
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ControlEvent(Base):
    """History of command changes (what the operator dashboard shows as the decision log)."""

    __tablename__ = "control_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    command: Mapped[str] = mapped_column(String(24))
    previous: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    reason: Mapped[str] = mapped_column(String(300))
    power_fraction: Mapped[float] = mapped_column(Float)


class Device(Base):
    """A device that talks to the backend: a real ESP32 or a simulator. One row per device_id.

    Rows created by the seed are *placeholders* (registered=False) until the device registers or sends telemetry.
    """

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    station_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stations.id"), nullable=True)
    device_mode: Mapped[str] = mapped_column(String(12), default="real")  # "real" | "simulated"
    registered: Mapped[bool] = mapped_column(Boolean, default=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    sensor_status: Mapped[str] = mapped_column(String(16), default="unknown")  # ok|missing|error|simulated|unknown
    firmware_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    telemetry_source: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    registered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # any contact
    last_telemetry_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_poll_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_sent_seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # last command delivered
    last_sent_command: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    last_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_ack_seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_ack_command: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    last_ack_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    last_ack_detail: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    last_ack_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    local_override: Mapped[bool] = mapped_column(Boolean, default=False)  # button held the output OFF
    button_count: Mapped[int] = mapped_column(Integer, default=0)
    last_button_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)  # stored lower-case
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(12), default="driver")  # "driver" | "operator"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class RefreshToken(Base):
    """One row per issued refresh token (only a hash of its id is stored). Rotated on every use."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256(jti)
    family: Mapped[str] = mapped_column(String(32), index=True)  # one sign-in = one family (reuse => revoke all)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)


class GeocodeCache(Base):
    """Cached Nominatim reverse-geocoding results (keyed by coordinates rounded to ~11 m)."""

    __tablename__ = "geocode_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(400))
    short_name: Mapped[str] = mapped_column(String(160))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
