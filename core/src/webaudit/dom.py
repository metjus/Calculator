"""HTML helpers working on BeautifulSoup trees."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

NON_CONTENT_TAGS = {"script", "style", "noscript", "template", "svg", "head", "title", "meta", "link"}


def parse(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "lxml")


def visible_text(node: Tag | BeautifulSoup) -> str:
    parts = []
    for string in node.find_all(string=True):
        if any(parent.name in NON_CONTENT_TAGS for parent in string.parents if isinstance(parent, Tag)):
            continue
        text = string.strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def bare_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_site(url: str, base: str) -> bool:
    return bare_host(url) == bare_host(base)


def normalize_link(href: str, base_url: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:", "sms:", "whatsapp:", "viber:")):
        return None
    absolute = urljoin(base_url, href)
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https"):
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def anchors(soup: BeautifulSoup) -> Iterator[Tag]:
    yield from soup.find_all("a", href=True)


def meta_content(soup: BeautifulSoup, *, name: str | None = None, prop: str | None = None) -> str | None:
    for tag in soup.find_all("meta"):
        if name and (tag.get("name") or "").strip().lower() == name:
            return (tag.get("content") or "").strip()
        if prop and (tag.get("property") or "").strip().lower() == prop:
            return (tag.get("content") or "").strip()
    return None


def json_ld_types(soup: BeautifulSoup) -> list[str]:
    """All schema.org ``@type`` values from JSON-LD blocks and microdata."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            kind = node.get("@type")
            if isinstance(kind, str):
                found.append(kind)
            elif isinstance(kind, list):
                found.extend(k for k in kind if isinstance(k, str))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for script in soup.find_all("script", type=lambda t: t and "ld+json" in t.lower()):
        try:
            walk(json.loads(script.string or script.get_text() or ""))
        except (ValueError, TypeError):
            continue
    for tag in soup.find_all(itemtype=True):
        itemtype = str(tag.get("itemtype"))
        for value in itemtype.split():
            found.append(value.rstrip("/").rsplit("/", 1)[-1])
    return found


def class_and_id(tag: Tag) -> str:
    classes = tag.get("class") or []
    if isinstance(classes, str):
        classes = [classes]
    return " ".join([*classes, str(tag.get("id") or "")]).lower()


_IDENT = re.compile(r"-?[A-Za-z_][\w-]*")


def css_path(tag: Tag, depth: int = 6) -> str:
    """A short CSS selector that locates ``tag`` (stops at the nearest id), e.g. ``div#main > p.note:nth-of-type(2)``.

    Mirrors ``cssPath`` in browser.py so static and rendered evidence read the same.
    """
    parts: list[str] = []
    node: Tag | None = tag
    while isinstance(node, Tag) and node.name not in ("[document]", "html") and len(parts) < depth:
        node_id = node.get("id")
        if isinstance(node_id, str) and _IDENT.fullmatch(node_id):
            parts.append(f"{node.name}#{node_id}")
            break
        part = node.name
        classes = [c for c in (node.get("class") or []) if _IDENT.fullmatch(c)][:2]
        if classes:
            part += "." + ".".join(classes)
        parent = node.parent
        if isinstance(parent, Tag):
            siblings = parent.find_all(node.name, recursive=False)
            if len(siblings) > 1:
                position = next(i for i, sibling in enumerate(siblings, start=1) if sibling is node)
                part += f":nth-of-type({position})"
        parts.append(part)
        if node.name == "body":
            break
        node = parent
    return " > ".join(reversed(parts))
