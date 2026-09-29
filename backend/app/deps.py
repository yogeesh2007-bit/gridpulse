"""FastAPI dependencies: current user, roles, device key, legacy-API guard."""
from __future__ import annotations

import hmac
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, WebSocketException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session as DbSession

from .config import settings
from .db import get_db
from .models import User
from .security import decode_token

_bearer = HTTPBearer(auto_error=False)
_UNAUTH = {"WWW-Authenticate": "Bearer"}


def user_from_access_token(db: DbSession, token: str) -> tuple[User, dict]:
    """Validate an access token and load its user. Raises HTTPException(401)."""
    try:
        payload = decode_token(token, "access")
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Access token expired", headers=_UNAUTH)
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid access token", headers=_UNAUTH)
    try:
        user = db.get(User, int(payload["sub"]))
    except (ValueError, TypeError):
        user = None
    if user is None or not user.is_active:
        raise HTTPException(401, "Account not found or disabled", headers=_UNAUTH)
    return user, payload


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer), db: DbSession = Depends(get_db)
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(401, "Not authenticated", headers=_UNAUTH)
    return user_from_access_token(db, creds.credentials)[0]


def require_role(*roles: str):
    """Dependency factory: the caller must be signed in and have one of `roles` (else 403)."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"This area is for {' / '.join(roles)} accounts")
        return user

    return dependency


require_driver = require_role("driver")
require_operator = require_role("operator")


def legacy_guard() -> None:
    """The pre-auth JSON API (dev tools, tests, scripts) only exists when LEGACY_API_ENABLED=true."""
    if not settings.legacy_api_enabled:
        raise HTTPException(404, "Not found")


def device_auth(x_device_key: Optional[str] = Header(None)) -> None:
    """Devices (ESP32 / simulator) authenticate with a shared key when DEVICE_API_KEY is configured."""
    expected = settings.device_api_key
    if not expected:
        return
    if not x_device_key or not hmac.compare_digest(x_device_key.encode(), expected.encode()):
        raise HTTPException(401, "Invalid or missing X-Device-Key", headers={"WWW-Authenticate": "DeviceKey"})
