"""Client-facing wording: issue texts, category and area labels (SK / CS / EN)."""

from __future__ import annotations

from typing import Any

from .config import Config
from .models import Area, Category, ScanResult, Status

LANGUAGES = ("sk", "cs", "en")


def _pick(entry: dict[str, Any] | None, lang: str) -> Any:
    if not entry:
        return None
    return entry.get(lang) or entry.get("en")


def issue_text(config: Config, check_id: str, lang: str, status: Status | None = None) -> dict[str, str] | None:
    """``{"label", "problem", "impact", "solution"}`` for one check, or None.

    A ``warn`` block in the texts overrides the wording when the check only warned.
    """
    entry = _pick(config.texts["issues"].get(check_id), lang)
    if entry is None:
        return None
    text = {k: v for k, v in entry.items() if k != "warn"}
    if status is Status.WARN and isinstance(entry.get("warn"), dict):
        text.update(entry["warn"])
    return text


def check_label(config: Config, check_id: str, lang: str = "en") -> str:
    text = issue_text(config, check_id, lang)
    return text["label"] if text else check_id


def category_label(config: Config, category: Category | str, lang: str = "en") -> str:
    key = category.value if isinstance(category, Category) else category
    return _pick(config.texts["categories"].get(key), lang) or key


def area_label(config: Config, area: Area | str, lang: str = "en") -> str:
    key = area.value if isinstance(area, Area) else area
    return _pick(config.texts["areas"].get(key), lang) or key


def client_issues(result: ScanResult, config: Config, lang: str) -> list[dict[str, Any]]:
    """Issues ordered by impact, each with the three-part client text."""
    out = []
    for issue in result.issues:
        text = issue_text(config, issue.check_id, lang, issue.status)
        if text is None:
            continue
        out.append({"check_id": issue.check_id, "status": issue.status.value, "impact": issue.impact, **text})
    return out
