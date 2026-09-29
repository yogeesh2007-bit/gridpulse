"""Pydantic request/response schemas."""
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    computed_field,
    field_validator,
    model_validator,
)


def _iso(d: datetime) -> str:
    return d.isoformat() + "Z" if d.tzinfo is None else d.isoformat()


# Naive-UTC datetimes are serialised with a trailing 'Z' so browsers parse them as UTC.
UTCDateTime = Annotated[datetime, PlainSerializer(_iso, return_type=str)]


class DriverRequestIn(BaseModel):
    """A driver's charging need. Accepts the problem-statement names (lat, lng, soc, target_soc, deadline) as well
    as the original ones (lon, soc_current, soc_target, deadline_minutes)."""

    model_config = ConfigDict(populate_by_name=True)

    driver_name: str = Field("Driver", max_length=60)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180, validation_alias=AliasChoices("lon", "lng"))
    soc_current: float = Field(ge=0, le=100, validation_alias=AliasChoices("soc_current", "soc"),
                               description="Current state of charge, %")
    soc_target: float = Field(ge=1, le=100, validation_alias=AliasChoices("soc_target", "target_soc"),
                              description="Target state of charge, %")
    deadline_minutes: float = Field(
        gt=0, le=1440, validation_alias=AliasChoices("deadline_minutes", "deadline"),
        description="Departure deadline: minutes from now, or an ISO-8601 departure time")
    battery_kwh: float = Field(40.0, gt=5, le=250)
    max_charge_kw: float = Field(50.0, gt=1, le=350, description="Max DC/AC power the vehicle accepts")
    location_source: Literal["gps", "manual"] = "gps"
    location_accuracy_m: Optional[float] = Field(None, ge=0)

    @field_validator("deadline_minutes", mode="before")
    @classmethod
    def _deadline_as_minutes_or_datetime(cls, v):
        """`deadline` may be a number of minutes from now, or an absolute departure time (ISO-8601 / datetime)."""
        if isinstance(v, bool):
            raise ValueError("deadline must be minutes from now or an ISO-8601 departure time")
        if isinstance(v, (int, float)):
            return v
        when = v
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                pass
            try:
                when = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("deadline must be minutes from now or an ISO-8601 departure time")
        if isinstance(when, datetime):
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            minutes = (when - datetime.now(timezone.utc)).total_seconds() / 60.0
            if minutes <= 0:
                raise ValueError("deadline is in the past")
            return round(minutes, 2)
        raise ValueError("deadline must be minutes from now or an ISO-8601 departure time")

    @model_validator(mode="after")
    def _target_above_current(self):
        if self.soc_target <= self.soc_current:
            raise ValueError("soc_target must be greater than soc_current")
        return self


class DriverRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: UTCDateTime
    driver_name: str
    lat: float
    lon: float
    location_source: str
    soc_current: float
    soc_target: float
    deadline_minutes: float
    deadline_at: Optional[UTCDateTime] = None
    battery_kwh: float
    max_charge_kw: float
    urgency: float
    priority_class: str
    recommended_station_id: Optional[int] = None

    @computed_field  # problem-statement spelling of `lon`
    @property
    def lng(self) -> float:
        return self.lon


class RecommendationIn(BaseModel):
    request_id: int


class ExplanationIn(BaseModel):
    request_id: int


class ExplanationOut(BaseModel):
    request_id: int
    text: str
    source: Literal["llm", "rules"]
    model: Optional[str] = None
    fallback_reason: Optional[str] = None
    latency_ms: int = 0


class ReservationCreate(BaseModel):
    request_id: int
    station_id: Optional[int] = Field(
        None, description="Defaults to the station recommended for this request"
    )


class LocationUpdateIn(BaseModel):
    """Live position of a driver who already has a charging request."""

    request_id: int
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: Optional[float] = Field(None, ge=0)
    source: Literal["gps", "manual"] = "gps"


class TelemetryIn(BaseModel):
    """One measurement packet from an ESP32 (INA219 readings). Units: volts, amps, watts, deg C."""

    device_id: str = Field(min_length=1, max_length=64)
    voltage: float = Field(ge=0, le=60)
    current: float = Field(ge=-30, le=30)
    power: float = Field(ge=-1000, le=2000)
    temperature: Optional[float] = Field(None, ge=-40, le=150)
    timestamp: Optional[datetime] = Field(None, description="Device clock (ISO 8601); server receive time is always recorded")
    mode: Optional[str] = Field(None, max_length=32, description="Command/mode the device is currently running")
    note: Optional[str] = Field(None, max_length=200)
    # Milestone 3 -- be explicit about what this packet is. Packets from before M3 carry none of these and are
    # treated as real, unflagged ESP32 packets.
    source: Literal["real", "simulated"] = Field("real", description="Who produced the packet")
    dry_run: bool = Field(False, description="Device is not physically driving its output pin")
    sensor_status: Literal["ok", "missing", "error", "simulated", "unknown"] = "ok"
    event: Optional[str] = Field(None, max_length=32, description='Edge event, e.g. "button_press"')
    local_override: Optional[bool] = Field(None, description="Button held the output OFF locally")


class DeviceRegisterIn(BaseModel):
    """Sent by a device on boot (and after reconnecting) so the backend knows what it is."""

    device_id: str = Field(min_length=1, max_length=64)
    device_mode: Literal["real", "simulated"]
    station_code: Optional[str] = Field(None, max_length=8, description="Bind to this station (e.g. 'A')")
    dry_run: bool = False
    firmware_version: Optional[str] = Field(None, max_length=40)
    sensor_status: Literal["ok", "missing", "error", "simulated", "unknown"] = "unknown"


class AckIn(BaseModel):
    """A device's acknowledgment of a control command it received."""

    seq: int = Field(ge=0, description="`seq` of the command being acknowledged")
    command: str = Field(min_length=1, max_length=24)
    status: Literal["applied", "rejected", "failsafe", "local_override"]
    detail: Optional[str] = Field(None, max_length=200)
    dry_run: Optional[bool] = None
    output_pct: Optional[float] = Field(None, ge=0, le=100)


class StationPatch(BaseModel):
    """Operator levers: change the grid connection limit / base load, or take a station offline."""

    site_limit_kw: Optional[float] = Field(None, gt=0, le=2000)
    base_load_kw: Optional[float] = Field(None, ge=0, le=2000)
    is_online: Optional[bool] = None
