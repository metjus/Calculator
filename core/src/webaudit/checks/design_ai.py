"""The overall design impression, judged by Claude from the screenshots (``ai_review.py``).

The review itself is made in the gather phase; this check only grades it. Its 0–100 score
counts directly (``CheckResult.credit``), so a 72 adds more than a 61 although both pass.
"""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..context import ScanContext
from ..models import Area, CheckResult, Status
from . import check, na, result

A = Area.DESIGN_AI
CHECK_ID = "design_ai.review"


def grade_review(review: dict[str, Any] | None, note: str | None, config: Config) -> CheckResult:
    """Also used by the API when the operator asks for a review after the audit."""
    if review is None:
        return na(CHECK_ID, A, note or "AI design review was not requested")
    score = int(review["score"])
    if score >= config.threshold("ai_design_pass"):
        status = Status.PASS
    elif score >= config.threshold("ai_design_fail_below"):
        status = Status.WARN
    else:
        status = Status.FAIL
    graded = result(
        CHECK_ID,
        A,
        status,
        f"Claude rated the design {score}/100: {review.get('verdict', '')}"[:300],
        value=review,
        evidence=review.get("weaknesses"),
    )
    graded.credit = score / 100
    return graded


@check(CHECK_ID, A)
def design_review(ctx: ScanContext) -> CheckResult:
    return grade_review(ctx.ai_review, ctx.ai_review_note, ctx.config)
