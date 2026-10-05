"""Business search: areas from OpenStreetMap (Photon), businesses from Google Places and OpenStreetMap (Overpass)."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

COUNTRIES = [
    {"code": "sk", "name": "Slovakia", "language": "sk"},
    {"code": "cz", "name": "Czechia", "language": "cs"},
    {"code": "at", "name": "Austria", "language": "en"},
    {"code": "hu", "name": "Hungary", "language": "en"},
    {"code": "pl", "name": "Poland", "language": "en"},
    {"code": "de", "name": "Germany", "language": "en"},
    {"code": "si", "name": "Slovenia", "language": "en"},
    {"code": "hr", "name": "Croatia", "language": "en"},
]
COUNTRY_CODES = {c["code"] for c in COUNTRIES}
OSM_ATTRIBUTION = "© OpenStreetMap contributors (ODbL)"


@cache
def _load(name: str) -> dict[str, Any]:
    return json.loads(resources.files(__package__).joinpath(name).read_text("utf-8"))


def categories() -> list[dict[str, Any]]:
    return _load("categories.json")["categories"]


def category(category_id: str) -> dict[str, Any] | None:
    return next((c for c in categories() if c["id"] == category_id), None)


def pricing() -> dict[str, Any]:
    return _load("pricing.json")


def country_language(code: str) -> str:
    return next((c["language"] for c in COUNTRIES if c["code"] == code), "en")
