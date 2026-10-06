"""Audit dashboard (stage 3): metrics, charts and the websites table across all audits.

Each website counts once: the latest finished scan of each customer (or domain, for sites
without one) within the chosen project and period. Websites without a score are listed
separately under “Check manually” and stay out of every statistic.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from webaudit import Config
from webaudit.dom import bare_host
from webaudit.report import check_label

from ..deps import current_user, get_db
from ..models import Audit, AuditSite, User
from ..site_view import checks_by_id

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
_CONFIG = Config.load()  # English labels for problem ids
UNSCORED = ("unreachable", "protected", "disallowed", "invalid")
CATEGORIES = ("critical", "weak", "ok", "good")
CMS_SLICES = 5  # the brief: at most five CMS slices plus "Other"
TOP_PROBLEMS = 8


def _domain(site: AuditSite) -> str:
    return bare_host(site.final_url or site.input_url) or site.input_url


def _yes_no(sites: list[AuditSite], check_id: str) -> dict[str, int]:
    counts = {"yes": 0, "no": 0}
    for site in sites:
        status = (checks_by_id(site.result or {}).get(check_id) or {}).get("status")
        if status == "pass":
            counts["yes"] += 1
        elif status in ("warn", "fail"):
            counts["no"] += 1
    return counts


@router.get("")
async def dashboard(
    project: str | None = Query(default=None, max_length=200),
    days: int | None = Query(default=None, ge=1, le=3650),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(AuditSite, Audit.project)
            .join(Audit)
            .where(Audit.workspace_id == user.workspace_id, AuditSite.finished_at.is_not(None), AuditSite.state.in_(("ok", *UNSCORED)))
            .order_by(AuditSite.finished_at.desc(), AuditSite.id.desc())
        )
    ).all()
    projects = sorted({name for _, name in rows if name})
    since = datetime.now(UTC) - timedelta(days=days) if days else None

    latest: dict[str, tuple[AuditSite, str | None]] = {}
    for site, audit_project in rows:
        site_project = audit_project or (site.company.project if site.company else None)
        if project and project not in (audit_project, site.company.project if site.company else None):
            continue
        finished = site.finished_at if site.finished_at.tzinfo else site.finished_at.replace(tzinfo=UTC)
        if since and finished < since:
            continue
        key = f"company:{site.company_id}" if site.company_id else f"domain:{_domain(site)}"
        latest.setdefault(key, (site, site_project))

    scored = [(s, p) for s, p in latest.values() if s.state == "ok" and s.score is not None]
    unscored = [(s, p) for s, p in latest.values() if s.state in UNSCORED]
    scored_sites = [s for s, _ in scored]

    problem_counts: Counter[str] = Counter()
    cms_counts: Counter[str] = Counter()
    websites = []
    for site, site_project in scored:
        result = site.result or {}
        issues = result.get("issues") or []
        problem_counts.update({issue["check_id"] for issue in issues})
        cms_counts[(result.get("tech") or {}).get("cms") or "Not detected"] += 1
        websites.append(
            {
                "site_id": site.id,
                "audit_id": site.audit_id,
                "domain": _domain(site),
                "company": site.company.name if site.company else None,
                "project": site_project,
                "score": site.score,
                "category": site.category,
                "top_issue": check_label(_CONFIG, issues[0]["check_id"]) if issues else None,
                "issues": len(issues),
                "issue_ids": [issue["check_id"] for issue in issues],
                "finished_at": site.finished_at,
            }
        )
    websites.sort(key=lambda w: (w["score"], w["domain"]))

    top_cms = cms_counts.most_common(CMS_SLICES)
    other = sum(cms_counts.values()) - sum(n for _, n in top_cms)
    cms = [{"name": name, "count": n} for name, n in top_cms] + ([{"name": "Other", "count": other}] if other else [])

    https = _yes_no(scored_sites, "basics.https")
    manual = [
        {
            "site_id": site.id,
            "audit_id": site.audit_id,
            "company_id": site.company_id,
            "domain": _domain(site),
            "url": site.final_url or site.input_url,
            "company": site.company.name if site.company else None,
            "project": site_project,
            "state": site.state,
            "reason": site.state_reason,
            "decision": site.company.manual_check if site.company else None,
            "checked_at": site.company.manual_checked_at if site.company else None,
            "finished_at": site.finished_at,
        }
        for site, site_project in unscored
    ]
    return {
        "projects": projects,
        "metrics": {
            "audited": len(scored_sites),
            "to_check": sum(1 for m in manual if not m["decision"]),
            "average": round(sum(s.score for s in scored_sites) / len(scored_sites)) if scored_sites else None,
            "critical": sum(1 for s in scored_sites if s.category == "critical"),
            "without_https": https["no"],
        },
        "categories": {category: sum(1 for s in scored_sites if s.category == category) for category in CATEGORIES},
        "https": https,
        "mobile": _yes_no(scored_sites, "mobile.viewport"),
        "cms": cms,
        "problems": [
            {"check_id": check_id, "label": check_label(_CONFIG, check_id), "count": n}
            for check_id, n in problem_counts.most_common(TOP_PROBLEMS)
        ],
        "websites": websites,
        "manual": manual,
    }
