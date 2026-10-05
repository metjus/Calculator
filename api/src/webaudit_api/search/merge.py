"""Combine Google and OpenStreetMap results and drop duplicates (same domain, or same name nearby)."""

from __future__ import annotations

import re
import unicodedata

from webaudit.dom import bare_host

from .providers import Area, Business, distance_km

LEGAL_SUFFIXES = re.compile(r"\b(s\.?\s?r\.?\s?o\.?|spol\.?|a\.?\s?s\.?|k\.?\s?s\.?|v\.?\s?o\.?\s?s\.?|gmbh|ltd|inc)\b")
SAME_PLACE_KM = 0.25


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = LEGAL_SUFFIXES.sub(" ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def merge(google: list[Business], osm: list[Business], area: Area) -> list[dict]:
    merged: list[Business] = []
    by_domain: dict[str, Business] = {}
    by_place_id: set[str] = set()
    for item in [*google, *osm]:  # Google first: its names and categories are usually more current
        if not area.contains(item.lat, item.lon):
            continue
        if item.place_id and item.place_id in by_place_id:
            continue
        domain = bare_host(item.website) if item.website else None
        twin = by_domain.get(domain) if domain else None
        if twin is None:
            key = normalize_name(item.name)
            twin = next(
                (
                    m
                    for m in merged
                    if m.source != item.source
                    and normalize_name(m.name) == key
                    and distance_km(m.lat, m.lon, item.lat, item.lon) <= SAME_PLACE_KM
                ),
                None,
            )
        if twin is not None:
            twin.website = twin.website or item.website
            twin.osm_id = twin.osm_id or item.osm_id
            twin.osm_name = twin.osm_name or item.osm_name
            twin.place_id = twin.place_id or item.place_id
            if item.source not in twin.extra_sources and item.source != twin.source:
                twin.extra_sources.append(item.source)
            if twin.website:
                by_domain.setdefault(bare_host(twin.website), twin)
            continue
        merged.append(item)
        if item.place_id:
            by_place_id.add(item.place_id)
        if domain:
            by_domain[domain] = item
    out = []
    for item in merged:
        sources = [item.source, *item.extra_sources]
        out.append(
            {
                "key": item.place_id or item.osm_id or f"{item.name}@{item.lat:.5f},{item.lon:.5f}",
                "name": item.name,
                # Only OpenStreetMap names may be stored (Google: place_id only, see models.py).
                "osm_name": item.osm_name,
                "website": item.website,
                "domain": bare_host(item.website) if item.website else None,
                "category": item.category,
                "lat": round(item.lat, 6),
                "lon": round(item.lon, 6),
                "distance_km": None if area.is_region else round(distance_km(area.lat, area.lon, item.lat, item.lon), 1),
                "place_id": item.place_id,
                "osm_id": item.osm_id,
                "sources": sources,
            }
        )
    out.sort(key=lambda r: (r["distance_km"] if r["distance_km"] is not None else 0, r["name"].lower()))
    return out
