"""Companies list (the CRM in stage 7 extends this with statuses, history and reminders)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import current_user, get_db
from ..models import Audit, AuditSite, Company, User

router = APIRouter(prefix="/api/companies", tags=["companies"])


class CompanyOut(BaseModel):
    id: int
    name: str | None
    url: str | None
    domain: str | None
    project: str | None
    has_website: bool
    do_not_contact: bool
    manual_check: str | None = None  # "contact" | "skip": decision after a manual check
    source: str  # "google" | "osm" | "manual"
    created_at: datetime
    last_score: int | None = None
    last_audit_id: int | None = None


@router.get("", response_model=list[CompanyOut])
async def list_companies(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> list[CompanyOut]:
    latest = (
        select(AuditSite.company_id, func.max(AuditSite.id).label("site_id"))
        .join(Audit)
        .where(Audit.workspace_id == user.workspace_id, AuditSite.score.is_not(None))
        .group_by(AuditSite.company_id)
        .subquery()
    )
    rows = await db.execute(
        select(Company, AuditSite.score, AuditSite.audit_id)
        .outerjoin(latest, latest.c.company_id == Company.id)
        .outerjoin(AuditSite, AuditSite.id == latest.c.site_id)
        .where(Company.workspace_id == user.workspace_id)
        .order_by(Company.created_at.desc())
        .limit(1000)
    )
    out = []
    for company, score, audit_id in rows:
        out.append(
            CompanyOut(
                id=company.id,
                name=company.name,
                url=company.url,
                domain=company.domain,
                project=company.project,
                has_website=company.has_website,
                do_not_contact=company.do_not_contact,
                manual_check=company.manual_check,
                source="google" if company.place_id else ("osm" if company.osm_id else "manual"),
                created_at=company.created_at,
                last_score=score,
                last_audit_id=audit_id,
            )
        )
    return out


class ManualCheck(BaseModel):
    decision: Literal["contact", "skip"] | None


@router.put("/{company_id}/manual-check")
async def set_manual_check(
    company_id: int, body: ManualCheck, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Record what the user decided after checking an unscored website by hand (None = undo)."""
    company = await db.get(Company, company_id)
    if company is None or company.workspace_id != user.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    company.manual_check = body.decision
    company.manual_checked_at = datetime.now(UTC) if body.decision else None
    await db.commit()
    return {"id": company.id, "manual_check": company.manual_check, "manual_checked_at": company.manual_checked_at}
