"""Turn check results into a 0–100 score, a category and a ranked issue list."""

from __future__ import annotations

from typing import Any

from .models import Area, AreaScore, Category, CheckResult, Issue, Score, Status


def _evaluated(checks: list[CheckResult], area: str, weights: dict[str, float]) -> list[tuple[CheckResult, float]]:
    return [(c, weights[c.id]) for c in checks if c.area.value == area and c.id in weights and c.status is not Status.NA]


def category_for(total: float, scoring: dict[str, Any]) -> Category:
    chosen = scoring["categories"][0]["id"]
    for cat in sorted(scoring["categories"], key=lambda c: c["min"]):
        if total >= cat["min"]:
            chosen = cat["id"]
    return Category(chosen)


def score(checks: list[CheckResult], scoring: dict[str, Any]) -> Score | None:
    credit = scoring["status_credit"]
    areas: list[AreaScore] = []
    for area, cfg in scoring["areas"].items():
        items = _evaluated(checks, area, cfg["checks"])
        if not items:
            continue
        total_weight = sum(w for _, w in items)
        value = 100 * sum(w * credit[c.status.value] for c, w in items) / total_weight
        areas.append(AreaScore(area=Area(area), score=round(value), weight=cfg["weight"], checks=len(items)))
    if not areas:
        return None
    weight_sum = sum(a.weight for a in areas)
    exact = sum(a.weight * a.score for a in areas) / weight_sum
    total = round(exact)
    return Score(total=total, category=category_for(total, scoring), areas=areas)


def rank_issues(checks: list[CheckResult], scoring: dict[str, Any]) -> list[Issue]:
    """Failed/warned checks ordered by how many total-score points they cost."""
    credit = scoring["status_credit"]
    present = {area: cfg for area, cfg in scoring["areas"].items() if _evaluated(checks, area, cfg["checks"])}
    area_weight_sum = sum(cfg["weight"] for cfg in present.values()) or 1
    issues: list[Issue] = []
    for area, cfg in present.items():
        items = _evaluated(checks, area, cfg["checks"])
        check_weight_sum = sum(w for _, w in items)
        for c, w in items:
            if c.status in (Status.FAIL, Status.WARN):
                lost = (cfg["weight"] / area_weight_sum) * (w / check_weight_sum) * (1 - credit[c.status.value]) * 100
                issues.append(Issue(check_id=c.id, area=c.area, status=c.status, impact=round(lost, 1)))
    issues.sort(key=lambda i: (-i.impact, i.check_id))
    return issues
