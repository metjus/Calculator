"""Remove contact details (e-mail addresses, phone numbers) from text and HTML.

The audit never stores contact data, but page snapshots and the page inventory
(used by the Claude Code export) contain page text. Everything that keeps page
text goes through these functions first. Person names cannot be recognised
reliably and are left as they are.
"""

from __future__ import annotations

import re

EMAIL_MARK = "[e-mail]"
PHONE_MARK = "[phone]"

_FILE_SUFFIX = re.compile(r"\.(png|jpe?g|gif|svg|webp|avif|ico|css|js|mjs|json|xml|pdf|woff2?|ttf|eot|mp4|webm)$", re.I)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+(?:@|&#0*64;|&#x0*40;|%40)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# "info [at] firma.sk", "info(at)firma(dot)sk", "info {zavináč} firma.sk"
_EMAIL_OBFUSCATED = re.compile(
    r"[A-Za-z0-9._%+-]+\s*[\[({]\s*(?:at|zavin[aá][cč])\s*[\])}]\s*[A-Za-z0-9-]+"
    r"(?:\s*(?:[\[({]\s*(?:dot|bodka)\s*[\])}]|\.)\s*[A-Za-z0-9-]+)+",
    re.I,
)
# Digits with the usual separators; validated by _phone_like (9–15 digits, not a date).
_PHONE = re.compile(r"(?<![\w.,/-])(?:\+|00)?\(?\d[\d \u00a0./()-]{7,22}\d(?![\w])")
_DATE = re.compile(r"\b\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4}\b")
_PHONE_URL = re.compile(r"\b(tel|sms|callto|viber):[^\"'\s<>]+", re.I)
_WHATSAPP = re.compile(r"(wa\.me/|[?&]phone=)[+\d%\s-]+", re.I)
_TEXT_ATTRS = re.compile(r"""(\s(?:content|value|title|alt|aria-label|placeholder|data-[\w-]+)\s*=\s*)("[^"]*"|'[^']*')""", re.I)
_TAG = re.compile(r"(<[^>]*>)")


def _email(match: re.Match[str]) -> str:
    return match.group(0) if _FILE_SUFFIX.search(match.group(0)) else EMAIL_MARK


def _phone_like(match: re.Match[str]) -> str:
    text = match.group(0)
    digits = sum(ch.isdigit() for ch in text)
    if not 9 <= digits <= 15 or _DATE.search(text):
        return text
    return PHONE_MARK


def redact_text(text: str) -> str:
    """Replace e-mail addresses and phone numbers in plain text."""
    if not text:
        return text
    text = _EMAIL.sub(_email, text)
    text = _EMAIL_OBFUSCATED.sub(EMAIL_MARK, text)
    text = _PHONE_URL.sub(lambda m: f"{m.group(1)}:{PHONE_MARK}", text)
    text = _WHATSAPP.sub(lambda m: f"{m.group(1)}{PHONE_MARK}", text)
    return _PHONE.sub(_phone_like, text)


def _redact_tag(tag: str) -> str:
    tag = _EMAIL.sub(_email, tag)
    tag = _PHONE_URL.sub(lambda m: f"{m.group(1)}:{PHONE_MARK}", tag)
    tag = _WHATSAPP.sub(lambda m: f"{m.group(1)}{PHONE_MARK}", tag)
    return _TEXT_ATTRS.sub(lambda m: m.group(1) + _PHONE.sub(_phone_like, m.group(2)), tag)


def redact_html(html: str) -> str:
    """Redact an HTML document but keep its markup byte-for-byte otherwise.

    Text (including inline scripts such as JSON-LD) gets the full treatment;
    inside tags only links (``mailto:``, ``tel:``, WhatsApp) and human-readable
    attributes are touched, so asset URLs and ids stay intact.
    """
    if not html:
        return html
    parts = _TAG.split(html)
    for i, part in enumerate(parts):
        parts[i] = _redact_tag(part) if i % 2 else redact_text(part)
    return "".join(parts)
