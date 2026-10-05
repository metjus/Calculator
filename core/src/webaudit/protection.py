"""Detect sites that refuse automated access (Cloudflare challenge and similar).

Such sites get the state ``protected``: no score, excluded from statistics,
shown separately with "Probably protected by Cloudflare – check manually".
"""

from __future__ import annotations

from typing import Any

from .models import Protection

BLOCKING_STATUSES = {401, 403, 405, 409, 429, 503}


def _header_hits(headers: dict[str, str], markers: list[str]) -> list[str]:
    hits = []
    for marker in markers:
        if ":" in marker:
            name, needle = (part.strip() for part in marker.split(":", 1))
            if needle.lower() in headers.get(name, "").lower():
                hits.append(marker)
        elif marker in headers:
            hits.append(f"header {marker}")
    return hits


def detect(status: int | None, headers: dict[str, str], body: str, signatures: dict[str, Any]) -> Protection | None:
    """Return a Protection when the response looks like a firewall block or challenge."""
    lowered = body[:60_000].lower()
    server = headers.get("server", "").lower()
    blocked = status in BLOCKING_STATUSES
    for provider, rules in signatures["protection"].items():
        evidence = _header_hits(headers, rules.get("headers", []))
        if rules.get("server") and rules["server"] in server:
            evidence.append(f"server: {server}")
        if headers.get("cf-mitigated", "").lower() == "challenge" and provider == "cloudflare":
            return Protection(provider=provider, evidence=evidence + ["cf-mitigated: challenge"])
        # "challenge_body" markers appear only on interstitial pages; "body" markers can also
        # appear on normal pages (e.g. Cloudflare injects challenge-platform scripts), so they
        # count only together with a blocking status.
        strong = [m for m in rules.get("challenge_body", []) if m in lowered]
        weak = [m for m in rules.get("body", []) if m in lowered]
        if (blocked and (evidence or strong or weak)) or (strong and evidence):
            return Protection(provider=provider, evidence=(evidence + [f"page contains “{m}”" for m in strong + weak])[:6])
    return None


def detect_in_title(title: str) -> bool:
    lowered = title.strip().lower()
    return lowered in ("just a moment...", "attention required! | cloudflare", "access denied", "one moment, please...")
