"""Workspace settings: API keys (masked, testable) and the user's own details for PDFs."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import current_user, get_db, get_keybox, get_settings
from ..keys import SERVICES, test_key
from ..models import ApiKey, User, Workspace
from ..security import KeyBox
from ..settings import Settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class KeyState(BaseModel):
    service: str
    configured: bool
    last4: str | None = None
    test_ok: bool | None = None
    test_message: str | None = None
    tested_at: datetime | None = None


class Profile(BaseModel):
    name: str = Field(default="", max_length=200)
    company_id: str = Field(default="", max_length=40)  # IČO
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=320)


class SettingsOut(BaseModel):
    keys: dict[str, KeyState]
    profile: Profile
    pdf_language: str


class ProfileIn(Profile):
    pdf_language: str = Field(default="sk", pattern="^(sk|cs|en)$")


class KeyIn(BaseModel):
    key: str = Field(default="", max_length=500)


def _state(service: str, row: ApiKey | None) -> KeyState:
    if row is None:
        return KeyState(service=service, configured=False)
    return KeyState(
        service=service, configured=True, last4=row.last4, test_ok=row.test_ok, test_message=row.test_message, tested_at=row.tested_at
    )


def _check_service(service: str) -> None:
    if service not in SERVICES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown service")


async def _settings_out(db: AsyncSession, workspace: Workspace) -> SettingsOut:
    rows = {r.service: r for r in await db.scalars(select(ApiKey).where(ApiKey.workspace_id == workspace.id))}
    return SettingsOut(
        keys={s: _state(s, rows.get(s)) for s in SERVICES},
        profile=Profile(**{k: v for k, v in (workspace.profile or {}).items() if k in Profile.model_fields}),
        pdf_language=workspace.pdf_language,
    )


@router.get("", response_model=SettingsOut)
async def read_settings(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> SettingsOut:
    return await _settings_out(db, user.workspace)


@router.put("/profile", response_model=SettingsOut)
async def update_profile(body: ProfileIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> SettingsOut:
    workspace = await db.get(Workspace, user.workspace_id)
    workspace.profile = Profile(**body.model_dump(exclude={"pdf_language"})).model_dump()
    workspace.pdf_language = body.pdf_language
    await db.commit()
    return await _settings_out(db, workspace)


@router.put("/keys/{service}", response_model=KeyState)
async def save_key(
    service: str, body: KeyIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db), keybox: KeyBox = Depends(get_keybox)
) -> KeyState:
    _check_service(service)
    key = body.key.strip()
    where = (ApiKey.workspace_id == user.workspace_id, ApiKey.service == service)
    if not key:
        await db.execute(delete(ApiKey).where(*where))
        await db.commit()
        return KeyState(service=service, configured=False)
    row = await db.scalar(select(ApiKey).where(*where))
    if row is None:
        row = ApiKey(workspace_id=user.workspace_id, service=service, encrypted="", last4="")
        db.add(row)
    row.encrypted, row.last4 = keybox.encrypt(key), key[-4:]
    row.test_ok = row.test_message = row.tested_at = None
    await db.commit()
    return _state(service, row)


@router.post("/keys/{service}/test", response_model=KeyState)
async def test_saved_key(
    service: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    keybox: KeyBox = Depends(get_keybox),
    settings: Settings = Depends(get_settings),
) -> KeyState:
    _check_service(service)
    row = await db.scalar(select(ApiKey).where(ApiKey.workspace_id == user.workspace_id, ApiKey.service == service))
    key = keybox.decrypt(row.encrypted) if row else None
    if row is None or key is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Save a key first")
    row.test_ok, row.test_message = await test_key(service, key, settings.google_places_base)
    row.tested_at = datetime.now(UTC)
    await db.commit()
    return _state(service, row)
