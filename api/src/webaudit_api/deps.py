"""Request dependencies: database session, current user, settings."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuthSession, User
from .security import SESSION_COOKIE, KeyBox, hash_token
from .settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_keybox(request: Request) -> KeyBox:
    return request.app.state.keybox


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        row = await db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        if row is not None and _aware(row.expires_at) > datetime.now(UTC):
            return row.user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue")


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes; they are stored in UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)
