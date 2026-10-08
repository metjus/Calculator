"""The archive, re-contacting and the retention of notes (stage 8).

Three rules from the brief, all with the owner's own numbers behind them:

* a customer who is done with - ``deal``, ``not_interested`` or ``no_answer`` - moves to the
  archive after a few months. Nobody is ever deleted: the archive is what tells the owner who
  was already approached;
* a rejection goes stale, so after a year the customer is offered again on a list of their own;
* notes written by hand are cleared after a couple of years in the archive, but **never without
  asking first** - the program only says who is due and the owner presses the button.

The pass is a few UPDATEs, so it runs whenever the customer list is read rather than needing a
scheduler. Everything it writes is also a timeline entry, so the card explains itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .crm import PROPOSAL_DAYS, WAITING_DAYS
from .models import Company, CompanyEvent, Workspace

# Statuses that mean the work with this customer is finished, one way or the other.
CLOSED_STATUSES = ("deal", "not_interested", "no_answer")
# ... and the two of those that are worth trying again later. A deal is not a rejection.
RECONTACT_STATUSES = ("not_interested", "no_answer")
MONTH = timedelta(days=30)  # the brief counts in months; a calendar month is not needed here
YEAR = timedelta(days=365)


@dataclass(frozen=True)
class Rules:
    """How long each step waits. The owner changes these in Settings."""

    archive_after_months: int = 3
    recontact_after_months: int = 12
    clear_notes_after_years: int = 2
    waiting_days: int = WAITING_DAYS  # "Waiting for an answer" longer than this is a follow-up
    proposal_days: int = PROPOSAL_DAYS  # a design demo left up longer than this should come down

    @classmethod
    def of(cls, workspace: Workspace | None) -> Rules:
        stored = (workspace.crm_rules if workspace else None) or {}
        return cls(**{key: int(stored[key]) for key in cls.__dataclass_fields__ if isinstance(stored.get(key), int | float)})

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def archive_due(status_at: datetime | None, rules: Rules, today: datetime) -> bool:
    return bool(status_at and status_at <= today - rules.archive_after_months * MONTH)


async def run_archive(db: AsyncSession, workspace_id: int, rules: Rules, today: datetime) -> int:
    """Move every closed customer whose time is up into the archive. Returns how many moved.

    Archiving changes nothing about the customer except where they are listed, so it is safe to
    do without asking - unlike clearing notes, which the owner confirms. A customer the owner
    brought back by hand stays out of it until their status changes again; otherwise the next
    pass would undo the very thing they just did.
    """
    cutoff = (today - rules.archive_after_months * MONTH).replace(tzinfo=None)
    due = list(
        await db.scalars(
            select(Company).where(
                Company.workspace_id == workspace_id,
                Company.archived_at.is_(None),
                Company.status.in_(CLOSED_STATUSES),
                Company.status_at.is_not(None),
                Company.status_at <= cutoff,
                or_(Company.unarchived_at.is_(None), Company.status_at > Company.unarchived_at),
            )
        )
    )
    for company in due:
        company.archived_at = today
        db.add(CompanyEvent(company_id=company.id, kind="archived", status=company.status, at=today))
    if due:
        await db.commit()
    return len(due)


def recontact_due(row: dict[str, Any], rules: Rules, today: datetime) -> bool:
    """A rejection old enough to be worth another try."""
    if row["do_not_contact"] or row["status"] not in RECONTACT_STATUSES:
        return False
    since = row["status_at"]
    return bool(since and since <= today - rules.recontact_after_months * MONTH)


def notes_due(row: dict[str, Any], rules: Rules, today: datetime) -> bool:
    """Notes that have been in the archive long enough to be cleared - after the owner agrees."""
    if not row["has_notes"]:
        return False
    since = row["archived_at"]
    return bool(since and since <= today - rules.clear_notes_after_years * YEAR)


async def clear_notes(db: AsyncSession, company_ids: list[int], today: datetime) -> int:
    """Drop what was written by hand; keep the business, the website, the dates and the results."""
    if not company_ids:
        return 0
    await db.execute(update(Company).where(Company.id.in_(company_ids)).values(notes=None))
    await db.execute(update(CompanyEvent).where(CompanyEvent.company_id.in_(company_ids), CompanyEvent.note.is_not(None)).values(note=None))
    for company_id in company_ids:
        db.add(CompanyEvent(company_id=company_id, kind="notes_cleared", at=today))
    await db.commit()
    return len(company_ids)
