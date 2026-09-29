"""Authentication: hashing, sign-up rules, roles, JWT access + rotating refresh tokens."""
import uuid

import jwt
import pytest

from app.config import settings
from app.db import SessionLocal
from app.models import RefreshToken, User
from app.security import hash_password, verify_password

PW = "correct-horse-9"


def new_email():
    return f"user-{uuid.uuid4().hex[:8]}@example.com"


def signup(client, **over):
    body = {"name": "Test User", "email": new_email(), "password": PW}
    body.update(over)
    return client.post("/api/auth/signup", json=body)


# ---- password hashing ----------------------------------------------------------------------------------
def test_password_hashing_is_salted_and_verifiable():
    a, b = hash_password(PW), hash_password(PW)
    assert a != b and a.startswith("scrypt$") and PW not in a
    assert verify_password(PW, a) and verify_password(PW, b)
    assert not verify_password("wrong-password", a)
    assert not verify_password(PW, "garbage") and not verify_password(PW, "scrypt$1$2$3$x$y")


# ---- sign up ------------------------------------------------------------------------------------------
def test_signup_creates_a_driver_and_returns_tokens(client):
    email = new_email()
    r = signup(client, email=email.upper(), name="  Ada  ")
    assert r.status_code == 201
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == settings.access_token_minutes * 60
    assert body["user"] == {"id": body["user"]["id"], "email": email, "name": "Ada", "role": "driver"}
    assert "password" not in r.text and "password_hash" not in r.text
    set_cookie = r.headers["set-cookie"].lower()
    assert "gp_refresh=" in set_cookie and "httponly" in set_cookie and "samesite=lax" in set_cookie
    assert "path=/api/auth" in set_cookie
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one()
        assert u.password_hash.startswith("scrypt$") and PW not in u.password_hash


def test_signup_validation(client):
    assert signup(client, password="short").status_code == 422
    assert signup(client, password="alllettersnodigits").status_code == 422
    assert signup(client, email="not-an-email").status_code == 422
    assert signup(client, name="").status_code == 422
    assert signup(client, role="admin").status_code == 422


def test_duplicate_email_is_rejected_case_insensitively(client):
    email = new_email()
    assert signup(client, email=email).status_code == 201
    assert signup(client, email=email.upper()).status_code == 409


def test_operator_signup_needs_the_invite_code(client):
    assert signup(client, role="operator").status_code == 403
    assert signup(client, role="operator", operator_code="nope").status_code == 403
    ok = signup(client, role="operator", operator_code=settings.effective_operator_code)
    assert ok.status_code == 201 and ok.json()["user"]["role"] == "operator"
    # supplying a code while asking for the driver role must not upgrade the account
    assert signup(client, role="driver", operator_code=settings.effective_operator_code).json()["user"]["role"] == "driver"


# ---- sign in / me ---------------------------------------------------------------------------------------
def test_signin_and_me(client):
    email = new_email()
    signup(client, email=email)
    client.cookies.clear()
    r = client.post("/api/auth/signin", json={"email": email.upper(), "password": PW})
    assert r.status_code == 200
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == email and me.json()["role"] == "driver"


def test_signin_failures_do_not_reveal_which_part_was_wrong(client):
    email = new_email()
    signup(client, email=email)
    wrong_pw = client.post("/api/auth/signin", json={"email": email, "password": "not-the-password1"})
    no_user = client.post("/api/auth/signin", json={"email": new_email(), "password": PW})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["detail"] == no_user.json()["detail"]


def test_seeded_demo_users_can_sign_in_in_development(client):
    for email, pw, role in (("operator@gridpulse.local", "Operator123!", "operator"),
                            ("driver@gridpulse.local", "Driver123!", "driver")):
        r = client.post("/api/auth/signin", json={"email": email, "password": pw})
        assert r.status_code == 200 and r.json()["user"]["role"] == role


def test_protected_route_needs_a_valid_access_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401
    good = signup(client).json()["access_token"]
    tampered = good[:-3] + ("aaa" if not good.endswith("aaa") else "bbb")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {tampered}"}).status_code == 401
    wrong_key = jwt.encode({"sub": "1", "type": "access", "iss": "gridpulse", "exp": 9999999999}, "another-secret" * 3, "HS256")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {wrong_key}"}).status_code == 401


def test_expired_access_token_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "access_token_minutes", -1)
    token = signup(client).json()["access_token"]
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and "expired" in r.json()["detail"].lower()


def test_refresh_token_cannot_be_used_as_an_access_token(client):
    client.cookies.clear()
    r = signup(client)
    refresh = client.cookies.get("gp_refresh")
    assert refresh
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {refresh}"}).status_code == 401
    # ...and an access token is not accepted where a refresh token is required
    client.cookies.clear()
    assert client.post("/api/auth/refresh", json={"refresh_token": r.json()["access_token"]}).status_code == 401


def test_inactive_user_is_locked_out(client):
    email = new_email()
    token = signup(client, email=email).json()["access_token"]
    with SessionLocal() as db:
        db.query(User).filter_by(email=email).one().is_active = False
        db.commit()
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.post("/api/auth/signin", json={"email": email, "password": PW}).status_code == 401


# ---- refresh rotation ------------------------------------------------------------------------------------
def test_refresh_rotates_the_token_and_returns_a_new_access_token(client):
    client.cookies.clear()
    signup(client)
    first = client.cookies.get("gp_refresh")
    r = client.post("/api/auth/refresh")  # cookie only, like the browser app
    assert r.status_code == 200 and r.json()["access_token"] and r.json()["user"]["role"] == "driver"
    second = client.cookies.get("gp_refresh")
    assert second and second != first
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200


def test_replaying_a_just_rotated_token_is_refused_but_keeps_the_session(client):
    """Two tabs refreshing at once must not sign the user out."""
    client.cookies.clear()
    signup(client)
    old = client.cookies.get("gp_refresh")
    assert client.post("/api/auth/refresh").status_code == 200
    newest = client.cookies.get("gp_refresh")
    client.cookies.clear()
    assert client.post("/api/auth/refresh", json={"refresh_token": old}).status_code == 401  # refused...
    assert client.post("/api/auth/refresh", json={"refresh_token": newest}).status_code == 200  # ...session intact


def test_reusing_a_rotated_refresh_token_revokes_the_whole_session(client, monkeypatch):
    monkeypatch.setattr(settings, "refresh_reuse_grace_s", 0)
    client.cookies.clear()
    signup(client)
    old = client.cookies.get("gp_refresh")
    assert client.post("/api/auth/refresh").status_code == 200  # rotates: `old` is now spent
    newest = client.cookies.get("gp_refresh")

    client.cookies.clear()  # an attacker replays the stolen, already-used token
    assert client.post("/api/auth/refresh", json={"refresh_token": old}).status_code == 401
    # the legitimate (newer) token from the same session is dead too
    assert client.post("/api/auth/refresh", json={"refresh_token": newest}).status_code == 401


def test_refresh_without_or_with_a_bad_token_is_401(client):
    client.cookies.clear()
    assert client.post("/api/auth/refresh").status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": "garbage"}).status_code == 401


def test_expired_refresh_token_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "refresh_token_days", -1)
    client.cookies.clear()
    signup(client)
    assert client.post("/api/auth/refresh").status_code == 401


def test_logout_revokes_the_refresh_token_and_clears_the_cookie(client):
    client.cookies.clear()
    signup(client)
    stolen = client.cookies.get("gp_refresh")
    r = client.post("/api/auth/logout")
    assert r.status_code == 200 and "gp_refresh=" in r.headers["set-cookie"].lower()
    assert client.cookies.get("gp_refresh") is None
    assert client.post("/api/auth/refresh", json={"refresh_token": stolen}).status_code == 401
    assert client.post("/api/auth/logout").status_code == 200  # idempotent


def test_only_hashes_of_refresh_tokens_are_stored(client):
    client.cookies.clear()
    signup(client)
    raw = client.cookies.get("gp_refresh")
    payload = jwt.decode(raw, options={"verify_signature": False})
    with SessionLocal() as db:
        rows = db.query(RefreshToken).all()
        assert rows and all(len(r.token_hash) == 64 for r in rows)
        assert not any(payload["jti"] == r.token_hash for r in rows)


# ---- brute-force protection ------------------------------------------------------------------------------
def test_signin_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "signin_max_attempts", 3)
    email = new_email()
    signup(client, email=email)
    codes = [client.post("/api/auth/signin", json={"email": email, "password": "wrong-password9"}).status_code
             for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
    blocked = client.post("/api/auth/signin", json={"email": email, "password": PW})  # even the right password waits
    assert blocked.status_code == 429 and "retry-after" in {k.lower() for k in blocked.headers}
