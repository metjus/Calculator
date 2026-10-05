"""Companies (future CRM records): lookup by domain so the same business is never duplicated."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from webaudit.dom import bare_host

from .models import Company


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    return bare_host(url) or None


async def get_or_create_company(
    db: AsyncSession,
    workspace_id: int,
    *,
    url: str | None,
    name: str | None = None,
    project: str | None = None,
    place_id: str | None = None,
    osm_id: str | None = None,
) -> Company:
    domain = domain_of(url)
    company: Company | None = None
    if domain:
        company = await db.scalar(select(Company).where(Company.workspace_id == workspace_id, Company.domain == domain).limit(1))
    elif place_id:
        company = await db.scalar(select(Company).where(Company.workspace_id == workspace_id, Company.place_id == place_id).limit(1))
    elif osm_id:
        company = await db.scalar(select(Company).where(Company.workspace_id == workspace_id, Company.osm_id == osm_id).limit(1))
    if company is None:
        company = Company(workspace_id=workspace_id, url=url, domain=domain)
        db.add(company)
    # Fill gaps, never overwrite what the user already has.
    company.name = company.name or (name or None)
    company.project = company.project or (project or None)
    company.place_id = company.place_id or place_id
    company.osm_id = company.osm_id or osm_id
    if url and not company.url:
        company.url, company.domain = url, domain
    await db.flush()
    return company
