"""Account and session logic: sign up, sign in, rotating refresh tokens, sign-in throttling, demo users."""
from __future__ import annotations

import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import jwt
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from ..config import settings
from ..db import utcnow
from ..models import RefreshToken, User
from ..security import (
    DUMMY_HASH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_jti,
    hash_password,
    verify_password,
)

INVALID_CREDENTIALS = "Invalid email or password"

DEMO_USERS = (
    ("operator@gridpulse.local", "Demo Operator", "Operator123!", "operator"),
    ("driver@gridpulse.local", "Demo Driver", "Driver123!", "driver"),
)


class AuthError(Exception):
    """Client-visible authentication/authorisation problem; the router turns it into an HTTP error."""

    def __init__(self, status: int, message: str, headers: Optional[dict] = None):
        super().__init__(message)
        self.status, self.message, self.headers = status, message, headers or {}


@dataclass
class Tokens:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_at: datetime


# ---- sign-in throttling ------------------------------------------------------------------------------------
class SignInLimiter:
    """In-memory sliding window of *failed* sign-ins per (client, email). Good enough for one process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}

    def _prune(self, key: str, now: float) -> list[float]:
        window = float(settings.signin_window_s)
        kept = [t for t in self._fails.get(key, []) if now - t < window]
        if kept:
            self._fails[key] = kept
        else:
            self._fails.pop(key, None)
        return kept

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            fails = self._prune(key, now)
            if len(fails) >= settings.signin_max_attempts:
                retry = max(1, int(settings.signin_window_s - (now - fails[0])))
                raise AuthError(429, "Too many sign-in attempts. Try again later.", {"Retry-After": str(retry)})

    def failure(self, key: str) -> None:
        with self._lock:
            self._fails.setdefault(key, []).append(time.monotonic())

    def success(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


signin_limiter = SignInLimiter()


# ---- accounts ------------------------------------------------------------------------------------------------
def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_user(db: DbSession, name: str, email: str, password: str, role: str = "driver") -> User:
    email = normalize_email(email)
    if db.scalar(select(User).where(User.email == email)):
        raise AuthError(409, "An account with this email already exists")
    user = User(email=email, name=name.strip(), password_hash=hash_password(password), role=role)
    db.add(user)
    db.commit()
    return user


def signup(db: DbSession, name: str, email: str, password: str, role: str, operator_code: Optional[str]) -> User:
    if role == "operator":
        expected = settings.effective_operator_code
        if not expected or not hmac.compare_digest((operator_code or "").encode(), expected.encode()):
            raise AuthError(403, "A valid operator invite code is required to register as an operator")
    return create_user(db, name, email, password, role)


def authenticate(db: DbSession, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    ok = verify_password(password, user.password_hash if user else DUMMY_HASH)  # same work either way
    if user is None or not ok or not user.is_active:
        raise AuthError(401, INVALID_CREDENTIALS)
    user.last_login_at = utcnow()
    db.commit()
    return user


def ensure_demo_users(db: DbSession) -> None:
    """Development convenience: one operator and one driver you can sign in with immediately."""
    for email, name, password, role in DEMO_USERS:
        if not db.scalar(select(User).where(User.email == email)):
            db.add(User(email=email, name=name, password_hash=hash_password(password), role=role))
    db.commit()


# ---- sessions (access + rotating refresh) -------------------------------------------------------------------
def _issue(db: DbSession, user: User, family: str, user_agent: Optional[str]) -> Tokens:
    access, lifetime = create_access_token(user.id, user.role)
    refresh, jti, expires_at = create_refresh_token(user.id, family)
    db.add(RefreshToken(user_id=user.id, token_hash=hash_jti(jti), family=family, expires_at=expires_at,
                        user_agent=(user_agent or "")[:200] or None))
    db.commit()
    return Tokens(access, lifetime, refresh, expires_at)


def start_session(db: DbSession, user: User, user_agent: Optional[str] = None) -> Tokens:
    """A fresh sign-in starts a new token family."""
    return _issue(db, user, secrets.token_hex(8), user_agent)


def _revoke_family(db: DbSession, family: str) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.family == family, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=utcnow()))
    db.commit()


def rotate_session(db: DbSession, refresh_token: str, user_agent: Optional[str] = None) -> tuple[User, Tokens]:
    """Exchange a refresh token for a new access + refresh pair. The presented token is spent.

    Presenting an already-spent token means it was stolen (or replayed), so the whole family is revoked -
    unless it was spent moments ago, which is what two browser tabs refreshing at once look like.
    """
    try:
        payload = decode_token(refresh_token, "refresh")
    except jwt.PyJWTError:
        raise AuthError(401, "Invalid or expired refresh token")
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_jti(payload["jti"])))
    if row is None:
        raise AuthError(401, "Invalid or expired refresh token")
    now = utcnow()
    if row.revoked_at is not None:
        if (now - row.revoked_at).total_seconds() > settings.refresh_reuse_grace_s:
            _revoke_family(db, row.family)
        raise AuthError(401, "Refresh token already used")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active or row.expires_at <= now:
        raise AuthError(401, "Invalid or expired refresh token")
    row.revoked_at = now
    db.commit()
    return user, _issue(db, user, row.family, user_agent)


def end_session(db: DbSession, refresh_token: Optional[str]) -> None:
    """Sign out: revoke the whole family of this refresh token. Never raises (logout is idempotent)."""
    if not refresh_token:
        return
    try:
        payload = decode_token(refresh_token, "refresh")
    except jwt.PyJWTError:
        return
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_jti(payload["jti"])))
    if row is not None:
        _revoke_family(db, row.family)
