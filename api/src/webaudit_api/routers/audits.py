"""Batch audits: create, list, detail, stop, live progress (SSE) and screenshots."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from webaudit import Config
from webaudit.report import check_label

from ..audit_service import AuditRequest, CreatedAudit, create_audit, parse_csv_bytes, parse_url_text
from ..deps import current_user, get_db, get_settings
from ..models import Audit, AuditEvent, AuditSite, User
from ..settings import Settings

router = APIRouter(prefix="/api/audits", tags=["audits"])
_CONFIG = Config.load()  # labels for problem ids (English operator UI)
MAX_CSV_BYTES = 2_000_000


class AuditOut(BaseModel):
    id: int
    project: str | None
    status: str
    cancel_requested: bool
    total: int
    done_count: int
    error_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SiteOut(BaseModel):
    id: int
    position: int
    input_url: str
    final_url: str | None
    company_name: str | None
    state: str
    state_reason: str | None
    step: str | None
    score: int | None
    category: str | None
    top_issue: str | None
    issues: int


class AuditDetail(AuditOut):
    sites: list[SiteOut]


class CreateResult(BaseModel):
    audit: AuditOut | None
    invalid: list[dict[str, str]]
    no_website_leads: int
    skipped_duplicates: int


class CreateFromText(BaseModel):
    project: str | None = Field(default=None, max_length=200)
    urls: str = Field(max_length=200_000)


def _site_out(site: AuditSite) -> SiteOut:
    issues = (site.result or {}).get("issues") or []
    return SiteOut(
        id=site.id,
        position=site.position,
        input_url=site.input_url,
        final_url=site.final_url,
        company_name=site.company.name if site.company else None,
        state=site.state,
        state_reason=site.state_reason,
        step=site.step,
        score=site.score,
        category=site.category,
        top_issue=check_label(_CONFIG, issues[0]["check_id"]) if issues else None,
        issues=len(issues),
    )


async def _own_audit(db: AsyncSession, user: User, audit_id: int) -> Audit:
    audit = await db.get(Audit, audit_id)
    if audit is None or audit.workspace_id != user.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Audit not found")
    return audit


def created_response(result: CreatedAudit) -> CreateResult:
    if result.audit is None and result.no_website_leads == 0:
        raise HTTPException(422, {"message": "No valid website addresses", "invalid": result.invalid})
    return CreateResult(
        audit=AuditOut.model_validate(result.audit, from_attributes=True) if result.audit else None,
        invalid=result.invalid,
        no_website_leads=result.no_website_leads,
        skipped_duplicates=result.skipped_duplicates,
    )


@router.post("", response_model=CreateResult, status_code=201)
async def create_from_text(
    body: CreateFromText, user: User = Depends(current_user), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> CreateResult:
    rows, invalid = parse_url_text(body.urls)
    request = AuditRequest(project=(body.project or "").strip() or None, rows=rows, invalid=invalid)
    return created_response(await create_audit(db, user.workspace_id, request, max_urls=settings.max_urls_per_audit))


@router.post("/csv", response_model=CreateResult, status_code=201)
async def create_from_csv(
    file: UploadFile = File(...),
    project: str | None = Form(default=None),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CreateResult:
    data = await file.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "CSV file is too large (max 2 MB)")
    try:
        rows, invalid = parse_csv_bytes(data)
    except ValueError as exc:
        raise HTTPException(422, {"message": str(exc), "invalid": []}) from exc
    request = AuditRequest(project=(project or "").strip() or None, rows=rows, invalid=invalid)
    return created_response(await create_audit(db, user.workspace_id, request, max_urls=settings.max_urls_per_audit))


@router.get("", response_model=list[AuditOut])
async def list_audits(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> list[AuditOut]:
    rows = await db.scalars(select(Audit).where(Audit.workspace_id == user.workspace_id).order_by(Audit.id.desc()).limit(200))
    return [AuditOut.model_validate(a, from_attributes=True) for a in rows]


@router.get("/stats/summary")
async def audit_summary(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    """Small counters for the empty dashboard and the sidebar (full dashboard in stage 3)."""
    audits = await db.scalar(select(func.count(Audit.id)).where(Audit.workspace_id == user.workspace_id))
    sites = await db.scalar(
        select(func.count(AuditSite.id)).join(Audit).where(Audit.workspace_id == user.workspace_id, AuditSite.score.is_not(None))
    )
    return {"audits": audits or 0, "scored_sites": sites or 0}


@router.get("/{audit_id}", response_model=AuditDetail)
async def get_audit(audit_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> AuditDetail:
    audit = await _own_audit(db, user, audit_id)
    sites = await db.scalars(select(AuditSite).where(AuditSite.audit_id == audit.id).order_by(AuditSite.position))
    base = AuditOut.model_validate(audit, from_attributes=True).model_dump()
    return AuditDetail(**base, sites=[_site_out(s) for s in sites])


@router.get("/{audit_id}/sites/{site_id}")
async def get_site_result(
    audit_id: int, site_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _own_audit(db, user, audit_id)
    site = await db.get(AuditSite, site_id)
    if site is None or site.audit_id != audit_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Website not found")
    result = site.result or {}
    summaries = {c["id"]: c.get("summary", "") for c in result.get("checks", [])}
    issues = [
        {**issue, "label": check_label(_CONFIG, issue["check_id"]), "summary": summaries.get(issue["check_id"], "")}
        for issue in result.get("issues", [])
    ]
    return {"site": _site_out(site).model_dump(), "issues": issues, "result": result}


@router.get("/{audit_id}/sites/{site_id}/screenshots/{name}")
async def get_screenshot(
    audit_id: int,
    site_id: int,
    name: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    await _own_audit(db, user, audit_id)
    site = await db.get(AuditSite, site_id)
    relative = ((site.result or {}).get("screenshots") or {}).get(name) if site and site.audit_id == audit_id else None
    if not relative:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Screenshot not found")
    root = settings.data_dir.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Screenshot not found")
    return FileResponse(Path(path), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/{audit_id}/stop", response_model=AuditOut)
async def stop_audit(audit_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> AuditOut:
    audit = await _own_audit(db, user, audit_id)
    if audit.status == "queued":
        audit.status = "cancelled"
        db.add(
            AuditEvent(
                audit_id=audit.id, kind="audit_done", level="warn", message="Audit stopped before it started", data={"status": "cancelled"}
            )
        )
    elif audit.status == "running":
        audit.cancel_requested = True
    await db.commit()
    return AuditOut.model_validate(audit, from_attributes=True)


@router.get("/{audit_id}/events")
async def stream_events(
    audit_id: int,
    request: Request,
    after: int = 0,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Server-sent events: the whole history first, then live updates until the audit ends."""
    await _own_audit(db, user, audit_id)
    last_id = int(request.headers.get("last-event-id") or after or 0)
    sessionmaker = request.app.state.sessionmaker

    async def generate() -> AsyncIterator[str]:
        nonlocal last_id
        idle = 0.0
        yield "retry: 2000\n\n"
        while not await request.is_disconnected():
            async with sessionmaker() as session:
                events = list(
                    await session.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.audit_id == audit_id, AuditEvent.id > last_id)
                        .order_by(AuditEvent.id)
                        .limit(500)
                    )
                )
                finished = await session.scalar(select(Audit.status).where(Audit.id == audit_id)) in ("done", "cancelled", "failed")
            for event in events:
                last_id = event.id
                payload = {
                    "kind": event.kind,
                    "level": event.level,
                    "message": event.message,
                    "time": event.created_at.isoformat(),
                    **event.data,
                }
                yield f"id: {event.id}\nevent: {event.kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if finished and not events:
                yield "event: end\ndata: {}\n\n"
                return
            if events:
                idle = 0.0
                continue
            idle += 0.5
            if idle >= 15:
                idle = 0.0
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
