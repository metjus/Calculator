"""Customer API keys (bring your own key): storage helpers and the "Test key" checks."""

from __future__ import annotations

import anthropic
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from webaudit import pagespeed

from .models import ApiKey
from .security import KeyBox
from .settings import CLAUDE_MODEL, Settings

SERVICES = ("pagespeed", "claude", "google_places")


async def get_key(db: AsyncSession, keybox: KeyBox, workspace_id: int, service: str) -> str | None:
    row = await db.scalar(select(ApiKey).where(ApiKey.workspace_id == workspace_id, ApiKey.service == service))
    return keybox.decrypt(row.encrypted) if row else None


async def test_claude(key: str) -> tuple[bool, str]:
    # Retrieving the model costs no tokens and proves both the key and access to the model we use.
    client = anthropic.AsyncAnthropic(api_key=key, max_retries=0, timeout=20.0)
    try:
        await client.models.retrieve(CLAUDE_MODEL)
    except anthropic.AuthenticationError:
        return False, "Key is not valid"
    except anthropic.PermissionDeniedError:
        return False, "Key works but has no access to the Claude model used for design reviews"
    except anthropic.NotFoundError:
        return False, f"Model {CLAUDE_MODEL} is not available for this key"
    except anthropic.RateLimitError:
        return True, "Key is valid (rate limit reached right now)"
    except anthropic.APIConnectionError:
        return False, "Could not reach the Anthropic API, try again"
    except anthropic.APIStatusError as exc:
        return False, f"Anthropic API answered {exc.status_code}"
    finally:
        await client.close()
    return True, "Key is valid"


async def test_google_places(key: str, base_url: str) -> tuple[bool, str]:
    # An IDs-only Text Search is the cheapest call that proves the key and that Places API (New) is enabled.
    headers = {"X-Goog-Api-Key": key, "X-Goog-FieldMask": "places.id"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{base_url}/places:searchText", headers=headers, json={"textQuery": "pizza Bratislava", "pageSize": 1}
            )
    except httpx.HTTPError:
        return False, "Could not reach Google, try again"
    if response.status_code == 200:
        return True, "Key is valid"
    text = response.text
    if "API key not valid" in text or "API_KEY_INVALID" in text:
        return False, "Key is not valid"
    if "has not been used" in text or "is disabled" in text or "SERVICE_DISABLED" in text:
        return False, "Enable “Places API (New)” for this key in Google Cloud Console"
    if response.status_code == 403:
        return False, "Key is not allowed to use Places API (New); check its API restrictions"
    return False, f"Google answered {response.status_code}"


async def test_key(service: str, key: str, settings: Settings) -> tuple[bool, str]:
    if service == "pagespeed":
        return await pagespeed.test_key(key)
    if service == "claude":
        return await test_claude(key)
    return await test_google_places(key, settings.google_places_base)
