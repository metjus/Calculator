"""Service configuration from environment variables (WEBAUDIT_*)."""

from __future__ import annotations

import os
import secrets
import warnings
from dataclasses import dataclass, field
from pathlib import Path

# Model used for the AI design review (stage 4); the Claude "Test key" checks access to it.
CLAUDE_MODEL = "claude-opus-5-5"


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


SECRET_FILE = "secret.key"
DEFAULT_OVERPASS = ",".join(
    [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]
)


def _secret_key() -> str:
    """WEBAUDIT_SECRET_KEY, else a key kept in the data folder (created on first start).

    The data folder is outside Git (.gitignore), so a self-hosted install keeps its
    sessions and encrypted API keys across restarts without any setup.
    """
    key = os.environ.get("WEBAUDIT_SECRET_KEY")
    if key:
        return key
    path = Path(os.environ.get("WEBAUDIT_DATA_DIR", "./data")) / SECRET_FILE
    try:
        if path.is_file():
            stored = path.read_text("utf-8").strip()
            if stored:
                return stored
        path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(48)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(key)
        return key
    except FileExistsError:
        return path.read_text("utf-8").strip()  # another process (the worker) created it first
    except OSError as exc:
        warnings.warn(
            f"WEBAUDIT_SECRET_KEY is not set and {path} is not writable ({exc}); using a random key. "
            "Sessions and stored API keys will not survive a restart.",
            stacklevel=2,
        )
        return secrets.token_urlsafe(48)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get("WEBAUDIT_DATABASE_URL", "sqlite+aiosqlite:///./webaudit.db"))
    secret_key: str = field(default_factory=_secret_key)
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("WEBAUDIT_DATA_DIR", "./data")))
    # Run the audit worker inside the API process (development / single-node).
    inprocess_worker: bool = field(default_factory=lambda: _bool("WEBAUDIT_INPROCESS_WORKER", True))
    # Only for local testing against private addresses; never enable in production.
    allow_private_targets: bool = field(default_factory=lambda: _bool("WEBAUDIT_ALLOW_PRIVATE_TARGETS", False))
    cookie_secure: bool = field(default_factory=lambda: _bool("WEBAUDIT_COOKIE_SECURE", False))
    signup_enabled: bool = field(default_factory=lambda: _bool("WEBAUDIT_SIGNUP_ENABLED", True))
    scan_concurrency: int = field(default_factory=lambda: int(os.environ.get("WEBAUDIT_SCAN_CONCURRENCY", "2")))
    max_urls_per_audit: int = field(default_factory=lambda: int(os.environ.get("WEBAUDIT_MAX_URLS_PER_AUDIT", "200")))
    session_days: int = 30
    # Base URLs of external services (overridable for tests).
    google_places_base: str = "https://places.googleapis.com/v1"
    # Overpass servers, comma-separated, tried in order (the public ones are often busy).
    overpass_url: str = field(default_factory=lambda: os.environ.get("WEBAUDIT_OVERPASS_URL", DEFAULT_OVERPASS))
    photon_url: str = field(default_factory=lambda: os.environ.get("WEBAUDIT_PHOTON_URL", "https://photon.komoot.io/api/"))
    # Desktop app (webaudit_desktop): one local user, signed in with a per-launch token instead of a password.
    local_mode: bool = field(default_factory=lambda: _bool("WEBAUDIT_LOCAL_MODE", False))
    local_token: str | None = field(default_factory=lambda: os.environ.get("WEBAUDIT_LOCAL_TOKEN") or None)
    # Map preview tiles. The browser loads them from /api/search/tiles, which fetches them from this
    # server with an identifying User-Agent and caches them in <data>/tiles, as the OSM tile usage
    # policy asks. Use your own tile provider for a busy SaaS deployment.
    map_tile_url: str = field(
        default_factory=lambda: os.environ.get("WEBAUDIT_MAP_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    )
    map_attribution: str = field(
        default_factory=lambda: os.environ.get(
            "WEBAUDIT_MAP_ATTRIBUTION", '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        )
    )
    # Shown in the sidebar so a screenshot tells which build is running; the desktop launcher sets it.
    build: str | None = field(default_factory=lambda: os.environ.get("WEBAUDIT_BUILD") or None)
