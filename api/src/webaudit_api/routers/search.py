"""Business search by category and area, with Google Places and OpenStreetMap combined."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from webaudit.inputs import SiteInput, normalize_url

from .. import __version__
from ..audit_service import AuditRequest, create_audit
from ..companies import get_or_create_company
from ..deps import current_user, get_db, get_keybox, get_settings
from ..keys import get_key
from ..models import ApiUsage, Audit, AuditSite, Company, SearchTemplate, User
from ..search import COUNTRIES, COUNTRY_CODES, OSM_ATTRIBUTION, categories, category, country_language, pricing
from ..search.merge import merge
from ..search.providers import Area, Business, GooglePlaces, Overpass, Photon, ProviderError
from ..security import KeyBox
from ..settings import Settings
from .audits import CreateResult, created_response

router = APIRouter(prefix="/api/search", tags=["search"])
log = logging.getLogger(__name__)
SKU = "text_search_enterprise"
# OSM services ask for a User-Agent that names the application and where to find it.
USER_AGENT = f"WebAudit/{__version__} (+https://github.com/metjus/Calculator)"
TILE_PATH = "/api/search/tiles/{z}/{x}/{y}"
TILE_REFRESH_DAYS = 30
TILE_BROWSER_CACHE = 7 * 24 * 3600


# ------------------------------------------------------------------ schemas


class AreaIn(BaseModel):
    label: str = Field(max_length=300)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    kind: Literal["place", "region"] = "place"
    bbox: tuple[float, float, float, float] | None = None
    osm_relation: int | None = None


class SearchParams(BaseModel):
    country: str
    area: AreaIn
    mode: Literal["radius", "region"] = "radius"
    radius_km: float = Field(default=15, ge=1, le=50)
    category_id: str | None = None
    query: str | None = Field(default=None, max_length=80)
    sources: list[Literal["google", "osm"]] = Field(default_factory=lambda: ["google", "osm"])

    @model_validator(mode="after")
    def _check(self) -> SearchParams:
        if self.country not in COUNTRY_CODES:
            raise ValueError("Choose a country")
        if not self.category_id and not (self.query or "").strip():
            raise ValueError("Choose a category or type what to search for")
        if self.category_id and category(self.category_id) is None:
            raise ValueError("Unknown category")
        if self.mode == "region" and not (self.area.osm_relation or self.area.bbox):
            raise ValueError("Pick a district or region for a whole-region search")
        return self

    def to_area(self) -> Area:
        return Area(
            label=self.area.label,
            lat=self.area.lat,
            lon=self.area.lon,
            radius_km=None if self.mode == "region" else self.radius_km,
            bbox=self.area.bbox,
            osm_relation=self.area.osm_relation,
        )


class Estimate(BaseModel):
    google_configured: bool
    google_requests_max: int
    price_per_1000: float
    estimated_cost_usd: float
    used_this_month: int
    free_per_month: int
    over_free_limit: bool
    message: str


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    params: SearchParams


class SearchItem(BaseModel):
    website: str | None = Field(default=None, max_length=2048)
    place_id: str | None = Field(default=None, max_length=255)
    osm_id: str | None = Field(default=None, max_length=64)
    osm_name: str | None = Field(default=None, max_length=300)


class SendItems(BaseModel):
    project: str | None = Field(default=None, max_length=200)
    items: list[SearchItem] = Field(min_length=1, max_length=500)


# ------------------------------------------------------------------ helpers


def _client(request: Request) -> httpx.AsyncClient:
    transport = getattr(request.app.state, "search_transport", None)
    return httpx.AsyncClient(timeout=30.0, transport=transport, headers={"User-Agent": USER_AGENT})


def _month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


async def _usage(db: AsyncSession, workspace_id: int) -> int:
    used = await db.scalar(
        select(ApiUsage.count).where(ApiUsage.workspace_id == workspace_id, ApiUsage.month == _month(), ApiUsage.sku == SKU)
    )
    return used or 0


async def _add_usage(db: AsyncSession, workspace_id: int, requests: int) -> None:
    if not requests:
        return
    row = await db.scalar(select(ApiUsage).where(ApiUsage.workspace_id == workspace_id, ApiUsage.month == _month(), ApiUsage.sku == SKU))
    if row is None:
        db.add(ApiUsage(workspace_id=workspace_id, month=_month(), sku=SKU, count=requests))
    else:
        row.count += requests
    await db.commit()


def _name_pattern(text: str) -> str:
    # Free text goes into an Overpass regex string; keep letters, digits and simple punctuation only.
    return re.sub(r"[^\w\s&'-]", "", text, flags=re.UNICODE).strip()[:60]


async def _known_companies(db: AsyncSession, workspace_id: int, results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    domains = {r["domain"] for r in results if r["domain"]}
    place_ids = {r["place_id"] for r in results if r["place_id"]}
    osm_ids = {r["osm_id"] for r in results if r["osm_id"]}
    if not (domains or place_ids or osm_ids):
        return {}
    conditions = []
    if domains:
        conditions.append(Company.domain.in_(domains))
    if place_ids:
        conditions.append(Company.place_id.in_(place_ids))
    if osm_ids:
        conditions.append(Company.osm_id.in_(osm_ids))
    companies = list(await db.scalars(select(Company).where(Company.workspace_id == workspace_id, or_(*conditions))))
    latest = {}
    if companies:
        rows = await db.execute(
            select(AuditSite.company_id, func.max(AuditSite.finished_at), func.max(Audit.id))
            .join(Audit)
            .where(AuditSite.company_id.in_([c.id for c in companies]), AuditSite.finished_at.is_not(None))
            .group_by(AuditSite.company_id)
        )
        latest = {company_id: finished for company_id, finished, _ in rows}
    known: dict[str, dict[str, Any]] = {}
    for company in companies:
        info = {
            "company_id": company.id,
            "do_not_contact": company.do_not_contact,
            "last_audit_at": latest.get(company.id).isoformat() if latest.get(company.id) else None,
        }
        for key in (company.domain, company.place_id, company.osm_id):
            if key:
                known[key] = info
    return known


# ---------------------------------------------------------------- endpoints


@router.get("/options")
async def options(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    keybox: KeyBox = Depends(get_keybox),
    settings: Settings = Depends(get_settings),
) -> dict:
    google = await get_key(db, keybox, user.workspace_id, "google_places")
    return {
        "countries": COUNTRIES,
        "categories": [{"id": c["id"], "label": c["label"]} for c in categories()],
        "google_configured": bool(google),
        "osm_attribution": OSM_ATTRIBUTION,
        "radius_km": {"min": 5, "max": 50, "default": 15},
        "map_tile_url": TILE_PATH,
        "map_attribution": settings.map_attribution,
    }


def _tile_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _fill(template: str, z: int, x: int, y: int) -> str:
    for key, value in {"{z}": z, "{x}": x, "{y}": y, "{s}": "a", "{r}": ""}.items():
        template = template.replace(key, str(value))
    return template


async def _fetch_tile(request: Request, url: str) -> tuple[bytes | None, str]:
    """Download one tile; on failure say why."""
    host = httpx.URL(url).host
    state = request.app.state
    if not hasattr(state, "tile_slots"):
        state.tile_slots = asyncio.Semaphore(2)  # OSM's volunteer servers ask for few parallel downloads
        state.tile_problems = set()
    problem, status_code = "", None
    async with state.tile_slots, _client(request) as client:
        try:
            response = await client.get(url, timeout=15.0)
            status_code = response.status_code
            if status_code == 200 and _tile_type(response.content):
                return response.content, ""
        except httpx.HTTPError as exc:
            problem = f"could not reach {host} ({exc.__class__.__name__})"
    if not problem:
        problem = f"{host} answered HTTP {status_code}"
        if status_code == 403:
            problem = f"{host} refused the map tiles (HTTP 403)"
        elif status_code == 200:
            problem = f"{host} sent something other than a map image"
    if problem not in state.tile_problems:  # once per kind of failure, not once per tile
        state.tile_problems.add(problem)
        log.warning("map tiles: %s", problem)
    return None, problem


@router.get("/tiles/{z}/{x}/{y}")
async def tile(
    z: int,
    x: int,
    y: int,
    request: Request,
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Map preview tile, fetched by the server rather than the browser.

    tile.openstreetmap.org blocks browsers that send no usable Referer, as the desktop window on
    127.0.0.1 does. From here the request carries our User-Agent, and tiles are kept in
    <data>/tiles so each is downloaded once.
    """
    if not (0 <= z <= 18 and 0 <= x < 2**z and 0 <= y < 2**z):
        raise HTTPException(404, "No such tile")
    path = settings.data_dir / "tiles" / str(z) / str(x) / str(y)
    cached = path.read_bytes() if path.is_file() else None
    if cached is None or time.time() - path.stat().st_mtime > TILE_REFRESH_DAYS * 86400:
        fresh, problem = await _fetch_tile(request, _fill(settings.map_tile_url, z, x, y))
        if fresh:
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_name(f"{path.name}.{os.getpid()}.part")
            partial.write_bytes(fresh)
            os.replace(partial, path)
            cached = fresh
        elif cached is None:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, problem)
    return Response(cached, media_type=_tile_type(cached), headers={"Cache-Control": f"private, max-age={TILE_BROWSER_CACHE}"})


@router.get("/areas")
async def areas(
    request: Request,
    country: str = Query(..., min_length=2, max_length=2),
    q: str = Query(..., min_length=2, max_length=100),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    if country not in COUNTRY_CODES:
        raise HTTPException(422, "Choose a country first")
    async with _client(request) as client:
        try:
            return await Photon(client, settings.photon_url).suggest(q, country)
        except ProviderError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post("/estimate", response_model=Estimate)
async def estimate(
    params: SearchParams, user: User = Depends(current_user), db: AsyncSession = Depends(get_db), keybox: KeyBox = Depends(get_keybox)
) -> Estimate:
    price = pricing()
    sku = price["skus"][SKU]
    configured = bool(await get_key(db, keybox, user.workspace_id, "google_places"))
    requests = price["max_pages_per_search"] if configured and "google" in params.sources else 0
    used = await _usage(db, user.workspace_id)
    over = configured and used + requests > sku["free_per_month"]
    cost = round(requests * sku["per_1000"] / 1000, 2)
    if not configured or "google" not in params.sources:
        message = "Only OpenStreetMap will be searched (free)."
    elif over:
        message = f"This may exceed Google's free monthly limit ({sku['free_per_month']} requests); you have used {used}. Up to ~${cost} for this search."
    else:
        message = f"Up to {requests} Google requests (~${cost} if over the free limit); {sku['free_per_month'] - used} free requests left this month."
    return Estimate(
        google_configured=configured,
        google_requests_max=requests,
        price_per_1000=sku["per_1000"],
        estimated_cost_usd=cost,
        used_this_month=used,
        free_per_month=sku["free_per_month"],
        over_free_limit=over,
        message=message,
    )


@router.post("/run")
async def run_search(
    params: SearchParams,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    keybox: KeyBox = Depends(get_keybox),
    settings: Settings = Depends(get_settings),
) -> dict:
    area = params.to_area()
    cat = category(params.category_id) if params.category_id else None
    language = country_language(params.country)
    free_text = (params.query or "").strip()
    google_key = await get_key(db, keybox, user.workspace_id, "google_places") if "google" in params.sources else None
    google_results: list[Business] = []
    osm_results: list[Business] = []
    warnings: list[str] = []
    async with _client(request) as client:
        if google_key:
            places = GooglePlaces(client, settings.google_places_base, google_key)
            try:
                google_results = await places.text_search(
                    area,
                    query=free_text or (cat["query"].get(language) or cat["query"]["en"]),
                    included_type=None if free_text else cat.get("google_type"),
                    country=params.country,
                    language=language,
                    max_pages=pricing()["max_pages_per_search"],
                )
            except ProviderError as exc:
                warnings.append(str(exc))
            await _add_usage(db, user.workspace_id, places.requests)
        elif "google" in params.sources:
            warnings.append("Google Places skipped: add a Google Places API key in Settings")
        if "osm" in params.sources:
            try:
                osm_results = await Overpass(client, settings.overpass_url).search(
                    area,
                    [] if free_text else (cat or {}).get("osm", []),
                    _name_pattern(free_text) or None,
                    None if free_text else cat["label"],
                )
            except ProviderError as exc:
                warnings.append(str(exc))
    results = merge(google_results, osm_results, area)
    known = await _known_companies(db, user.workspace_id, results)
    for item in results:
        item["known"] = next((known[k] for k in (item["domain"], item["place_id"], item["osm_id"]) if k and k in known), None)
    with_site = sum(1 for r in results if r["website"])
    return {
        "results": results,
        "counts": {"total": len(results), "with_website": with_site, "without_website": len(results) - with_site},
        "sources": {"google": len(google_results), "osm": len(osm_results)},
        "attribution": OSM_ATTRIBUTION if osm_results else None,
        "warnings": warnings,
    }


@router.get("/templates")
async def list_templates(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = await db.scalars(select(SearchTemplate).where(SearchTemplate.workspace_id == user.workspace_id).order_by(SearchTemplate.name))
    return [{"id": t.id, "name": t.name, "params": t.params} for t in rows]


@router.post("/templates", status_code=201)
async def save_template(body: TemplateIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    template = SearchTemplate(workspace_id=user.workspace_id, name=body.name.strip(), params=body.params.model_dump(mode="json"))
    db.add(template)
    await db.commit()
    return {"id": template.id, "name": template.name, "params": template.params}


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> None:
    template = await db.get(SearchTemplate, template_id)
    if template is None or template.workspace_id != user.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    await db.delete(template)
    await db.commit()


@router.post("/to-audit", response_model=CreateResult, status_code=201)
async def send_to_audit(
    body: SendItems, user: User = Depends(current_user), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> CreateResult:
    rows: list[SiteInput] = []
    request = AuditRequest(project=(body.project or "").strip() or None, rows=rows)
    for item in body.items:
        if not item.website:
            continue
        try:
            url = normalize_url(item.website)
        except ValueError as exc:
            request.invalid.append({"input": item.website, "error": str(exc)})
            continue
        if item.place_id:
            request.place_ids[len(rows)] = item.place_id
        if item.osm_id:
            request.osm_ids[len(rows)] = item.osm_id
        rows.append(SiteInput(url=url, company=item.osm_name))
    return created_response(await create_audit(db, user.workspace_id, request, max_urls=settings.max_urls_per_audit))


@router.post("/to-leads")
async def send_to_leads(body: SendItems, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """Businesses without a website go to the customer list as leads for a new website."""
    created = 0
    for item in body.items:
        if item.website or not (item.place_id or item.osm_id):
            continue
        await get_or_create_company(
            db,
            user.workspace_id,
            url=None,
            name=item.osm_name,
            project=(body.project or "").strip() or None,
            place_id=item.place_id,
            osm_id=item.osm_id,
        )
        created += 1
    await db.commit()
    return {"leads": created}
