"""Claude's design review in the API: cost estimate, the reviewer to use, and rescoring a stored result.

The review itself lives in core (``webaudit.ai_review``). The audit worker runs it during a
scan when the audit asked for it; ``POST /api/audits/{id}/sites/{sid}/ai-review`` runs it later
for one website from its stored screenshots. Tests replace the reviewer through
``app.state.ai_reviewer_factory``; nothing here calls the Claude API in tests.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from webaudit import Config, ScanResult
from webaudit.ai_review import ClaudeReviewer, Reviewer
from webaudit.checks.design_ai import CHECK_ID, grade_review
from webaudit.scoring import rank_issues, score


@cache
def pricing() -> dict[str, Any]:
    return json.loads(resources.files(__package__).joinpath("ai_pricing.json").read_text("utf-8"))


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    price = pricing()["usd_per_mtok"]
    return round(input_tokens * price["input"] / 1_000_000 + output_tokens * price["output"] / 1_000_000, 4)


def estimate(sites: int) -> dict[str, Any]:
    """Price range for reviewing ``sites`` websites (the model's reasoning length varies)."""
    tokens = pricing()["tokens_per_site"]
    low = cost_usd(tokens["input"], tokens["output_low"])
    high = cost_usd(tokens["input"], tokens["output_high"])
    return {
        "model": pricing()["model"],
        "sites": sites,
        "per_site_usd": {"low": round(low, 2), "high": round(high, 2)},
        "total_usd": {"low": round(low * sites, 2), "high": round(high * sites, 2)},
    }


def reviewer_for(state: Any, api_key: str) -> Reviewer:
    factory = getattr(state, "ai_reviewer_factory", None)  # tests inject a fake
    return factory(api_key) if factory else ClaudeReviewer(api_key)


def apply_review(result: dict[str, Any], review: dict[str, Any] | None, note: str | None, config: Config) -> dict[str, Any]:
    """The stored result with the design-review check replaced and the score and issues recomputed."""
    scan = ScanResult.model_validate(result)
    graded = grade_review(review, note, config)
    scan.checks = [c for c in scan.checks if c.id != CHECK_ID] + [graded]
    scan.score = score(scan.checks, config.scoring)
    scan.issues = rank_issues(scan.checks, config.scoring)
    return scan.model_dump(mode="json")


def review_view(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """The review as the website detail shows it, with its cost; None when the check is missing."""
    check = next((c for c in (result or {}).get("checks") or [] if c["id"] == CHECK_ID), None)
    if check is None:
        return None
    value = check.get("value") or {}
    view = {"status": check["status"], "summary": check.get("summary", ""), **value}
    if value.get("input_tokens") is not None:
        view["cost_usd"] = cost_usd(value["input_tokens"], value.get("output_tokens") or 0)
    return view
