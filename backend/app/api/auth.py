"""Auth API: sign up, sign in, refresh (rotating), sign out, current user."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session as DbSession

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas_auth import AuthOut, RefreshIn, SignInIn, SignUpIn, UserOut
from ..services import auth_service as auth
from ..services.auth_service import AuthError, Tokens

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE = "gp_refresh"
COOKIE_PATH = "/api/auth"  # the browser only sends the refresh cookie to the auth endpoints


def _fail(e: AuthError) -> HTTPException:
    return HTTPException(e.status, e.message, headers=e.headers or None)


def _set_refresh_cookie(response: Response, tokens: Tokens) -> None:
    response.set_cookie(
        REFRESH_COOKIE, tokens.refresh_token, max_age=settings.refresh_token_days * 86400, httponly=True,
        secure=settings.cookie_secure, samesite="lax", path=COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH, secure=settings.cookie_secure, httponly=True, samesite="lax")


def _auth_out(user: User, tokens: Tokens) -> AuthOut:
    return AuthOut(
        user=UserOut(id=user.id, email=user.email, name=user.name, role=user.role),  # type: ignore[arg-type]
        access_token=tokens.access_token, expires_in=tokens.expires_in,
    )


@router.post("/signup", response_model=AuthOut, status_code=201)
def signup(body: SignUpIn, request: Request, response: Response, db: DbSession = Depends(get_db)):
    """Create an account and sign in. Driver by default; operator needs the invite code."""
    try:
        user = auth.signup(db, body.name, body.email, body.password, body.role, body.operator_code)
    except AuthError as e:
        raise _fail(e)
    tokens = auth.start_session(db, user, request.headers.get("user-agent"))
    _set_refresh_cookie(response, tokens)
    return _auth_out(user, tokens)


@router.post("/signin", response_model=AuthOut)
def signin(body: SignInIn, request: Request, response: Response, db: DbSession = Depends(get_db)):
    key = f"{request.client.host if request.client else '?'}|{body.email}"
    try:
        auth.signin_limiter.check(key)
        try:
            user = auth.authenticate(db, body.email, body.password)
        except AuthError:
            auth.signin_limiter.failure(key)
            raise
    except AuthError as e:
        raise _fail(e)
    auth.signin_limiter.success(key)
    tokens = auth.start_session(db, user, request.headers.get("user-agent"))
    _set_refresh_cookie(response, tokens)
    return _auth_out(user, tokens)


@router.post("/refresh", response_model=AuthOut)
def refresh(
    request: Request, response: Response, body: Optional[RefreshIn] = None, db: DbSession = Depends(get_db)
):
    """Trade the refresh token (httpOnly cookie, or JSON body for non-browser clients) for a new pair."""
    token = request.cookies.get(REFRESH_COOKIE) or (body.refresh_token if body else None)
    if not token:
        raise HTTPException(401, "No refresh token")
    try:
        user, tokens = auth.rotate_session(db, token, request.headers.get("user-agent"))
    except AuthError as e:
        _clear_refresh_cookie(response)
        raise _fail(e)
    _set_refresh_cookie(response, tokens)
    return _auth_out(user, tokens)


@router.post("/logout")
def logout(request: Request, response: Response, body: Optional[RefreshIn] = None, db: DbSession = Depends(get_db)):
    """Revoke this session's refresh tokens and clear the cookie. Safe to call when already signed out."""
    auth.end_session(db, request.cookies.get(REFRESH_COOKIE) or (body.refresh_token if body else None))
    _clear_refresh_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut(id=user.id, email=user.email, name=user.name, role=user.role)  # type: ignore[arg-type]
