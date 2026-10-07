"""Batch audits: create, list, detail, stop, live progress (SSE), screenshots and the Claude Code export."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask
from webaudit import Config, ScanResult, SiteState, claude_export
from webaudit.ai_review import AIReviewError
from webaudit.dom import bare_host
from webaudit.pdf import OfferOption, build_html, safe_pdf_name
from webaudit.report import check_label

from ..ai_service import apply_review, estimate, review_view, reviewer_for
from ..audit_service import AuditRequest, CreatedAudit, create_audit, parse_csv_bytes, parse_url_text
from ..deps import current_user, get_db, get_keybox, get_settings
from ..keys import get_key
from ..models import Audit, AuditEvent, AuditSite, CompetitorScan, User, Workspace
from ..pdf_service import LANGUAGES, content_for, make_pdf, offer_defaults, preview
from ..security import KeyBox
from ..settings import Settings
from ..site_view import areas, comparison, facts, page_contents, problems

router = APIRouter(prefix="/api/audits", tags=["audits"])
_CONFIG = Config.load()  # labels for problem ids (English operator UI)
MAX_CSV_BYTES = 2_000_000
MAX_COMPETITORS = 5  # per website; each one is a full scan


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


class QueueOut(BaseModel):
    """Why a queued audit has not started yet (the UI used to just say "waiting for a free worker")."""

    ahead: int  # audits queued before this one
    running_audit_id: int | None  # the audit being scanned right now, when it is this workspace's
    worker: str  # running | starting | stopped | unknown (a worker in another process cannot be asked)
    worker_error: str | None


class AuditDetail(AuditOut):
    sites: list[SiteOut]
    queue: QueueOut | None = None  # only while this audit waits


class CreateResult(BaseModel):
    audit: AuditOut | None
    invalid: list[dict[str, str]]
    no_website_leads: int
    skipped_duplicates: int


class OfferIn(BaseModel):
    title: str = Field(default="", max_length=120)
    price: str = Field(default="", max_length=40)  # typed by hand; no per-problem price list by design
    description: str = Field(default="", max_length=400)
    recommended: bool = False


class PdfIn(BaseModel):
    """Everything the operator decided in the preview."""

    language: str = Field(default="sk", pattern="^(sk|cs|en)$")
    client_name: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=1500)
    include: list[str] | None = None  # check ids, in the order they should be printed
    offer: list[OfferIn] = Field(default_factory=list, max_length=3)


class CreateFromText(BaseModel):
    project: str | None = Field(default=None, max_length=200)
    urls: str = Field(max_length=200_000)
    ai_review: bool = False  # Claude's design review for every website (needs a Claude key)
    competitors: str = Field(default="", max_length=20_000)  # compared with every website in the audit


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


async def _own_site(db: AsyncSession, user: User, audit_id: int, site_id: int) -> AuditSite:
    await _own_audit(db, user, audit_id)
    site = await db.get(AuditSite, site_id)
    if site is None or site.audit_id != audit_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Website not found")
    return site


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


async def _options(db: AsyncSession, keybox: KeyBox, user: User, ai_review: bool) -> dict[str, Any]:
    if ai_review and not await get_key(db, keybox, user.workspace_id, "claude"):
        raise HTTPException(422, {"message": "Add a Claude API key in Settings to evaluate design with Claude", "invalid": []})
    return {"ai_review": ai_review}


def _add_competitors(request: AuditRequest, text: str) -> None:
    """Competitors typed for the whole audit join the ones each row already has (CSV column)."""
    common, invalid = parse_url_text(text)
    request.invalid += [{**item, "error": f"competitor: {item['error']}"} for item in invalid]
    for row in request.rows:
        own = bare_host(row.url) if row.url else None
        merged = [*row.competitors, *(c.url for c in common if c.url)]
        row.competitors = [url for url in dict.fromkeys(merged) if bare_host(url) != own][:MAX_COMPETITORS]


@router.post("", response_model=CreateResult, status_code=201)
async def create_from_text(
    body: CreateFromText,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    keybox: KeyBox = Depends(get_keybox),
    settings: Settings = Depends(get_settings),
) -> CreateResult:
    rows, invalid = parse_url_text(body.urls)
    request = AuditRequest(project=(body.project or "").strip() or None, rows=rows, invalid=invalid)
    _add_competitors(request, body.competitors)
    options = await _options(db, keybox, user, body.ai_review)
    return created_response(await create_audit(db, user.workspace_id, request, max_urls=settings.max_urls_per_audit, options=options))


@router.post("/csv", response_model=CreateResult, status_code=201)
async def create_from_csv(
    file: UploadFile = File(...),
    project: str | None = Form(default=None),
    ai_review: bool = Form(default=False),
    competitors: str = Form(default="", max_length=20_000),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    keybox: KeyBox = Depends(get_keybox),
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
    _add_competitors(request, competitors)
    options = await _options(db, keybox, user, ai_review)
    return created_response(await create_audit(db, user.workspace_id, request, max_urls=settings.max_urls_per_audit, options=options))


@router.get("", response_model=list[AuditOut])
async def list_audits(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> list[AuditOut]:
    rows = await db.scalars(select(Audit).where(Audit.workspace_id == user.workspace_id).order_by(Audit.id.desc()).limit(200))
    return [AuditOut.model_validate(a, from_attributes=True) for a in rows]


@router.get("/stats/summary")
async def audit_summary(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    """Small counters for the empty dashboard and the sidebar."""
    audits = await db.scalar(select(func.count(Audit.id)).where(Audit.workspace_id == user.workspace_id))
    sites = await db.scalar(
        select(func.count(AuditSite.id)).join(Audit).where(Audit.workspace_id == user.workspace_id, AuditSite.score.is_not(None))
    )
    return {"audits": audits or 0, "scored_sites": sites or 0}


@router.get("/ai-estimate")
async def ai_estimate(
    sites: int = Query(default=1, ge=0, le=10_000),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    keybox: KeyBox = Depends(get_keybox),
) -> dict[str, Any]:
    """Whether a Claude key is set and what reviewing ``sites`` websites may cost."""
    return {"configured": bool(await get_key(db, keybox, user.workspace_id, "claude")), **estimate(sites)}


async def _queue(request: Request, db: AsyncSession, user: User, audit: Audit) -> QueueOut | None:
    """What a waiting audit is waiting for: audits before it, or a worker that is not running."""
    if audit.status != "queued":
        return None
    ahead = await db.scalar(select(func.count(Audit.id)).where(Audit.status == "queued", Audit.id < audit.id))
    running = await db.scalar(
        select(Audit.id).where(Audit.status == "running", Audit.workspace_id == user.workspace_id).order_by(Audit.id).limit(1)
    )
    worker = getattr(request.app.state, "worker", None)  # None: the worker is a separate process
    return QueueOut(
        ahead=ahead or 0,
        running_audit_id=running,
        worker=worker.state if worker is not None else "unknown",
        worker_error=getattr(worker, "last_error", None),
    )


@router.get("/{audit_id}", response_model=AuditDetail)
async def get_audit(audit_id: int, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> AuditDetail:
    audit = await _own_audit(db, user, audit_id)
    sites = await db.scalars(select(AuditSite).where(AuditSite.audit_id == audit.id).order_by(AuditSite.position))
    base = AuditOut.model_validate(audit, from_attributes=True).model_dump()
    return AuditDetail(**base, sites=[_site_out(s) for s in sites], queue=await _queue(request, db, user, audit))


@router.get("/{audit_id}/sites/{site_id}")
async def get_site_result(
    audit_id: int,
    site_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    keybox: KeyBox = Depends(get_keybox),
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
    history = []
    if site.company_id:
        earlier = await db.scalars(
            select(AuditSite)
            .where(AuditSite.company_id == site.company_id, AuditSite.finished_at.is_not(None))
            .order_by(AuditSite.finished_at.desc())
            .limit(20)
        )
        history = [
            {
                "site_id": s.id,
                "audit_id": s.audit_id,
                "state": s.state,
                "score": s.score,
                "category": s.category,
                "finished_at": s.finished_at,
            }
            for s in earlier
        ]
    audit = await db.get(Audit, audit_id)
    company = site.company
    return {
        "site": _site_out(site).model_dump(),
        "audit": {"id": audit_id, "project": audit.project if audit else None},
        "company": {"id": company.id, "name": company.name, "manual_check": company.manual_check} if company else None,
        "finished_at": site.finished_at,
        "issues": issues,
        "problems": problems(result, _CONFIG),
        "areas": areas(result, _CONFIG) if result.get("score") else [],
        "facts": facts(result) if result.get("checks") else [],
        "contents": page_contents(result),
        "history": history,
        "ai_review": review_view(result),
        "ai": {"configured": bool(await get_key(db, keybox, user.workspace_id, "claude")), **estimate(1)},
        "comparison": {"self": comparison(result), **await _competitors(db, site)},
        "result": result,
    }


async def _competitors(db: AsyncSession, site: AuditSite) -> dict[str, Any]:
    """The listed competitors' scans, or else the best other websites of the same audit."""
    if site.competitors:
        scans = {c.url: c for c in await db.scalars(select(CompetitorScan).where(CompetitorScan.audit_id == site.audit_id))}
        rows = []
        for url in site.competitors:
            scan = scans.get(url)
            rows.append(
                {
                    "id": scan.id if scan else None,
                    "domain": bare_host(scan.final_url if scan and scan.final_url else url) or url,
                    "url": (scan.final_url if scan else None) or url,
                    "state": scan.state if scan else "pending",
                    "reason": scan.state_reason if scan else "Not scanned yet",
                    "score": scan.score if scan else None,
                    "category": scan.category if scan else None,
                    "screenshots": sorted(((scan.result or {}).get("screenshots") or {}) if scan else {}),
                    **comparison(scan.result if scan else None),
                }
            )
        return {"source": "competitors", "rows": rows}
    peers = await db.scalars(
        select(AuditSite)
        .where(AuditSite.audit_id == site.audit_id, AuditSite.id != site.id, AuditSite.score.is_not(None))
        .order_by(AuditSite.score.desc())
        .limit(3)
    )
    return {
        "source": "audit",
        "rows": [
            {
                "site_id": peer.id,
                "domain": bare_host(peer.final_url or peer.input_url) or peer.input_url,
                "url": peer.final_url or peer.input_url,
                "state": peer.state,
                "score": peer.score,
                "category": peer.category,
                **comparison(peer.result),
            }
            for peer in peers
        ],
    }


async def _pdf_content(
    db: AsyncSession, user: User, settings: Settings, audit_id: int, site_id: int, language: str
) -> tuple[Any, AuditSite, Workspace]:
    site = await _own_site(db, user, audit_id, site_id)
    if not (site.result or {}).get("score"):
        raise HTTPException(422, "This website has no score, so there is nothing to put in a report")
    workspace = await db.get(Workspace, user.workspace_id)
    rows = (await _competitors(db, site))["rows"]
    name = site.company.name if site.company else None
    content = content_for(site, workspace, settings, _CONFIG, language=language, competitors=rows, client_name=name)
    return content, site, workspace


@router.get("/{audit_id}/sites/{site_id}/pdf-preview")
async def pdf_preview(
    audit_id: int,
    site_id: int,
    lang: str = Query(default=""),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """What the client PDF would say, before the operator edits it."""
    workspace = await db.get(Workspace, user.workspace_id)
    language = lang if lang in LANGUAGES else workspace.pdf_language
    content, _site, workspace = await _pdf_content(db, user, settings, audit_id, site_id, language)
    return preview(content, _CONFIG, workspace)


def _apply(content: Any, body: PdfIn, config: Config, workspace: Workspace) -> None:
    """The operator's choices from the preview, over the defaults."""
    if body.client_name is not None:
        content.client_name = body.client_name.strip() or content.client_name
    if body.summary is not None:
        content.summary = body.summary.strip()
    if body.include is not None:
        content.include = body.include
    content.offer = (
        [OfferOption(**option.model_dump()) for option in body.offer] if body.offer else offer_defaults(content, config, workspace)
    )


@router.post("/{audit_id}/sites/{site_id}/pdf-html", include_in_schema=False)
async def pdf_html(
    audit_id: int,
    site_id: int,
    body: PdfIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """The report as HTML - the same document the PDF is rendered from.

    The preview screen shows this in an iframe, so editing a price updates it in milliseconds
    instead of launching Chromium. The page carries only ``data:`` URIs and no script, and the
    policy below keeps it that way even if that ever changed.
    """
    content, _site, workspace = await _pdf_content(db, user, settings, audit_id, site_id, body.language)
    _apply(content, body, _CONFIG, workspace)
    return Response(
        build_html(content, _CONFIG),
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:",
            "Cache-Control": "no-store",
        },
    )


@router.post("/{audit_id}/sites/{site_id}/pdf")
async def pdf_export(
    audit_id: int,
    site_id: int,
    body: PdfIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """The finished PDF. The three options are also kept as the defaults for the next export."""
    content, _site, workspace = await _pdf_content(db, user, settings, audit_id, site_id, body.language)
    _apply(content, body, _CONFIG, workspace)
    pdf = await make_pdf(content, _CONFIG)
    workspace.pdf_offer = [vars(option) for option in content.offer]
    workspace.pdf_language = content.language
    await db.commit()
    name = safe_pdf_name(content)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/{audit_id}/sites/{site_id}/ai-review")
async def review_site(
    audit_id: int,
    site_id: int,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    keybox: KeyBox = Depends(get_keybox),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Claude's design review for one already scanned website, from its stored screenshots; the score is recomputed."""
    await _own_audit(db, user, audit_id)
    site = await db.get(AuditSite, site_id)
    if site is None or site.audit_id != audit_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Website not found")
    if site.state != "ok" or not site.result:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only scored websites can be reviewed")
    key = await get_key(db, keybox, user.workspace_id, "claude")
    if not key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add a Claude API key in Settings first")
    read = _file_reader(settings)
    shots = site.result.get("screenshots") or {}
    desktop = read(shots["desktop"]) if shots.get("desktop") else None
    if desktop is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This website has no screenshots; audit it again first")
    mobile = read(shots["mobile"]) if shots.get("mobile") else None
    workspace = await db.get(Workspace, user.workspace_id)
    try:
        review = await reviewer_for(request.app.state, key)(desktop, mobile, site.final_url or site.input_url, workspace.pdf_language)
    except AIReviewError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    updated = apply_review(site.result, review, None, await _workspace_config(db, user))
    site.result = updated
    site.score, site.category = updated["score"]["total"], updated["score"]["category"]
    await db.commit()
    return await get_site_result(audit_id, site_id, user, db, keybox)


@router.get("/{audit_id}/competitors/{competitor_id}/screenshots/{name}")
async def get_competitor_screenshot(
    audit_id: int,
    competitor_id: int,
    name: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    await _own_audit(db, user, audit_id)
    scan = await db.get(CompetitorScan, competitor_id)
    relative = ((scan.result or {}).get("screenshots") or {}).get(name) if scan and scan.audit_id == audit_id else None
    return _screenshot_response(settings, relative)


def _screenshot_response(settings: Settings, relative: str | None) -> FileResponse:
    if not relative:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Screenshot not found")
    root = settings.data_dir.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Screenshot not found")
    return FileResponse(Path(path), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


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
    return _screenshot_response(settings, relative)


def _file_reader(settings: Settings) -> Callable[[str], bytes | None]:
    """Read stored screenshots/snapshots, confined to the data folder."""
    root = settings.data_dir.resolve()

    def read(relative: str) -> bytes | None:
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return None
        return path.read_bytes()

    return read


async def _workspace_config(db: AsyncSession, user: User) -> Config:
    workspace = await db.get(Workspace, user.workspace_id)
    return Config.load(overrides=workspace.config_overrides or None)


def _slug(text: str) -> str:
    return "-".join("".join(ch if ch.isalnum() else " " for ch in text.lower()).split())[:60]


async def _zip_response(files: Any, root: str) -> FileResponse:
    """Write the ZIP to a temporary file (batches can be large) and stream it."""

    def build() -> str:
        handle, path = tempfile.mkstemp(prefix="webaudit-export-", suffix=".zip")
        try:
            with os.fdopen(handle, "wb") as target:
                claude_export.write_zip(files() if callable(files) else files, root, target)
        except BaseException:
            os.unlink(path)
            raise
        return path

    path = await asyncio.to_thread(build)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"{root}.zip",
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(os.unlink, path),
    )


@router.get("/{audit_id}/sites/{site_id}/claude-export")
async def export_site(
    audit_id: int,
    site_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """ZIP for Claude Code: what the page contains and where each problem is (see webaudit.claude_export)."""
    await _own_audit(db, user, audit_id)
    site = await db.get(AuditSite, site_id)
    if site is None or site.audit_id != audit_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Website not found")
    if site.state != SiteState.OK.value or not site.result:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only scored websites can be exported")
    result = ScanResult.model_validate(site.result)
    config = await _workspace_config(db, user)
    files = await asyncio.to_thread(claude_export.site_files, result, config, _file_reader(settings))
    return await _zip_response(files, claude_export.bundle_name(result))


@router.get("/{audit_id}/claude-export")
async def export_audit(
    audit_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """One ZIP with an index and a folder per scored website."""
    audit = await _own_audit(db, user, audit_id)
    if audit.status in ("queued", "running"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Wait until the audit has finished")
    sites = list(await db.scalars(select(AuditSite).where(AuditSite.audit_id == audit.id).order_by(AuditSite.position)))
    results: list[ScanResult] = []
    for site in sites:
        if site.result:
            results.append(ScanResult.model_validate(site.result))
        elif site.state in {s.value for s in SiteState}:
            results.append(ScanResult(input_url=site.input_url, state=SiteState(site.state), state_reason=site.state_reason))
    if not any(r.state is SiteState.OK and r.score for r in results):
        raise HTTPException(status.HTTP_409_CONFLICT, "No website in this audit was scored")
    config = await _workspace_config(db, user)
    title = audit.project or f"Audit #{audit.id}"
    root = f"webaudit-{_slug(audit.project) if audit.project else f'audit-{audit.id}'}-{audit.created_at:%Y-%m-%d}"
    reader = _file_reader(settings)
    return await _zip_response(lambda: claude_export.iter_audit_files(results, config, reader, title=title), root)


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
