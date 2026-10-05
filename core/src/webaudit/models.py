"""Result models shared by the scanner, the CLI and the SaaS backend.

Nothing in here may hold contact data (names, phone numbers, e-mails):
checks record only booleans, counts and URLs of the audited site.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class Status(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    NA = "na"  # not applicable or could not be evaluated; never counts towards the score


class Area(StrEnum):
    BASICS = "basics"
    MOBILE = "mobile"
    SPEED = "speed"
    SEO = "seo"
    TRUST = "trust"
    TECH = "tech"
    ACCESSIBILITY = "accessibility"
    DESIGN = "design"
    DESIGN_AI = "design_ai"


class SiteState(StrEnum):
    OK = "ok"  # scanned and scored
    UNREACHABLE = "unreachable"  # could not be loaded; no score, only a reason
    PROTECTED = "protected"  # blocked by Cloudflare or another firewall; check manually
    DISALLOWED = "disallowed"  # robots.txt forbids scanning
    INVALID = "invalid"  # malformed URL or a target we refuse to scan (private network)
    CANCELLED = "cancelled"


class Category(StrEnum):
    CRITICAL = "critical"
    WEAK = "weak"
    OK = "ok"
    GOOD = "good"


class LogLevel(StrEnum):
    INFO = "info"
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


class CheckResult(BaseModel):
    id: str
    area: Area
    status: Status
    value: Any = None
    summary: str = ""  # one English line for the operator (UI language is English)
    evidence: list[str] = Field(default_factory=list)


class LogEntry(BaseModel):
    time: datetime = Field(default_factory=utcnow)
    level: LogLevel
    message: str


class AreaScore(BaseModel):
    area: Area
    score: int
    weight: float
    checks: int


class Score(BaseModel):
    total: int
    category: Category
    areas: list[AreaScore]


class Issue(BaseModel):
    check_id: str
    area: Area
    status: Status
    impact: float  # approximate points of the total score this problem costs


class Protection(BaseModel):
    provider: str  # "cloudflare", "sucuri", ...
    evidence: list[str] = Field(default_factory=list)


class LibraryInfo(BaseModel):
    name: str
    version: str | None = None
    status: Status = Status.PASS


class TechInfo(BaseModel):
    cms: str | None = None
    cms_version: str | None = None
    libraries: list[LibraryInfo] = Field(default_factory=list)


class ScanResult(BaseModel):
    input_url: str
    url: str | None = None
    final_url: str | None = None
    state: SiteState = SiteState.OK
    state_reason: str | None = None
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    checks: list[CheckResult] = Field(default_factory=list)
    score: Score | None = None
    issues: list[Issue] = Field(default_factory=list)
    tech: TechInfo = Field(default_factory=TechInfo)
    protection: Protection | None = None
    screenshots: dict[str, str] = Field(default_factory=dict)
    log: list[LogEntry] = Field(default_factory=list)

    @property
    def duration_s(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    def check(self, check_id: str) -> CheckResult | None:
        return next((c for c in self.checks if c.id == check_id), None)
