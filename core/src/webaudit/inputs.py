"""Input handling: URL normalisation and CSV import.

CSV columns (header names are matched loosely, SK or EN):
``url``, ``nazov_firmy`` (optional), ``konkurencia`` (optional, URLs separated
by commas), ``projekt``. A row without a URL becomes a "no website" lead.
"""

from __future__ import annotations

import csv
import io
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

COLUMN_ALIASES = {
    "url": {"url", "web", "website", "stranka", "domain", "domena"},
    "company": {"nazov_firmy", "nazov firmy", "firma", "nazov", "company", "company_name", "name", "nazev_firmy", "nazev firmy"},
    "competitors": {"konkurencia", "konkurence", "competitors", "competition"},
    "project": {"projekt", "project"},
}


def normalize_url(raw: str) -> str:
    """Return a canonical absolute http(s) URL or raise ValueError."""
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("empty URL")
    if "://" not in raw:
        raw = "https://" + raw.lstrip("/")
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError(f"unsupported scheme {parts.scheme}")
    host = (parts.hostname or "").strip(".")
    if not host or (" " in host):
        raise ValueError("missing or invalid host")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("invalid international domain name") from exc
    if "." not in host and host != "localhost":
        raise ValueError("host must be a domain name")
    netloc = host + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))


def _key(name: str) -> str:
    stripped = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    return stripped.strip().lower()


@dataclass
class SiteInput:
    url: str | None
    company: str | None = None
    competitors: list[str] = field(default_factory=list)
    project: str | None = None
    error: str | None = None  # set when the URL column is filled but invalid

    @property
    def has_website(self) -> bool:
        return self.url is not None


def parse_csv_text(text: str) -> list[SiteInput]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    mapping: dict[str, str] = {}
    for column in reader.fieldnames or []:
        for target, aliases in COLUMN_ALIASES.items():
            if _key(column) in aliases and target not in mapping:
                mapping[target] = column
    if "url" not in mapping and "company" not in mapping:
        raise ValueError("CSV needs a 'url' or 'nazov_firmy' column")
    rows: list[SiteInput] = []
    for row in reader:

        def get(target: str, row: dict[str, str] = row) -> str:
            return (row.get(mapping[target]) or "").strip() if target in mapping else ""

        raw_url, company = get("url"), get("company")
        if not raw_url and not company:
            continue
        item = SiteInput(url=None, company=company or None, project=get("project") or None)
        if raw_url:
            try:
                item.url = normalize_url(raw_url)
            except ValueError as exc:
                item.error = f"invalid URL “{raw_url}”: {exc}"
        for competitor in get("competitors").replace(";", ",").split(","):
            if competitor.strip():
                try:
                    item.competitors.append(normalize_url(competitor))
                except ValueError:
                    continue
        rows.append(item)
    return rows


def read_csv(path: str | Path) -> list[SiteInput]:
    data = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1250"):
        try:
            return parse_csv_text(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    return parse_csv_text(data.decode("utf-8", errors="replace"))
