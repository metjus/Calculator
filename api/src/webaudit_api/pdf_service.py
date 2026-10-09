"""The client PDF in the API: what the preview screen shows, and the export itself.

The operator decides everything the report says - the language, which problems go in, the
summary paragraph and the three prices - so this module only gathers the defaults and hands
the choices to ``webaudit.pdf``. The three prices are typed by hand (there is no per-problem
price list by design) and the last ones used are kept as the defaults for the next export.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from webaudit import Config
from webaudit.models import ScanResult
from webaudit.pdf import (
    DETAIL_LEVELS,
    OfferOption,
    PdfContent,
    Profile,
    build_html,
    default_offer,
    default_summary,
    issues_for,
    render,
    safe_pdf_name,
)

from .models import AuditSite, Workspace
from .settings import Settings

LANGUAGES = ("sk", "cs", "en")
MAX_LOGO_BYTES = 1_000_000
LOGO_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg", "image/webp": ".webp"}
_render_lock = asyncio.Lock()  # one Chromium at a time; the desktop app has one user


def logo_bytes(workspace: Workspace, settings: Settings) -> bytes | None:
    name = getattr(workspace, "logo", None)
    if not name:
        return None
    path = (settings.data_dir / "branding" / name).resolve()
    if not path.is_file() or not path.is_relative_to((settings.data_dir / "branding").resolve()):
        return None
    return path.read_bytes()


def profile_of(workspace: Workspace, settings: Settings) -> Profile:
    stored = workspace.profile or {}
    return Profile(
        name=stored.get("name", ""),
        company_id=stored.get("company_id", ""),
        phone=stored.get("phone", ""),
        email=stored.get("email", ""),
        logo=logo_bytes(workspace, settings),
    )


def _screenshots(site: AuditSite, settings: Settings) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for name, stored in ((site.result or {}).get("screenshots") or {}).items():
        path = (settings.data_dir / stored).resolve()
        if path.is_file() and path.is_relative_to(settings.data_dir.resolve()):
            out[name] = path.read_bytes()
    return out


def content_for(
    site: AuditSite,
    workspace: Workspace,
    settings: Settings,
    config: Config,
    *,
    language: str,
    competitors: list[dict[str, Any]],
    client_name: str | None = None,
) -> PdfContent:
    return PdfContent(
        result=ScanResult.model_validate(site.result or {}),
        profile=profile_of(workspace, settings),
        language=language if language in LANGUAGES else "sk",
        client_name=client_name,
        competitors=[{"domain": row["domain"], "score": row.get("score")} for row in competitors if row.get("score") is not None],
        screenshots=_screenshots(site, settings),
    )


def stored_offer(workspace: Workspace) -> list[dict[str, Any]]:
    return list(getattr(workspace, "pdf_offer", None) or [])


def offer_defaults(content: PdfContent, config: Config, workspace: Workspace) -> list[OfferOption]:
    """Last time's three options when there are any, otherwise the wording from texts.json."""
    options = default_offer(content, config, issues_for(content, config))
    for option, saved in zip(options, stored_offer(workspace), strict=False):
        option.title = saved.get("title") or option.title
        option.price = saved.get("price") or option.price
        option.description = saved.get("description") or option.description
        option.recommended = bool(saved.get("recommended", option.recommended))
    return options


def preview(content: PdfContent, config: Config, workspace: Workspace) -> dict[str, Any]:
    """What the preview screen needs: the problems to tick, the summary and the three options."""
    issues = issues_for(content, config)
    return {
        "language": content.language,
        "languages": list(LANGUAGES),
        "detail": workspace.pdf_detail or content.detail,
        "details": list(DETAIL_LEVELS),
        "client_name": content.client_name,
        "summary": default_summary(content, config, len(issues)),
        "issues": issues,
        "offer": [vars(option) for option in offer_defaults(content, config, workspace)],
        "competitors": content.competitors,
        "screenshots": sorted(content.screenshots),
        "profile": {k: v for k, v in vars(content.profile).items() if k != "logo"},
        "has_logo": content.profile.logo is not None,
        "file_name": safe_pdf_name(content),
    }


async def make_pdf(content: PdfContent, config: Config) -> bytes:
    html = build_html(content, config)
    async with _render_lock:
        return await render(html)


def save_logo(data: bytes, content_type: str, settings: Settings) -> str:
    """Keep the logo next to the data folder and return the file name stored on the workspace."""
    suffix = LOGO_TYPES[content_type]
    folder = settings.data_dir / "branding"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("logo.*"):
        old.unlink(missing_ok=True)
    name = f"logo{suffix}"
    (folder / name).write_bytes(data)
    return name


def delete_logo(workspace: Workspace, settings: Settings) -> None:
    name = getattr(workspace, "logo", None)
    if name:
        Path(settings.data_dir / "branding" / name).unlink(missing_ok=True)
