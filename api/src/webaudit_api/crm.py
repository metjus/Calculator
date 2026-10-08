"""The sales side of the program: where every customer stands and who needs a nudge (stage 7).

The brief's funnel, in order. A customer enters as ``audited`` (or ``lead`` when they have no
website yet) and leaves the funnel through ``deal``, ``not_interested`` or ``no_answer``.
Statuses are stored on the customer and every change is also written to the timeline, so the
card can show when each step happened without a second source of truth.

Nothing here stores a contact person, a phone number or an e-mail: a logged contact keeps only
the date, how it happened and a short note.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Audit, AuditSite, Company, CompanyEvent

# id, English label for the operator UI, and whether the customer is still in play.
STATUSES: dict[str, dict[str, Any]] = {
    "lead": {"label": "Lead (no website)", "open": True, "funnel": False},
    "audited": {"label": "Audited", "open": True, "funnel": True},
    "contacted": {"label": "Contacted", "open": True, "funnel": True},
    "waiting": {"label": "Waiting for an answer", "open": True, "funnel": True},
    "interested": {"label": "Interested", "open": True, "funnel": True},
    "proposal": {"label": "Proposal sent", "open": True, "funnel": True},
    "deal": {"label": "Deal", "open": False, "funnel": True},
    "not_interested": {"label": "Not interested", "open": False, "funnel": False},
    "no_answer": {"label": "No answer", "open": False, "funnel": False},
}
FUNNEL = [key for key, meta in STATUSES.items() if meta["funnel"]]
CONTACT_WAYS = ("in_person", "phone", "email", "message")
WAITING_DAYS = 7  # "Waiting for an answer" longer than this lands on the follow-up list
PROPOSAL_DAYS = 30  # after this the demo of the design should come down


def now() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; compare them as UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def default_status(company: Company, scored: bool) -> str:
    if company.status:
        return company.status
    if not company.url:
        return "lead"
    return "audited" if scored else "audited"


@dataclass
class Row:
    """One line of the customer list."""

    company: Company
    score: int | None
    audit_id: int | None
    site_id: int | None
    last_contact: datetime | None
    contacts: int


async def latest_audit_map(db: AsyncSession, workspace_id: int) -> dict[int, tuple[int | None, int, int]]:
    """company_id -> (score, audit_id, site_id) of its most recent finished scan."""
    latest = (
        select(AuditSite.company_id, func.max(AuditSite.id).label("site_id"))
        .join(Audit)
        .where(Audit.workspace_id == workspace_id, AuditSite.finished_at.is_not(None), AuditSite.company_id.is_not(None))
        .group_by(AuditSite.company_id)
        .subquery()
    )
    rows = await db.execute(
        select(AuditSite.company_id, AuditSite.score, AuditSite.audit_id, AuditSite.id).join(latest, AuditSite.id == latest.c.site_id)
    )
    return {company_id: (score, audit_id, site_id) for company_id, score, audit_id, site_id in rows}


async def contact_summary(db: AsyncSession, company_ids: list[int]) -> dict[int, tuple[datetime | None, int]]:
    if not company_ids:
        return {}
    rows = await db.execute(
        select(CompanyEvent.company_id, func.max(CompanyEvent.at), func.count(CompanyEvent.id))
        .where(CompanyEvent.company_id.in_(company_ids), CompanyEvent.kind == "contact")
        .group_by(CompanyEvent.company_id)
    )
    return {company_id: (aware(last), count) for company_id, last, count in rows}


def row_out(row: Row) -> dict[str, Any]:
    company = row.company
    status = company.status or default_status(company, row.score is not None)
    return {
        "id": company.id,
        "name": company.name,
        "url": company.url,
        "domain": company.domain,
        "project": company.project,
        "has_website": bool(company.url),
        "do_not_contact": company.do_not_contact,
        "manual_check": company.manual_check,  # the decision after checking an unscored website by hand
        "status": status,
        "status_label": STATUSES[status]["label"],
        "status_at": aware(company.status_at),
        "archived_at": aware(company.archived_at),
        "has_notes": bool(company.notes),
        "next_step": company.next_step,
        "next_step_at": aware(company.next_step_at),
        "deal_value": company.deal_value,
        "score": row.score,
        "audit_id": row.audit_id,
        "site_id": row.site_id,
        "last_contact": row.last_contact,
        "contacts": row.contacts,
        "created_at": aware(company.created_at),
    }


def follow_up_reason(row: dict[str, Any], today: datetime, waiting_days: int = WAITING_DAYS) -> str | None:
    """Why this customer is on the follow-up list, or None when they are not."""
    if row["do_not_contact"] or row["archived_at"]:
        return None
    next_step_at = row["next_step_at"]
    if next_step_at and next_step_at <= today:
        return "next_step"
    if row["status"] == "waiting":
        since = row["status_at"]
        if since and since <= today - timedelta(days=waiting_days):
            return "waiting"
    return None


def proposal_warning(company: Company, today: datetime, days: int = PROPOSAL_DAYS) -> bool:
    """True when a design demo has been up longer than the agreed days and should come down."""
    sent = aware(company.proposal_sent_at)
    return bool(sent and company.proposal_url and sent <= today - timedelta(days=days))


async def timeline(db: AsyncSession, company: Company, workspace_id: int) -> list[dict[str, Any]]:
    """Everything that happened to this customer, newest first: audits and the logged events."""
    events = await db.scalars(select(CompanyEvent).where(CompanyEvent.company_id == company.id).order_by(CompanyEvent.at.desc()))
    out: list[dict[str, Any]] = [
        {
            "kind": event.kind,
            "at": aware(event.at),
            "status": event.status,
            "status_label": STATUSES.get(event.status or "", {}).get("label"),
            "way": event.way,
            "note": event.note,
            "id": event.id,
        }
        for event in events
    ]
    audits = await db.execute(
        select(AuditSite.id, AuditSite.audit_id, AuditSite.score, AuditSite.state, AuditSite.finished_at)
        .join(Audit)
        .where(Audit.workspace_id == workspace_id, AuditSite.company_id == company.id, AuditSite.finished_at.is_not(None))
        .order_by(AuditSite.finished_at.desc())
    )
    out += [
        {
            "kind": "audit",
            "at": aware(finished_at),
            "score": score,
            "state": state,
            "audit_id": audit_id,
            "site_id": site_id,
            "id": -site_id,
        }
        for site_id, audit_id, score, state, finished_at in audits
    ]
    out.sort(key=lambda item: item["at"] or now(), reverse=True)
    return out


def set_status(company: Company, status: str, note: str | None = None, at: datetime | None = None) -> CompanyEvent:
    company.status = status
    company.status_at = at or now()
    return CompanyEvent(company_id=company.id, kind="status", status=status, note=note, at=company.status_at)


# ------------------------------------------------------------------ numbers


async def statistics(db: AsyncSession, workspace_id: int, rows: list[dict[str, Any]], weeks: int = 12) -> dict[str, Any]:
    """The charts of the brief: the funnel, conversion, weekly outreach and deals, and the money."""
    counts = {key: 0 for key in STATUSES}
    for row in rows:
        counts[row["status"]] += 1

    contacted = sum(counts[key] for key in ("contacted", "waiting", "interested", "proposal", "deal"))
    interested = sum(counts[key] for key in ("interested", "proposal", "deal"))
    deals = counts["deal"]
    ids = [row["id"] for row in rows]

    # Weekly outreach and deals, from the timeline rather than the current status.
    series: dict[str, dict[str, int]] = {}
    start = now() - timedelta(weeks=weeks)
    if ids:
        events = await db.scalars(
            select(CompanyEvent).where(CompanyEvent.company_id.in_(ids), CompanyEvent.at >= start.replace(tzinfo=None))
        )
        for event in events:
            moment = aware(event.at)
            if moment is None:
                continue
            week = (moment - timedelta(days=moment.weekday())).date().isoformat()
            bucket = series.setdefault(week, {"contacted": 0, "deals": 0})
            if event.kind == "contact" or (event.kind == "status" and event.status == "contacted"):
                bucket["contacted"] += 1
            if event.kind == "status" and event.status == "deal":
                bucket["deals"] += 1

    answer_days = await _average_answer_days(db, ids)
    return {
        "funnel": [{"status": key, "label": STATUSES[key]["label"], "count": counts[key]} for key in FUNNEL],
        "by_status": [{"status": key, "label": STATUSES[key]["label"], "count": counts[key]} for key in STATUSES if counts[key]],
        "conversion": {
            "contacted": contacted,
            "interested": interested,
            "deals": deals,
            "interested_pct": round(interested / contacted * 100) if contacted else None,
            "deal_pct": round(deals / contacted * 100) if contacted else None,
        },
        "weeks": [{"week": week, **series[week]} for week in sorted(series)],
        "answer_days": answer_days,
        "deal_value": sum(row["deal_value"] or 0 for row in rows if row["status"] == "deal"),
        "open": sum(1 for row in rows if STATUSES[row["status"]]["open"]),
        "total": len(rows),
    }


async def _average_answer_days(db: AsyncSession, company_ids: list[int]) -> float | None:
    """Days from "contacted" to the first status that means the customer answered."""
    if not company_ids:
        return None
    answered = {"interested", "not_interested", "proposal", "deal"}
    events = await db.scalars(
        select(CompanyEvent)
        .where(CompanyEvent.company_id.in_(company_ids), CompanyEvent.kind == "status")
        .order_by(CompanyEvent.company_id, CompanyEvent.at)
    )
    spans: list[float] = []
    contacted_at: dict[int, datetime] = {}
    for event in events:
        moment = aware(event.at)
        if moment is None:
            continue
        if event.status == "contacted":
            contacted_at[event.company_id] = moment
        elif event.status in answered and event.company_id in contacted_at:
            spans.append((moment - contacted_at.pop(event.company_id)).total_seconds() / 86400)
    return round(sum(spans) / len(spans), 1) if spans else None
