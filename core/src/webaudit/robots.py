"""Minimal robots.txt parser (RFC 9309) with ``*`` and ``$`` wildcard support.

``urllib.robotparser`` treats wildcards literally, which makes it more
permissive than the rules site owners actually wrote, so we parse ourselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, path pattern)
    crawl_delay: float | None = None


def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in pattern)
    return re.compile(regex + ("$" if anchored else ""))


class Robots:
    """Parsed robots.txt. ``Robots.allow_all()`` when there is none."""

    def __init__(self, text: str = "", *, disallow_all: bool = False) -> None:
        self.disallow_all = disallow_all
        self.groups: list[_Group] = []
        self.sitemaps: list[str] = []
        if text:
            self._parse(text)

    @classmethod
    def allow_all(cls) -> Robots:
        return cls()

    def _parse(self, text: str) -> None:
        current: _Group | None = None
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                if current is None or not last_was_agent:
                    current = _Group()
                    self.groups.append(current)
                current.agents.append(value.lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if key == "sitemap" and value:
                self.sitemaps.append(value)
            elif current is None:
                continue
            elif key in ("allow", "disallow"):
                if value:
                    current.rules.append((key == "allow", value))
            elif key == "crawl-delay":
                try:
                    current.crawl_delay = float(value)
                except ValueError:
                    pass

    def _group_for(self, agent_token: str) -> _Group | None:
        # RFC 9309: case-insensitive match on the product token ("WebAuditBot" in "WebAuditBot/0.1").
        product = agent_token.split("/", 1)[0].strip().lower()
        specific = [g for g in self.groups if any(a.split("/", 1)[0].strip() == product for a in g.agents if a != "*")]
        if specific:
            return specific[0]
        return next((g for g in self.groups if "*" in g.agents), None)

    def can_fetch(self, agent_token: str, path: str) -> bool:
        if self.disallow_all:
            return False
        if path == "/robots.txt":
            return True
        group = self._group_for(agent_token)
        if group is None:
            return True
        best: tuple[int, bool] | None = None  # (pattern length, allow)
        for allow, pattern in group.rules:
            if _pattern_to_regex(pattern).match(path):
                candidate = (len(pattern), allow)
                # Longest match wins; on a tie, allow wins (RFC 9309 2.2.2).
                if best is None or candidate[0] > best[0] or (candidate[0] == best[0] and allow):
                    best = candidate
        return True if best is None else best[1]

    def crawl_delay(self, agent_token: str) -> float | None:
        group = self._group_for(agent_token)
        return group.crawl_delay if group else None
