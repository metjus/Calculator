"""Everything gathered about one site; checks read from it and never do I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from .config import Config
from .fetch import Fetch
from .models import utcnow
from .robots import Robots


@dataclass
class RenderData:
    """Result of loading the page in a real browser at one viewport."""

    ok: bool
    error: str | None = None
    title: str = ""
    html: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    console_errors: list[str] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    cookie: dict[str, Any] = field(default_factory=dict)
    screenshot: str | None = None


@dataclass
class ScanContext:
    config: Config
    url: str
    home: Fetch
    dom: BeautifulSoup  # rendered DOM when a browser was used, otherwise the static HTML
    static_dom: BeautifulSoup
    robots: Robots
    now: datetime = field(default_factory=utcnow)
    http_probe: Fetch | None = None
    sitemap_found: bool | None = None
    favicon_found: bool | None = None
    contact_url: str | None = None
    contact_dom: BeautifulSoup | None = None
    link_results: dict[str, tuple[int | None, str | None]] = field(default_factory=dict)
    image_bytes: dict[str, int] = field(default_factory=dict)  # only used without a browser
    desktop: RenderData | None = None
    mobile: RenderData | None = None
    pagespeed: dict[str, dict[str, Any]] = field(default_factory=dict)  # strategy -> API JSON
    pagespeed_note: str | None = None
    ai_review: dict[str, Any] | None = None  # Claude's design review (ai_review.py), if one was made
    ai_review_note: str | None = None  # why there is none: not requested, no screenshots, API error
    memo: dict[str, Any] = field(default_factory=dict)  # derived values shared by several checks

    @property
    def final_url(self) -> str:
        return self.home.final_url

    @property
    def is_https(self) -> bool:
        return self.final_url.startswith("https://")

    @property
    def browser_ok(self) -> bool:
        return bool(self.desktop and self.desktop.ok)

    @property
    def mobile_ok(self) -> bool:
        return bool(self.mobile and self.mobile.ok)

    @property
    def signatures(self) -> dict[str, Any]:
        return self.config.signatures

    def t(self, key: str) -> Any:
        return self.config.threshold(key)

    def all_requests(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for render in (self.desktop, self.mobile):
            if render and render.ok:
                out.extend(render.requests)
        return out
