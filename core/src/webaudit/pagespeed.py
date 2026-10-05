"""Google PageSpeed Insights API v5 client.

Docs / how to get a key: https://developers.google.com/speed/docs/insights/v5/get-started
"""

from __future__ import annotations

from typing import Any

import httpx

API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


class PageSpeedError(Exception):
    pass


async def run(url: str, strategy: str, api_key: str, timeout_s: float = 70) -> dict[str, Any]:
    params = {"url": url, "strategy": strategy, "category": "performance", "key": api_key}
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        try:
            response = await client.get(API_URL, params=params)
        except httpx.HTTPError as exc:
            raise PageSpeedError(f"PageSpeed request failed: {exc.__class__.__name__}") from exc
    if response.status_code == 400 and "API key not valid" in response.text:
        raise PageSpeedError("PageSpeed API key is not valid")
    if response.status_code == 429:
        raise PageSpeedError("PageSpeed quota exceeded")
    if response.status_code != 200:
        message = ""
        try:
            message = response.json().get("error", {}).get("message", "")
        except ValueError:
            pass
        raise PageSpeedError(f"PageSpeed returned {response.status_code} {message[:160]}".strip())
    data = response.json()
    # Keep only what the checks need; full Lighthouse JSON is large.
    lighthouse = data.get("lighthouseResult") or {}
    audits = lighthouse.get("audits") or {}
    keep = ("largest-contentful-paint", "cumulative-layout-shift", "total-blocking-time", "first-contentful-paint", "speed-index")
    return {
        "loadingExperience": data.get("loadingExperience") or {},
        "lighthouseResult": {
            "categories": {"performance": (lighthouse.get("categories") or {}).get("performance") or {}},
            "audits": {k: {"numericValue": (audits.get(k) or {}).get("numericValue")} for k in keep},
        },
    }


async def test_key(api_key: str) -> tuple[bool, str]:
    """Used by the settings screen's “Test key” button."""
    try:
        await run("https://www.google.com/", "desktop", api_key, timeout_s=60)
    except PageSpeedError as exc:
        return False, str(exc)
    return True, "Key is valid"
