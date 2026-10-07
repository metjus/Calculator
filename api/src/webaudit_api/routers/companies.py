"""Customers: the list, the card with its timeline, statuses, contacts and the follow-up list.

This is the CRM of stage 7. The rules it follows come from ``..crm``; the endpoints here only
load rows, apply the filters and write what the operator did. No contact person, phone number
or e-mail is ever stored - a logged contact keeps the date, how it happened and a short note.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from webaudit.inputs import normalize_url

from ..companies import domain_of
from ..crm import (
    CONTACT_WAYS,
    STATUSES,
    Row,
    aware,
    contact_summary,
    default_status,
    follow_up_reason,
    latest_audit_map,
    now,
    proposal_warning,
    row_out,
    set_status,
    statistics,
    timeline,
)
from ..deps import current_user, get_db
from ..models import Company, CompanyEvent, User

router = APIRouter(prefix="/api/companies", tags=["companies"])
MAX_ROWS = 2000


class CompanyIn(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=2048)
    project: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)
    next_step: str | None = Field(default=None, max_length=300)
    next_step_at: datetime | None = None
    proposal_url: str | None = Field(default=None, max_length=2048)
    proposal_sent_at: datetime | None = None
    do_not_contact: bool | None = None


class StatusIn(BaseModel):
    status: str
    note: str | None = Field(default=None, max_length=2000)
    deal_value: int | None = Field(default=None, ge=0, le=10_000_000)


class ContactIn(BaseModel):
    way: Literal["in_person", "phone", "email", "message"]
    note: str | None = Field(default=None, max_length=2000)
    at: datetime | None = None


class ManualCheck(BaseModel):
    decision: Literal["contact", "skip"] | None


async def _own(db: AsyncSession, user: User, company_id: int) -> Company:
    company = await db.get(Company, company_id)
    if company is None or company.workspace_id != user.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return company


async def _rows(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    """Every customer of the workspace with their latest scan and contact summary."""
    companies = list(
        await db.scalars(
            select(Company).where(Company.workspace_id == user.workspace_id).order_by(Company.created_at.desc()).limit(MAX_ROWS)
        )
    )
    audits = await latest_audit_map(db, user.workspace_id)
    contacts = await contact_summary(db, [c.id for c in companies])
    out = []
    for company in companies:
        score, audit_id, site_id = audits.get(company.id, (None, None, None))
        last_contact, count = contacts.get(company.id, (None, 0))
        out.append(
            row_out(Row(company=company, score=score, audit_id=audit_id, site_id=site_id, last_contact=last_contact, contacts=count))
        )
    return out


@router.get("")
async def list_companies(
    status_filter: str = Query(default="", alias="status"),
    project: str = "",
    website: str = Query(default="", pattern="^(|yes|no)$"),
    q: str = "",
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The customer list with the filters of the brief, the charts, and who needs a nudge."""
    everything = await _rows(db, user)
    wanted = {s for s in status_filter.split(",") if s in STATUSES}
    needle = q.strip().lower()
    rows = [
        row
        for row in everything
        if (not wanted or row["status"] in wanted)
        and (not project or (row["project"] or "") == project)
        and (not website or (row["has_website"] if website == "yes" else not row["has_website"]))
        and (not needle or needle in f"{row['name'] or ''} {row['domain'] or ''} {row['project'] or ''}".lower())
    ]
    today = now()
    follow_ups = []
    for row in everything:
        reason = follow_up_reason(row, today)
        if reason:
            follow_ups.append({**row, "reason": reason})
    follow_ups.sort(key=lambda row: row["next_step_at"] or row["status_at"] or today)
    return {
        "rows": rows,
        "follow_ups": follow_ups,
        "projects": sorted({row["project"] for row in everything if row["project"]}),
        "statuses": [{"id": key, "label": meta["label"], "open": meta["open"]} for key, meta in STATUSES.items()],
        "stats": await statistics(db, user.workspace_id, rows),
        "total": len(everything),
    }


@router.post("", status_code=201)
async def create_company(body: CompanyIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Add a customer by hand. Without a website they are a lead for a new one."""
    url = (body.url or "").strip()
    if url:
        try:
            url = normalize_url(url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if not url and not (body.name or "").strip():
        raise HTTPException(422, "Give the customer a name or a website address")
    company = Company(
        workspace_id=user.workspace_id,
        name=(body.name or "").strip() or None,
        url=url or None,
        domain=domain_of(url) if url else None,
        project=(body.project or "").strip() or None,
        notes=body.notes,
        status="audited" if url else "lead",
        status_at=now(),
    )
    db.add(company)
    await db.flush()
    db.add(CompanyEvent(company_id=company.id, kind="status", status=company.status, at=company.status_at))
    await db.commit()
    return await read_company(company.id, user, db)


@router.get("/{company_id}")
async def read_company(company_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    company = await _own(db, user, company_id)
    audits = await latest_audit_map(db, user.workspace_id)
    score, audit_id, site_id = audits.get(company.id, (None, None, None))
    last_contact, count = (await contact_summary(db, [company.id])).get(company.id, (None, 0))
    row = row_out(Row(company=company, score=score, audit_id=audit_id, site_id=site_id, last_contact=last_contact, contacts=count))
    return {
        "customer": {
            **row,
            "notes": company.notes,
            "proposal_url": company.proposal_url,
            "proposal_sent_at": aware(company.proposal_sent_at),
            "proposal_warning": proposal_warning(company, now()),
            "manual_check": company.manual_check,
            "source": "google" if company.place_id else ("osm" if company.osm_id else "manual"),
        },
        "timeline": await timeline(db, company, user.workspace_id),
        "statuses": [{"id": key, "label": meta["label"], "open": meta["open"]} for key, meta in STATUSES.items()],
        "ways": list(CONTACT_WAYS),
    }


@router.patch("/{company_id}")
async def update_company(
    company_id: int, body: CompanyIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    company = await _own(db, user, company_id)
    fields = body.model_dump(exclude_unset=True)
    if "url" in fields:
        url = (fields["url"] or "").strip()
        if url:
            try:
                url = normalize_url(url)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        company.url, company.domain = url or None, domain_of(url) if url else None
        if url and company.status == "lead":
            # A lead that now has a website can be audited like anyone else.
            db.add(set_status(company, "audited"))
    for field in ("name", "project", "notes", "next_step", "next_step_at", "proposal_url", "proposal_sent_at", "do_not_contact"):
        if field in fields:
            value = fields[field]
            setattr(company, field, value.strip() or None if isinstance(value, str) else value)
    if fields.get("proposal_url") and not company.proposal_sent_at:
        company.proposal_sent_at = now()
        db.add(CompanyEvent(company_id=company.id, kind="proposal", note=company.proposal_url, at=company.proposal_sent_at))
    await db.commit()
    return await read_company(company_id, user, db)


@router.post("/{company_id}/status")
async def change_status(
    company_id: int, body: StatusIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    if body.status not in STATUSES:
        raise HTTPException(422, "Unknown status")
    company = await _own(db, user, company_id)
    if body.status == "deal" and body.deal_value is not None:
        company.deal_value = body.deal_value
    db.add(set_status(company, body.status, body.note))
    await db.commit()
    return await read_company(company_id, user, db)


@router.post("/{company_id}/contacts", status_code=201)
async def log_contact(
    company_id: int, body: ContactIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Record that contact happened: the date, how, and a short note. Never who."""
    company = await _own(db, user, company_id)
    db.add(CompanyEvent(company_id=company.id, kind="contact", way=body.way, note=body.note, at=body.at or now()))
    if company.status in (None, "lead", "audited"):
        db.add(set_status(company, "contacted"))
    await db.commit()
    return await read_company(company_id, user, db)


@router.delete("/{company_id}/events/{event_id}")
async def delete_event(
    company_id: int, event_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _own(db, user, company_id)
    event = await db.get(CompanyEvent, event_id)
    if event is None or event.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    await db.delete(event)
    await db.commit()
    return await read_company(company_id, user, db)


@router.delete("/{company_id}/notes")
async def delete_notes(company_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Keep the customer, the website, the dates and the result; drop what was written by hand."""
    company = await _own(db, user, company_id)
    company.notes = None
    await db.execute(
        CompanyEvent.__table__.update().where(CompanyEvent.company_id == company.id, CompanyEvent.note.is_not(None)).values(note=None)
    )
    await db.commit()
    return await read_company(company_id, user, db)


@router.delete("/{company_id}", status_code=200)
async def delete_company(
    company_id: int,
    keep_url: bool = False,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete the customer. ``keep_url`` leaves the address behind marked "do not contact"."""
    company = await _own(db, user, company_id)
    url, domain, workspace_id = company.url, company.domain, company.workspace_id
    await db.execute(delete(CompanyEvent).where(CompanyEvent.company_id == company.id))
    await db.delete(company)
    if keep_url and url:
        db.add(Company(workspace_id=workspace_id, url=url, domain=domain, do_not_contact=True, status="not_interested", status_at=now()))
    await db.commit()
    return {"deleted": "yes", "kept_url": "yes" if keep_url and url else "no"}


@router.put("/{company_id}/manual-check")
async def set_manual_check(
    company_id: int, body: ManualCheck, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """What the user decided after checking an unscored website by hand (None = undo)."""
    company = await _own(db, user, company_id)
    company.manual_check = body.decision
    company.manual_checked_at = datetime.now(UTC) if body.decision else None
    if body.decision == "skip" and company.status in (None, "audited"):
        db.add(set_status(company, "not_interested", "Checked by hand: not worth contacting"))
    await db.commit()
    return {"id": company.id, "manual_check": company.manual_check, "manual_checked_at": company.manual_checked_at}


@router.get("/{company_id}/duplicates", include_in_schema=False)
async def duplicates(company_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    """Other customers with the same domain or name - the brief's duplicate check."""
    company = await _own(db, user, company_id)
    clauses = []
    if company.domain:
        clauses.append(Company.domain == company.domain)
    if company.name:
        clauses.append(func.lower(Company.name) == company.name.lower())
    if not clauses:
        return []
    rows = await db.scalars(
        select(Company).where(Company.workspace_id == user.workspace_id, Company.id != company.id, or_(*clauses)).limit(10)
    )
    return [
        {
            "id": other.id,
            "name": other.name,
            "domain": other.domain,
            "status": other.status or default_status(other, False),
            "status_label": STATUSES[other.status or default_status(other, False)]["label"],
            "created_at": aware(other.created_at),
        }
        for other in rows
    ]
