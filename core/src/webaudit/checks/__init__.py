"""Check registry. Each check is a pure function ``(ScanContext) -> CheckResult``."""

from __future__ import annotations

from collections.abc import Callable

from ..context import ScanContext
from ..models import Area, CheckResult, Status

CheckFn = Callable[[ScanContext], CheckResult]
REGISTRY: list[tuple[str, Area, CheckFn]] = []


def check(check_id: str, area: Area) -> Callable[[Callable[..., CheckResult]], Callable[..., CheckResult]]:
    def decorator(fn: Callable[..., CheckResult]) -> Callable[..., CheckResult]:
        REGISTRY.append((check_id, area, fn))
        return fn

    return decorator


def result(
    ctx_id: str, area: Area, status: Status, summary: str = "", value: object = None, evidence: list[str] | None = None
) -> CheckResult:
    return CheckResult(id=ctx_id, area=area, status=status, summary=summary, value=value, evidence=(evidence or [])[:10])


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    """``plural(1, "image") -> "1 image"``, ``plural(3, "image") -> "3 images"``."""
    return f"{count} {singular if count == 1 else (plural_form or singular + 's')}"


def na(check_id: str, area: Area, summary: str) -> CheckResult:
    return CheckResult(id=check_id, area=area, status=Status.NA, summary=summary)


def grade(value: float, *, warn_at: float, fail_at: float) -> Status:
    """Higher is worse: ``value >= fail_at`` fails, ``value >= warn_at`` warns."""
    if value >= fail_at:
        return Status.FAIL
    if value >= warn_at:
        return Status.WARN
    return Status.PASS


def run_all(ctx: ScanContext) -> tuple[list[CheckResult], list[str]]:
    """Run every registered check; a crashing check becomes ``na`` plus an error message."""
    from . import accessibility, basics, design, mobile, seo, speed, tech, trust  # noqa: F401  (registration)

    results: list[CheckResult] = []
    errors: list[str] = []
    for check_id, area, fn in REGISTRY:
        try:
            results.append(fn(ctx))
        except Exception as exc:  # noqa: BLE001 - one broken check must not stop the audit
            results.append(na(check_id, area, "check failed internally"))
            errors.append(f"{check_id}: {exc.__class__.__name__}: {exc}")
    return results, errors
