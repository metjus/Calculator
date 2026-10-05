"""Sign up, sign in, sign out. Sessions are opaque tokens in an httpOnly cookie."""

from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import current_user, get_db, get_settings
from ..models import AuthSession, User, Workspace
from ..security import MIN_PASSWORD_LENGTH, SESSION_COOKIE, hash_password, hash_token, new_session_token, verify_password
from ..settings import Settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Tiny in-process brake on password guessing (per e-mail and per client IP).
_FAILURES: dict[str, deque[float]] = defaultdict(deque)
_MAX_FAILURES, _WINDOW_S = 8, 15 * 60


def _too_many(key: str) -> bool:
    attempts = _FAILURES[key]
    while attempts and attempts[0] < time.monotonic() - _WINDOW_S:
        attempts.popleft()
    return len(attempts) >= _MAX_FAILURES


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class SignUp(Credentials):
    workspace_name: str | None = Field(default=None, max_length=200)


LOCAL_EMAIL = "local@webaudit.invalid"  # the desktop app's only user; .invalid never resolves


class Me(BaseModel):
    email: str
    workspace_id: int
    workspace_name: str
    local: bool = False  # desktop app: no sign-out, a Quit button instead


def _me(user: User, settings: Settings | None = None) -> Me:
    local = bool(settings and settings.local_mode)
    return Me(email=user.email, workspace_id=user.workspace_id, workspace_name=user.workspace.name, local=local)


async def _start_session(response: Response, db: AsyncSession, user: User, settings: Settings) -> None:
    token, token_hash = new_session_token()
    db.add(AuthSession(token_hash=token_hash, user_id=user.id, expires_at=datetime.now(UTC) + timedelta(days=settings.session_days)))
    await db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _normalize_email(email: str) -> str:
    email = email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(422, "Enter a valid e-mail address")
    return email


@router.post("/signup", response_model=Me, status_code=201)
async def signup(body: SignUp, response: Response, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> Me:
    if not settings.signup_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-up is closed")
    email = _normalize_email(body.email)
    if len(body.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(422, f"Use at least {MIN_PASSWORD_LENGTH} characters for the password")
    if await db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this e-mail already exists")
    workspace = Workspace(name=(body.workspace_name or "").strip() or "My workspace", profile={})
    db.add(workspace)
    await db.flush()
    user = User(email=email, password_hash=hash_password(body.password), workspace_id=workspace.id)
    db.add(user)
    await db.flush()
    user.workspace = workspace
    await _start_session(response, db, user, settings)
    return _me(user)


@router.post("/login", response_model=Me)
async def login(
    body: Credentials,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Me:
    email = body.email.strip().lower()
    keys = [f"email:{email}", f"ip:{request.client.host if request.client else '?'}"]
    if any(_too_many(k) for k in keys):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again in a few minutes.")
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(user.password_hash, body.password):
        for k in keys:
            _FAILURES[k].append(time.monotonic())
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong e-mail or password")
    await _start_session(response, db, user, settings)
    return _me(user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=Me)
async def me(user: User = Depends(current_user), settings: Settings = Depends(get_settings)) -> Me:
    return _me(user, settings)


@router.get("/local", include_in_schema=False)
async def local_sign_in(
    token: str = Query(..., max_length=200), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> Response:
    """Desktop app: the launcher opens this URL with its per-launch token; no password exists."""
    if not settings.local_mode or not settings.local_token or not hmac.compare_digest(token, settings.local_token):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    user = await db.scalar(select(User).where(User.email == LOCAL_EMAIL))
    if user is None:
        workspace = Workspace(name="My workspace", profile={})
        db.add(workspace)
        await db.flush()
        user = User(email=LOCAL_EMAIL, password_hash=hash_password(secrets.token_urlsafe(32)), workspace_id=workspace.id)
        db.add(user)
        await db.flush()
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    await _start_session(response, db, user, settings)
    return response
