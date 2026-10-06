"""External data sources. Only name, location, category and website are taken from
either source – never phone numbers, e-mails or people's names."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import OSM_ATTRIBUTION  # noqa: F401  (re-exported for callers)

log = logging.getLogger(__name__)

OSM_AREA_OFFSET = 3_600_000_000  # Overpass area id = relation id + this offset
PLACE_TYPES = {"city", "town", "village", "locality", "district"}
REGION_TYPES = {"county", "state"}


class ProviderError(Exception):
    """A data source failed; the message is safe to show to the user."""


@dataclass
class Area:
    """Where to search: a circle around a place, or a whole region (okres / kraj)."""

    label: str
    lat: float
    lon: float
    radius_km: float | None = None  # set for circle searches
    bbox: tuple[float, float, float, float] | None = None  # (min_lon, min_lat, max_lon, max_lat)
    osm_relation: int | None = None  # set for region searches

    @property
    def is_region(self) -> bool:
        return self.radius_km is None

    def rectangle(self) -> tuple[float, float, float, float]:
        """Bounding box (min_lon, min_lat, max_lon, max_lat) for Google's locationRestriction."""
        if self.is_region and self.bbox:
            return self.bbox
        radius = self.radius_km or 10
        dlat = radius / 111.32
        dlon = radius / (111.32 * max(math.cos(math.radians(self.lat)), 0.01))
        return (self.lon - dlon, self.lat - dlat, self.lon + dlon, self.lat + dlat)

    def contains(self, lat: float, lon: float) -> bool:
        if self.is_region:
            if not self.bbox:
                return True
            min_lon, min_lat, max_lon, max_lat = self.bbox
            return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat
        return distance_km(self.lat, self.lon, lat, lon) <= (self.radius_km or 0) + 0.05


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


@dataclass
class Business:
    source: str  # "google" | "osm"
    name: str
    lat: float
    lon: float
    website: str | None = None
    category: str | None = None
    place_id: str | None = None
    osm_id: str | None = None
    osm_name: str | None = None  # OpenStreetMap name (storable under ODbL)
    extra_sources: list[str] = field(default_factory=list)


def _website(value: str | None) -> str | None:
    value = (value or "").strip().split(";")[0].strip()
    if not value:
        return None
    if "://" not in value:
        value = "https://" + value
    return value if value.startswith(("http://", "https://")) else None


# ------------------------------------------------------------------ Photon (areas)


class Photon:
    """Place autocomplete from OpenStreetMap data (komoot Photon); free, no key."""

    def __init__(self, client: httpx.AsyncClient, url: str) -> None:
        self.client, self.url = client, url

    async def suggest(self, text: str, country: str, limit: int = 8) -> list[dict[str, Any]]:
        params = [("q", text), ("limit", "25"), ("lang", "default")]
        params += [("layer", layer) for layer in ("city", "district", "locality", "county", "state")]
        try:
            response = await self.client.get(self.url, params=params)
            response.raise_for_status()
            features = response.json().get("features", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("Place search is not available right now") from exc
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for feature in features:
            props = feature.get("properties") or {}
            if (props.get("countrycode") or "").lower() != country:
                continue
            kind = "region" if props.get("type") in REGION_TYPES else "place"
            if kind == "place" and props.get("type") not in PLACE_TYPES:
                continue
            name = props.get("name") or ""
            parts = [name]
            if kind == "place" and props.get("county") and props.get("county") != name:
                parts.append(props["county"])
            if props.get("state") and props.get("state") != name:
                parts.append(props["state"])
            parts.append(props.get("country") or country.upper())
            label = ", ".join(p for p in parts if p)
            if label in seen:
                continue
            seen.add(label)
            lon, lat = (feature.get("geometry") or {}).get("coordinates", [None, None])[:2]
            extent = props.get("extent")  # [min_lon, max_lat, max_lon, min_lat]
            bbox = (extent[0], extent[3], extent[2], extent[1]) if extent and len(extent) == 4 else None
            relation = props.get("osm_id") if props.get("osm_type") == "R" else None
            out.append(
                {
                    "id": f"osm:{props.get('osm_type')}{props.get('osm_id')}",
                    "label": label,
                    "kind": kind,
                    "lat": lat,
                    "lon": lon,
                    "bbox": bbox,
                    "osm_relation": relation,
                }
            )
            if len(out) >= limit:
                break
        return out


# ------------------------------------------------------------ Overpass (businesses)


class Overpass:
    """Businesses from OpenStreetMap; ODbL data that may be stored with attribution.

    The public Overpass servers are volunteer-run and often busy (429/504), so the
    query goes to each of ``urls`` in turn until one answers.
    """

    # Overpass turns queries away with 504 when it is busy, the more readily the more time and
    # memory they reserve; its docs advise lowering timeout and maxsize (default 180 s, 512 MiB).
    SETTINGS = "[out:json][timeout:20][maxsize:67108864]"
    TIMEOUT = httpx.Timeout(10.0, read=35.0)  # the query itself may run 20 s on the server

    def __init__(self, client: httpx.AsyncClient, urls: str | list[str]) -> None:
        self.client = client
        self.urls = [u.strip() for u in urls.split(",")] if isinstance(urls, str) else list(urls)
        self.urls = [u for u in self.urls if u]

    @staticmethod
    def build_query(area: Area, tags: list[list[str]], name_regex: str | None) -> str:
        if area.is_region and area.osm_relation:
            prefix, scope = f"area(id:{OSM_AREA_OFFSET + int(area.osm_relation)})->.a;", "(area.a)"
        else:
            # A bounding box is Overpass's cheapest filter (``around`` on ways is costly);
            # merge() then drops what lies outside the circle.
            min_lon, min_lat, max_lon, max_lat = area.rectangle()
            prefix, scope = "", f"({min_lat:.5f},{min_lon:.5f},{max_lat:.5f},{max_lon:.5f})"
        selectors = []
        if name_regex:
            safe = name_regex.replace("\\", "").replace('"', "")
            for key in ("shop", "craft", "office", "amenity", "tourism", "leisure", "healthcare"):
                selectors.append(f'nwr["name"~"{safe}",i]["{key}"]{scope};')
        for key, value in tags:
            selectors.append(f'nwr["{key}"="{value}"]{scope};')
        return f"{Overpass.SETTINGS};{prefix}({''.join(selectors)});out center tags 400;"

    async def search(self, area: Area, tags: list[list[str]], name_regex: str | None, category_label: str | None) -> list[Business]:
        elements = await self._query(self.build_query(area, tags, name_regex))
        out: list[Business] = []
        for element in elements:
            tags_ = element.get("tags") or {}
            name = tags_.get("name")
            lat = element.get("lat") or (element.get("center") or {}).get("lat")
            lon = element.get("lon") or (element.get("center") or {}).get("lon")
            if not name or lat is None or lon is None:
                continue
            out.append(
                Business(
                    source="osm",
                    name=name,
                    lat=float(lat),
                    lon=float(lon),
                    website=_website(tags_.get("website") or tags_.get("contact:website") or tags_.get("url")),
                    category=category_label,
                    osm_id=f"{element.get('type')}/{element.get('id')}",
                    osm_name=name,
                )
            )
        return out

    async def _query(self, query: str) -> list[dict[str, Any]]:
        failures: list[str] = []
        for url in self.urls:
            host = httpx.URL(url).host
            try:
                response = await self.client.post(url, data={"data": query}, headers={"Accept": "application/json"}, timeout=self.TIMEOUT)
            except httpx.HTTPError as exc:
                failures.append(f"{host}: {exc.__class__.__name__}")
                log.warning("Overpass %s failed: %r", host, exc)
                continue
            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError:
                    failures.append(f"{host}: not JSON")
                    log.warning("Overpass %s answered something other than JSON: %.200s", host, response.text)
                    continue
                remark = data.get("remark") or ""
                if "out of memory" in remark:  # every server would say the same
                    log.warning("Overpass %s: %s", host, remark)
                    raise ProviderError("This area is too large for an OpenStreetMap search; choose a smaller radius or a district")
                if not data.get("elements") and ("runtime error" in remark or "timed out" in remark):
                    failures.append(f"{host}: {remark[:80]}")
                    log.warning("Overpass %s: %s", host, remark)
                    continue
                return data.get("elements", [])
            failures.append(f"{host}: HTTP {response.status_code}")
            log.warning("Overpass %s answered %s: %.300s", host, response.status_code, response.text)
            if response.status_code == 400:  # our query is wrong; another server will say the same
                break
        detail = "; ".join(failures) or "no server configured"
        raise ProviderError(f"OpenStreetMap search is not available right now ({detail})")


# ------------------------------------------------------------- Google Places (New)


class GooglePlaces:
    FIELDS = "places.id,places.displayName,places.location,places.websiteUri,places.primaryTypeDisplayName,nextPageToken"

    def __init__(self, client: httpx.AsyncClient, base_url: str, key: str) -> None:
        self.client, self.base_url, self.key = client, base_url, key
        self.requests = 0  # billed Text Search requests made by this instance

    async def text_search(
        self,
        area: Area,
        *,
        query: str,
        included_type: str | None,
        country: str,
        language: str,
        max_pages: int,
    ) -> list[Business]:
        min_lon, min_lat, max_lon, max_lat = area.rectangle()
        body: dict[str, Any] = {
            "textQuery": query,
            "languageCode": language,
            "regionCode": country.upper(),
            "pageSize": 20,
            "locationRestriction": {
                "rectangle": {"low": {"latitude": min_lat, "longitude": min_lon}, "high": {"latitude": max_lat, "longitude": max_lon}}
            },
        }
        if included_type:
            body["includedType"] = included_type
            body["strictTypeFiltering"] = True
        headers = {"X-Goog-Api-Key": self.key, "X-Goog-FieldMask": self.FIELDS}
        out: list[Business] = []
        for _page in range(max_pages):
            try:
                response = await self.client.post(f"{self.base_url}/places:searchText", headers=headers, json=body)
            except httpx.HTTPError as exc:
                raise ProviderError("Google Places is not available right now") from exc
            self.requests += 1
            if response.status_code != 200:
                raise ProviderError(_google_error(response))
            data = response.json()
            for place in data.get("places", []):
                location = place.get("location") or {}
                if "latitude" not in location:
                    continue
                out.append(
                    Business(
                        source="google",
                        name=(place.get("displayName") or {}).get("text") or "",
                        lat=location["latitude"],
                        lon=location["longitude"],
                        website=_website(place.get("websiteUri")),
                        category=(place.get("primaryTypeDisplayName") or {}).get("text"),
                        place_id=place.get("id"),
                    )
                )
            token = data.get("nextPageToken")
            if not token:
                break
            body["pageToken"] = token
        return out


def _google_error(response: httpx.Response) -> str:
    text = response.text
    if "API key not valid" in text or "API_KEY_INVALID" in text:
        return "Google Places API key is not valid (Settings)"
    if "has not been used" in text or "SERVICE_DISABLED" in text:
        return "Enable “Places API (New)” for your Google key"
    if response.status_code == 429:
        return "Google Places quota exceeded"
    return f"Google Places answered {response.status_code}"
