"""Creating audits from pasted URLs, CSV files or business-search results."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession
from webaudit.inputs import SiteInput, normalize_url, parse_csv_text

from .companies import domain_of, get_or_create_company
from .models import Audit, AuditEvent, AuditSite

SPLIT_RE = re.compile(r"[\s,;]+")


@dataclass
class AuditRequest:
    project: str | None
    rows: list[SiteInput]
    invalid: list[dict[str, str]] = field(default_factory=list)
    # Extra identifiers for rows coming from business search, keyed by row index.
    place_ids: dict[int, str] = field(default_factory=dict)
    osm_ids: dict[int, str] = field(default_factory=dict)


def parse_url_text(text: str) -> tuple[list[SiteInput], list[dict[str, str]]]:
    rows: list[SiteInput] = []
    invalid: list[dict[str, str]] = []
    for token in SPLIT_RE.split(text or ""):
        if not token:
            continue
        try:
            rows.append(SiteInput(url=normalize_url(token)))
        except ValueError as exc:
            invalid.append({"input": token[:200], "error": str(exc)})
    return rows, invalid


def parse_csv_bytes(data: bytes) -> tuple[list[SiteInput], list[dict[str, str]]]:
    for encoding in ("utf-8-sig", "cp1250"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="replace")
    rows = parse_csv_text(text)  # raises ValueError for unusable CSVs
    invalid = [{"input": r.company or "", "error": r.error} for r in rows if r.error]
    return [r for r in rows if not r.error], invalid


@dataclass
class CreatedAudit:
    audit: Audit | None
    invalid: list[dict[str, str]]
    no_website_leads: int
    skipped_duplicates: int
    # Stage 8: what the import found in the CRM. "Do not contact" is left out of the audit
    # unless the user says otherwise; the rest is only told to them.
    blocked: list[dict[str, str]] = field(default_factory=list)
    known: list[dict[str, str]] = field(default_factory=list)


# Statuses that mean this business has already been approached, so the import says so.
APPROACHED = ("contacted", "waiting", "interested", "proposal", "deal", "not_interested", "no_answer")


def match_reviews(rows: list[tuple[str, dict | None]], urls: list[str]) -> tuple[dict[str, dict], list[str]]:
    """Tie each pasted review to a website of this audit by its bare host.

    Returns the reviews keyed by domain and the addresses in the file that match nothing here -
    usually a typo or a review copied from another list, and worth saying out loud.
    """
    wanted = {domain_of(url) for url in urls if domain_of(url)}
    matched: dict[str, dict] = {}
    unknown: list[str] = []
    for site, review in rows:
        domain = domain_of(site if "//" in site else f"https://{site}")
        if domain and domain in wanted:
            if review is not None:
                matched[domain] = review
        else:
            unknown.append(site[:120])
    return matched, unknown


async def create_audit(
    db: AsyncSession,
    workspace_id: int,
    request: AuditRequest,
    *,
    max_urls: int,
    options: dict | None = None,
    allow_do_not_contact: bool = False,
    reviews: dict[str, dict] | None = None,
) -> CreatedAudit:
    seen: set[str] = set()
    sites: list[AuditSite] = []
    blocked: list[dict[str, str]] = []
    known: list[dict[str, str]] = []
    leads = duplicates = 0
    for index, row in enumerate(request.rows):
        project = row.project or request.project
        place_id, osm_id = request.place_ids.get(index), request.osm_ids.get(index)
        if not row.url:
            # A business without a website becomes a lead for a new website (no audit).
            if row.company or place_id or osm_id:
                await get_or_create_company(db, workspace_id, url=None, name=row.company, project=project, place_id=place_id, osm_id=osm_id)
                leads += 1
            continue
        domain = domain_of(row.url)
        if domain in seen:
            duplicates += 1
            continue
        seen.add(domain)
        if len(sites) >= max_urls:
            request.invalid.append({"input": row.url, "error": f"more than {max_urls} websites in one audit"})
            continue
        company = await get_or_create_company(
            db, workspace_id, url=row.url, name=row.company, project=project, place_id=place_id, osm_id=osm_id
        )
        label = company.name or domain or row.url
        if company.do_not_contact and not allow_do_not_contact:
            # The brief: a business marked "do not contact" is never audited without a word.
            blocked.append({"url": row.url, "name": label})
            continue
        if company.status in APPROACHED or company.archived_at:
            known.append({"url": row.url, "name": label, "status": company.status or ""})
        sites.append(AuditSite(position=len(sites) + 1, input_url=row.url, competitors=row.competitors, company_id=company.id))

    audit = None
    if sites:
        # Reviews pasted from the Claude app wait here until each website has been scanned.
        settings = dict(options or {})
        if reviews:
            settings["pasted_reviews"] = {domain: review for domain, review in reviews.items() if domain in seen}
        audit = Audit(workspace_id=workspace_id, project=request.project, total=len(sites), options=settings, sites=sites)
        db.add(audit)
        await db.flush()
        db.add(AuditEvent(audit_id=audit.id, kind="queued", data={"total": len(sites)}))
    await db.commit()
    return CreatedAudit(
        audit=audit, invalid=request.invalid, no_website_leads=leads, skipped_duplicates=duplicates, blocked=blocked, known=known
    )
