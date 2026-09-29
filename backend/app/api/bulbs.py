"""Bulb/relay node API: device-facing (device key) and operator-facing (operator role)."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session as DbSession

from ..db import get_db, utcnow
from ..deps import device_auth, require_operator
from ..models import User
from ..services import bulbs, realtime
from ..services.state import iso

DeviceId = Path(..., pattern=bulbs.DEVICE_ID_PATTERN, description="lower-case letters, digits, - and _")


class BulbStatusIn(BaseModel):
    bulb_on: bool
    source: Literal["boot", "heartbeat", "manual_button_on", "manual_button_off", "manual_button", "state_change", "remote_command"] = "heartbeat"
    rssi: Optional[int] = None
    firmware: Optional[str] = None

    @model_validator(mode="after")
    def _consistent(self):
        bulbs.check_consistent(self.source, self.bulb_on)
        return self


class BulbCommandIn(BaseModel):
    bulb_on: bool


# ---- device-facing -------------------------------------------------------------------------------------------
device = APIRouter(prefix="/api/bulb", tags=["bulb-device"], dependencies=[Depends(device_auth)])


@device.post("/{device_id}/status")
def post_status(body: BulbStatusIn, device_id: str = DeviceId, db: DbSession = Depends(get_db)):
    """The node reports its state (boot, button press, remote command applied, heartbeat). Replies with the command."""
    d = bulbs.record_status(db, device_id, body.bulb_on, body.source, body.rssi, body.firmware, utcnow())
    realtime.poke()
    return {"accepted": True, "bulb_on": d.desired_on, "seq": d.command_seq}


@device.get("/{device_id}/command")
def get_command(device_id: str = DeviceId, db: DbSession = Depends(get_db)):
    """What the node should do. Compact JSON on purpose: the firmware matches the text "bulb_on":true."""
    d = bulbs.get_or_create(db, device_id)
    db.commit()
    return {"bulb_on": d.desired_on, "seq": d.command_seq, "commanded_by": d.commanded_by, "commanded_at": iso(d.commanded_at)}


# ---- operator-facing -----------------------------------------------------------------------------------------
operator = APIRouter(prefix="/api/operator/bulbs", tags=["bulbs"], dependencies=[Depends(require_operator)])


@operator.get("")
def list_bulbs(db: DbSession = Depends(get_db)):
    return bulbs.list_views(db, utcnow())


@operator.post("/{device_id}/command")
def send_command(body: BulbCommandIn, device_id: str = DeviceId, user: User = Depends(require_operator), db: DbSession = Depends(get_db)):
    """Turn the bulb ON/OFF remotely. The device applies it on its next poll (within ~3 s) and reports back."""
    now = utcnow()
    d = bulbs.set_command(db, device_id, body.bulb_on, user.name, now)
    realtime.poke()
    return bulbs.view(d, now)


@operator.get("/{device_id}/events")
def events(device_id: str = DeviceId, db: DbSession = Depends(get_db)):
    return bulbs.recent_events(db, device_id)


# ---- compatibility contract: /api/devices/{id}/... (same behaviour, alternative field names) --------------------------
class DeviceStateIn(BaseModel):
    bulb_on: bool
    source: Literal["boot", "heartbeat", "manual_button_on", "manual_button_off", "manual_button", "state_change", "remote_command"] = "heartbeat"
    rssi: Optional[int] = None
    firmware_version: Optional[str] = None

    @model_validator(mode="after")
    def _consistent(self):
        bulbs.check_consistent(self.source, self.bulb_on)
        return self


class DashboardCommandIn(BaseModel):
    bulb_on: bool
    source: Literal["dashboard"] = "dashboard"


devices_device = APIRouter(prefix="/api/devices", tags=["bulb-device"], dependencies=[Depends(device_auth)])
devices_operator = APIRouter(prefix="/api/devices", tags=["bulbs"], dependencies=[Depends(require_operator)])


@devices_device.post("/{device_id}/state")
def device_state(body: DeviceStateIn, device_id: str = DeviceId, db: DbSession = Depends(get_db)):
    """Device reports its state. Same as /api/bulb/{id}/status; `firmware_version` is accepted as the firmware field."""
    d = bulbs.record_status(db, device_id, body.bulb_on, body.source, body.rssi, body.firmware_version, utcnow())
    realtime.poke()
    return {"ok": True, "device_id": d.device_id, "bulb_on": bool(d.reported_on)}


@devices_device.get("/{device_id}/command")
def device_command(device_id: str = DeviceId, db: DbSession = Depends(get_db)):
    d = bulbs.get_or_create(db, device_id)
    db.commit()
    return {"bulb_on": d.desired_on, "command_id": str(d.command_seq)}


@devices_operator.post("/{device_id}/command")
def dashboard_command(body: DashboardCommandIn, device_id: str = DeviceId, user: User = Depends(require_operator), db: DbSession = Depends(get_db)):
    """Operator sets the desired state (requires an operator sign-in, not the device key)."""
    d = bulbs.set_command(db, device_id, body.bulb_on, user.name, utcnow())
    realtime.poke()
    return {"ok": True, "bulb_on": d.desired_on}
