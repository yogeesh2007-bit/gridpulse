"""Password hashing (scrypt, stdlib) and JWT helpers (PyJWT, HS256).

Two token types, told apart by the `type` claim so one can never be used as the other:
  * access  - short lived, sent as `Authorization: Bearer ...` (and as `?token=` for the WebSocket)
  * refresh - long lived, delivered in an httpOnly cookie, rotated on every use, only a hash of its `jti` is stored
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from .config import BACKEND_DIR, settings

ALGORITHM = "HS256"
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _DKLEN = 2**14, 8, 1, 32
_secret_cache: Optional[str] = None


# ---- passwords ---------------------------------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DKLEN)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(hash_b64)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# A valid hash of a random password: verifying against it burns the same CPU when the user does not exist,
# so response time does not reveal which emails are registered.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


# ---- JWT ----------------------------------------------------------------------------------------------------
def jwt_secret() -> str:
    """The configured secret, or (development only) a random one persisted next to the backend."""
    global _secret_cache
    if settings.jwt_secret:
        return settings.jwt_secret
    if _secret_cache is None:
        path = BACKEND_DIR / ".dev_jwt_secret"
        if path.exists():
            _secret_cache = path.read_text(encoding="utf-8").strip()
        else:
            _secret_cache = secrets.token_urlsafe(48)
            path.write_text(_secret_cache, encoding="utf-8")
    return _secret_cache


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    """Returns (token, lifetime in seconds)."""
    lifetime = settings.access_token_minutes * 60
    now = _now()
    payload = {
        "iss": settings.jwt_issuer, "sub": str(user_id), "role": role, "type": "access",
        "iat": now, "exp": now + timedelta(seconds=lifetime), "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, jwt_secret(), algorithm=ALGORITHM), int(lifetime)


def create_refresh_token(user_id: int, family: str) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at as naive UTC for the database)."""
    now = _now()
    exp = now + timedelta(days=settings.refresh_token_days)
    jti = uuid.uuid4().hex
    payload = {"iss": settings.jwt_issuer, "sub": str(user_id), "type": "refresh", "fam": family,
               "iat": now, "exp": exp, "jti": jti}
    return jwt.encode(payload, jwt_secret(), algorithm=ALGORITHM), jti, exp.replace(tzinfo=None)


def decode_token(token: str, expected_type: str) -> dict:
    """Verify signature, expiry and issuer, and that this is the right kind of token. Raises jwt.PyJWTError."""
    payload = jwt.decode(
        token, jwt_secret(), algorithms=[ALGORITHM], issuer=settings.jwt_issuer,
        options={"require": ["exp", "iat", "sub", "type"]},
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected a {expected_type} token")
    return payload


def hash_jti(jti: str) -> str:
    return hashlib.sha256(jti.encode()).hexdigest()
