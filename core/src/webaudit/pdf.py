"""The client PDF: one audited website turned into a report its owner can read (stage 5).

``build_html`` is pure and testable without a browser; ``render`` turns that HTML into a PDF
with Chromium. Everything the page needs is inlined as ``data:`` URIs (fonts, screenshots,
logo, QR code) and the renderer blocks every network request, so making a PDF never reaches
out to anything - it only ever draws what the caller passed in.

Wording follows the brief: the owner is addressed formally, judgements are hedged, no number
is invented, and every problem has the same three parts (what is wrong, what it causes, how
to fix it). All chrome strings live in ``defaults/texts.json`` under ``pdf``, so they can be
changed without touching code.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from typing import Any

from .config import Config
from .models import ScanResult
from .report import area_label, category_label, issue_text

FONT_WEIGHTS = (300, 400, 500, 600)
ISSUES_PER_PAGE = 3  # cards are tall; three per page leaves room for the longest texts
# How much of each finding the client sees. The report always names what is wrong and what it
# costs them; how much of the repair it hands over is the operator's decision, per client.
DETAIL_LEVELS = ("full", "no_fix", "short")
SHORT_IN_FULL = 3  # "short": this many findings in detail, the rest named only
MAX_LOGO_HEIGHT_MM = 14
QR_QUIET_ZONE = 4  # the standard quiet zone; scanners need it to find the symbol
QR_ERROR = "m"  # 15% error correction: enough for a printed page, and keeps the symbol small
QR_SIZE_MM = 36  # with the vCard above this leaves ~0.6 mm per module, which a phone reads easily


@dataclass
class OfferOption:
    """One of the three choices on the last page. The operator writes the price by hand."""

    title: str
    price: str
    description: str
    recommended: bool = False


@dataclass
class Profile:
    """Who the audit is from. Never the client's contact data - only the operator's own."""

    name: str = ""
    company_id: str = ""
    phone: str = ""
    email: str = ""
    logo: bytes | None = None


@dataclass
class PdfContent:
    """Everything the report shows, already decided by the operator in the preview."""

    result: ScanResult
    profile: Profile
    language: str = "sk"
    client_name: str | None = None
    summary: str | None = None
    include: list[str] | None = None  # check ids to print, in order; None = every issue
    detail: str = "no_fix"  # see DETAIL_LEVELS
    offer: list[OfferOption] = field(default_factory=list)
    competitors: list[dict[str, Any]] = field(default_factory=list)
    screenshots: dict[str, bytes] = field(default_factory=dict)
    today: date | None = None


# --------------------------------------------------------------------- bits


def _data_uri(data: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode()}"


def _font_faces() -> str:
    faces = []
    for weight in FONT_WEIGHTS:
        for subset in ("latin", "latin-ext"):
            name = f"ibm-plex-sans-{subset}-{weight}-normal.woff2"
            data = resources.files(__package__).joinpath("assets", "fonts", name).read_bytes()
            faces.append(
                f"@font-face{{font-family:'Plex';font-style:normal;font-weight:{weight};font-display:block;"
                f"src:url({_data_uri(data, 'font/woff2')}) format('woff2')}}"
            )
    return "".join(faces)


def _image_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"<?xml") or data.lstrip()[:4] == b"<svg":
        return "image/svg+xml"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def vcard(profile: Profile) -> str:
    """A contact card for the QR code. Only the operator's own details go in.

    Kept short on purpose: every character is another module in the symbol, and the company id
    is printed beside the code anyway, so it does not need to be scanned as well.
    """
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{profile.name}", f"N:{profile.name};;;;"]
    if profile.phone:
        lines.append(f"TEL;TYPE=CELL:{profile.phone}")
    if profile.email:
        lines.append(f"EMAIL;TYPE=INTERNET:{profile.email}")
    lines.append("END:VCARD")
    return "\r\n".join(lines)


def qr_svg(payload: str) -> str:
    """The vCard as an inline SVG, sized by CSS. Drawn locally; nothing is sent anywhere.

    Two details decide whether a phone can read it. The symbol needs the standard four-module
    quiet zone, and the SVG needs a ``viewBox``: without one, a CSS width does not scale the
    symbol, it crops it - which is exactly what shipped in 0.6.0 and made the code unreadable.
    """
    import io

    import segno

    code = segno.make(payload, error=QR_ERROR)
    buffer = io.BytesIO()
    code.save(buffer, kind="svg", scale=1, border=QR_QUIET_ZONE, dark="#1d1b18", svgclass=None, lineclass=None, xmldecl=False)
    svg = buffer.getvalue().decode("utf-8").strip()
    side = code.symbol_size(scale=1, border=QR_QUIET_ZONE)[0]
    return svg.replace("<svg ", f'<svg viewBox="0 0 {side} {side}" preserveAspectRatio="xMidYMid meet" ', 1)


def _esc(text: Any) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("\n", "<br>")


# One colour per status, dark enough to be read as text (>= 4.5:1 on the page) and used for the
# dot and the bar as well, with a light step of the same hue as the meter track (>= 3:1 against
# the bar). Measured, not picked by eye - see "Stage 5 as built" in docs/ARCHITECTURE.md.
STATUS_COLOURS = {
    "critical": ("#9b1111", "#f6dada"),
    "weak": ("#c05519", "#f8e3d6"),
    "ok": ("#94701b", "#f3ead2"),
    "good": ("#128460", "#d9f0e7"),
}
NEUTRAL = ("#57524a", "#f0ece4")


def status_of(score: int | None) -> str:
    if score is None:
        return ""
    return "critical" if score < 40 else "weak" if score < 60 else "ok" if score < 80 else "good"


def _tone(score: int | None) -> str:
    return STATUS_COLOURS.get(status_of(score), NEUTRAL)[0]


def _track(score: int | None) -> str:
    return STATUS_COLOURS.get(status_of(score), NEUTRAL)[1]


# --------------------------------------------------------------------- data


def _text(config: Config, key: str, language: str) -> str:
    entry = (config.texts.get("pdf") or {}).get(key) or {}
    return entry.get(language) or entry.get("en") or key


def _check(result: ScanResult, check_id: str) -> dict[str, Any] | None:
    for check in result.checks:
        if check.id == check_id:
            return check.model_dump(mode="json")
    return None


def issues_for(content: PdfContent, config: Config) -> list[dict[str, Any]]:
    """The problems to print, each with its three client texts in the report language."""
    ranked = {issue.check_id: issue for issue in content.result.issues}
    order = content.include if content.include is not None else list(ranked)
    out = []
    for check_id in order:
        issue = ranked.get(check_id)
        if issue is None:
            continue
        text = issue_text(config, check_id, content.language, issue.status) or {}
        if not text.get("problem"):
            continue
        out.append(
            {
                "id": check_id,
                "status": issue.status.value,
                "label": text.get("label", check_id),
                "problem": text["problem"],
                "impact": text.get("impact", ""),
                "solution": text.get("solution", ""),
            }
        )
    return out


def default_summary(content: PdfContent, config: Config, count: int) -> str:
    template = _text(config, "summary", content.language)
    return template.format(count=count, domain=_domain(content))


def format_date(day: date, config: Config, language: str) -> str:
    """7. októbra 2026 / 7. října 2026 / 7 October 2026 - month names live in texts.json."""
    months = (config.texts.get("pdf") or {}).get("months") or {}
    names = months.get(language) or months.get("en") or []
    if len(names) < 12:
        return day.isoformat()
    month = names[day.month - 1]
    return f"{day.day} {month} {day.year}" if language == "en" else f"{day.day}. {month} {day.year}"


def _domain(content: PdfContent) -> str:
    url = content.result.final_url or content.result.input_url
    return re.sub(r"^https?://(www\.)?", "", url).rstrip("/")


def _areas(content: PdfContent, config: Config) -> list[tuple[str, int]]:
    score = content.result.score
    if score is None:
        return []
    return [(area_label(config, area.area.value, content.language), area.score) for area in score.areas]


def _tiles(content: PdfContent, config: Config) -> list[dict[str, str]]:
    """Three facts the owner grasps at a glance; a fact we did not measure is left out."""
    tiles = []

    def status_of(check_id: str) -> str | None:
        check = _check(content.result, check_id)
        return check["status"] if check else None

    mobile = status_of("mobile.viewport")
    if mobile in ("pass", "warn", "fail"):
        passed = mobile == "pass"
        tiles.append(
            {
                "label": _text(config, "tile_mobile", content.language),
                "value": _text(config, "tile_mobile_" + ("yes" if passed else "no"), content.language),
                "colour": "#17a478" if passed else "#9b1111",
            }
        )
    https = status_of("basics.https")
    if https in ("pass", "fail"):
        tiles.append(
            {
                "label": _text(config, "tile_https", content.language),
                "value": _text(config, "tile_https_" + ("yes" if https == "pass" else "no"), content.language),
                "colour": "#17a478" if https == "pass" else "#9b1111",
            }
        )
    speed = _check(content.result, "speed.pagespeed_mobile")
    if speed and isinstance(speed.get("value"), int | float):
        value = int(speed["value"])
        tiles.append({"label": _text(config, "tile_speed", content.language), "value": f"{value} / 100", "colour": _tone(value)})
    return tiles[:3]


# --------------------------------------------------------------------- html


STYLE = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Plex',sans-serif;-webkit-font-smoothing:antialiased}
.page{width:210mm;height:297mm;background:#fffdf9;position:relative;overflow:hidden;color:#1d1b18;font-size:10.5pt;line-height:1.5;
      page-break-after:always;break-after:page}
.page:last-child{page-break-after:auto;break-after:auto}
.pad{padding:16mm 18mm}
.eyebrow{font-size:7.5pt;letter-spacing:.14em;text-transform:uppercase;color:#716b63;font-weight:500}
h1{font-weight:300;font-size:30pt;line-height:1.15;letter-spacing:-.01em;color:#fffdf9}
h2{font-weight:500;font-size:15pt;margin-bottom:5mm}
h3{font-weight:600;font-size:11.5pt}
.muted{color:#57524a}.small{font-size:9pt}
.band{height:74mm;background:linear-gradient(135deg,#0b6e72 0%,#0a5e63 55%,#084f52 100%);padding:14mm 18mm 0;color:#fffdf9;position:relative}
.band .eyebrow{color:#cfe8e7}
.band .logo{max-height:__LOGOMM__mm;max-width:52mm;margin-bottom:6mm;display:block}
.band h1{margin:5mm 0 2mm}
.band .url{color:#dcefed;font-size:11pt}
.band .mark{position:absolute;right:18mm;top:14mm;font-size:8.5pt;letter-spacing:.14em;text-transform:uppercase;color:#cfe8e7}
.scorecard{position:absolute;left:18mm;right:18mm;top:56mm;background:#fffdf9;border-radius:10px;
           box-shadow:0 1px 0 #e2ddd4, 0 10px 30px rgba(13,40,38,.13);padding:9mm 10mm 8mm;display:flex;gap:10mm;align-items:flex-start}
.scorecard .l{flex:0 0 62mm}
.scorecard .r{flex:1;border-left:1px solid #e2ddd4;padding-left:9mm}
.scorecard .r .t{margin-bottom:4.5mm}
.scorecard .r .t:last-child{margin-bottom:0}
.scorecard .r .t b{display:block;font-size:7.5pt;letter-spacing:.13em;text-transform:uppercase;color:#6a645c;font-weight:500;margin-bottom:1mm}
.scorecard .r .t span{font-size:12pt;font-weight:500}
.hero{font-weight:300;font-size:86pt;line-height:.86;letter-spacing:-.035em}
.hero small{font-size:14pt;font-weight:400;color:#716b63;letter-spacing:0;margin-left:3mm}
.meter{height:4mm;border-radius:2mm;position:relative;overflow:hidden;margin-top:5mm}
.meter i{position:absolute;inset:0 auto 0 0;border-radius:2mm}
.verdict{display:flex;align-items:center;gap:2.2mm;font-size:10pt;font-weight:500;margin-top:4mm;color:#1d1b18}
.verdict i{width:2.6mm;height:2.6mm;border-radius:50%;display:block;flex:0 0 auto}
.pad.below{padding-top:62mm}
.lead{font-size:11pt;line-height:1.7;max-width:142mm}
.arow{display:flex;align-items:center;gap:4mm;font-size:9.5pt;margin-bottom:2.2mm}
.arow .an{flex:0 0 40mm;color:#57524a}
.arow .at{flex:1;height:3mm;background:#f0ece4;border-radius:1.5mm;position:relative;max-width:58mm}
.arow .at i{position:absolute;inset:0 auto 0 0;border-radius:1.5mm}
.arow .av{flex:0 0 7mm;text-align:right;color:#57524a}
.areas2{columns:2;column-gap:12mm}
.cards{display:flex;flex-direction:column;gap:4mm;margin-top:4mm}
.card{border:1px solid #e2ddd4;border-radius:6px;padding:5mm;display:flex;gap:5mm}
.n{flex:0 0 9mm;height:9mm;border-radius:50%;display:grid;place-items:center;font-weight:600;font-size:10pt;background:#9b1111;color:#fff}
.card.warn .n{background:#daa932;color:#2a2205}
.chip{display:inline-block;font-size:7pt;letter-spacing:.1em;text-transform:uppercase;font-weight:600;padding:.9mm 2mm;border-radius:3px;
      background:#f6e6e6;color:#9b1111;margin-left:3mm;vertical-align:2px}
.card.warn .chip{background:#faf0d8;color:#8a6a10}
.part{margin-top:2.2mm}
.part b{display:block;font-size:7pt;letter-spacing:.12em;text-transform:uppercase;color:#716b63;font-weight:500;margin-bottom:.8mm}
.shots{display:flex;gap:5mm;align-items:flex-start;margin-top:4mm}
.shots figure{border-radius:6px;overflow:hidden;border:1px solid #e2ddd4;background:#f7f4ee}
.shots img{display:block;width:100%}
.shots figcaption{font-size:8pt;color:#716b63;padding:2mm}
.shots .d{flex:0 0 108mm}.shots .m{flex:0 0 42mm}
.barrow{display:flex;align-items:center;gap:4mm;margin-bottom:2.5mm;font-size:9.5pt}
.barrow .name{flex:0 0 52mm;color:#57524a}
.barrow .track{flex:1;height:7mm;background:#f0ece4;border-radius:3px;position:relative}
.barrow .track i{position:absolute;inset:0 auto 0 0;border-radius:3px;background:#b9cfc9}
.barrow.you{font-weight:600}
.barrow.you .track i{background:#cb5a1a}
.barrow .v{flex:0 0 12mm;text-align:right;font-variant-numeric:tabular-nums}
.boxes{display:flex;gap:4mm;align-items:stretch;margin-top:5mm}
.box{flex:1;border:1px solid #e2ddd4;border-radius:8px;padding:6mm 5mm;display:flex;flex-direction:column}
.box.pick{border:2px solid #0b6e72;background:#f3f8f7;margin-top:-4mm;padding-top:10mm;position:relative}
.box .tag{position:absolute;top:4mm;left:5mm;font-size:7pt;letter-spacing:.12em;text-transform:uppercase;color:#0b6e72;font-weight:600}
.box .t{font-weight:600;font-size:11pt;min-height:14mm}
.box .price{font-weight:300;font-size:21pt;margin:2mm 0 3mm}
.box .d2{font-size:9pt;color:#57524a;flex:1}
.note{margin-top:6mm;font-size:10pt;color:#57524a}
.more{margin-top:7mm;border-top:1px solid #e2ddd4;padding-top:5mm}
.more .mini{font-size:7.5pt;letter-spacing:.12em;text-transform:uppercase;color:#716b63;margin-bottom:3mm}
.more ul{margin:0;padding-left:5mm;columns:2;column-gap:8mm;font-size:10pt}
.more li{margin-bottom:1.5mm;break-inside:avoid}
.more p{margin:4mm 0 0;font-size:9.5pt;color:#57524a}
.contact{position:absolute;left:18mm;right:18mm;bottom:18mm;border-top:1px solid #e2ddd4;padding-top:5mm;display:flex;gap:6mm;align-items:center}
.contact svg{width:__QRMM__mm;height:__QRMM__mm;display:block;flex:0 0 auto}
.who{position:absolute;left:18mm;right:18mm;bottom:14mm;border-top:1px solid #e2ddd4;padding-top:4mm;display:flex;
     justify-content:space-between;font-size:9pt;color:#57524a}
.foot{position:absolute;left:18mm;right:18mm;bottom:10mm;display:flex;justify-content:space-between;font-size:8pt;color:#716b63;
      border-top:1px solid #e2ddd4;padding-top:3mm}
"""


def build_html(content: PdfContent, config: Config) -> str:
    """The whole report as one self-contained HTML document (no external requests)."""
    language = content.language
    label = lambda key: _text(config, key, language)  # noqa: E731 - a local shorthand reads better here
    issues = issues_for(content, config)
    domain = _domain(content)
    client = content.client_name or domain
    today = format_date(content.today or date.today(), config, language)
    score = content.result.score
    pages: list[str] = []

    def foot(number: int) -> str:
        return (
            f'<div class="foot"><span>{_esc(label("footer"))} {_esc(domain)} · {_esc(today)}</span>'
            f"<span>{_esc(label('page'))} {number}</span></div>"
        )

    # ---------------------------------------------------------- cover
    # The band carries the brand, the card below it overlaps the band's edge and holds the
    # three numbers the owner looks for first. One number = one hero figure plus a meter;
    # a ring would say the same thing twice (and its arc never reached 3:1 in print).
    logo = ""
    if content.profile.logo:
        logo = f'<img class="logo" src="{_data_uri(content.profile.logo, _image_type(content.profile.logo))}" alt="">'
    category = category_label(config, score.category.value, language) if score else ""
    tiles = "".join(
        f'<div class="t"><b>{_esc(t["label"])}</b><span style="color:{t["colour"]}">{_esc(t["value"])}</span></div>'
        for t in _tiles(content, config)
    )
    areas = "".join(
        f'<div class="arow"><span class="an">{_esc(name)}</span>'
        f'<span class="at"><i style="width:{value}%;background:{_tone(value)}"></i></span>'
        f'<span class="av">{value}</span></div>'
        for name, value in _areas(content, config)
    )
    summary = content.summary if content.summary is not None else default_summary(content, config, len(issues))
    card = ""
    if score:
        colour, track = _tone(score.total), _track(score.total)
        card = f"""<div class="scorecard">
    <div class="l">
      <div class="hero">{score.total}<small>/ 100</small></div>
      <div class="meter" style="background:{track}"><i style="width:{score.total}%;background:{colour}"></i></div>
      <div class="verdict"><i style="background:{colour}"></i>{_esc(label("score_label"))} {_esc(category.lower())}</div>
    </div>
    {f'<div class="r">{tiles}</div>' if tiles else ""}
  </div>"""
    pages.append(
        f"""<section class="page">
  <div class="band">{logo}
    <div class="eyebrow">{_esc(label("doc_title"))}</div>
    <h1>{_esc(client)}</h1>
    <div class="url">{_esc(domain)} · {_esc(today)}</div>
    <div class="mark">{_esc(content.profile.name)}</div>
  </div>
  {card}
  <div class="pad{" below" if card else ""}">
    <p class="lead">{_esc(summary)}</p>
    {
            f'<div class="eyebrow" style="margin-top:12mm">{_esc(label("areas_eyebrow"))}</div>'
            f'<div class="areas2" style="margin-top:5mm">{areas}</div>'
            if areas
            else ""
        }
  </div>
  <div class="who"><span>{_esc(label("prepared_by"))} {_esc(content.profile.name)}</span>
    <span>{_esc(" · ".join(p for p in (content.profile.phone, content.profile.email) if p))}</span></div>
</section>"""
    )

    # ---------------------------------------------------------- findings
    detail = content.detail if content.detail in DETAIL_LEVELS else "no_fix"
    detailed = issues[:SHORT_IN_FULL] if detail == "short" else issues
    named_only = issues[SHORT_IN_FULL:] if detail == "short" else []

    def card(number: int, item: dict[str, Any]) -> str:
        parts = f'<div class="part"><b>{_esc(label("part_problem"))}</b>{_esc(item["problem"])}</div>'
        if item["impact"]:
            parts += f'<div class="part"><b>{_esc(label("part_impact"))}</b>{_esc(item["impact"])}</div>'
        if detail == "full" and item["solution"]:
            parts += f'<div class="part"><b>{_esc(label("part_solution"))}</b>{_esc(item["solution"])}</div>'
        return (
            f'<div class="card {"warn" if item["status"] == "warn" else ""}"><div class="n">{number}</div><div>'
            f'<h3>{_esc(item["label"])}<span class="chip">'
            f"{_esc(label('chip_minor' if item['status'] == 'warn' else 'chip_major'))}</span></h3>{parts}</div></div>"
        )

    for start in range(0, len(detailed), ISSUES_PER_PAGE):
        chunk = detailed[start : start + ISSUES_PER_PAGE]
        cards = "".join(card(number, item) for number, item in enumerate(chunk, start + 1))
        head = f'<div class="eyebrow">{_esc(label("findings_eyebrow"))}</div><h2>{_esc(label("findings_title"))}</h2>' if start == 0 else ""
        more = ""
        if named_only and start + ISSUES_PER_PAGE >= len(detailed):
            # The rest are named, not explained: the owner sees there is more without being handed a list to shop around.
            rows = "".join(f"<li>{_esc(item['label'])}</li>" for item in named_only)
            more = (
                f'<div class="more"><div class="mini">{_esc(label("more_title"))}</div><ul>{rows}</ul>'
                f"<p>{_esc(label('more_note').format(count=len(named_only)))}</p></div>"
            )
        pages.append(
            f'<section class="page"><div class="pad">{head}<div class="cards">{cards}</div>{more}</div>{foot(len(pages) + 1)}</section>'
        )
    if not issues:
        pages.append(
            f'<section class="page"><div class="pad"><div class="eyebrow">{_esc(label("findings_eyebrow"))}</div>'
            f"<h2>{_esc(label('no_issues'))}</h2></div>{foot(len(pages) + 1)}</section>"
        )

    # ---------------------------------------------------------- how it looks + comparison
    shots = "".join(
        f'<figure class="{"d" if name == "desktop" else "m"}">'
        f'<img src="{_data_uri(data, _image_type(data))}" alt="">'
        f"<figcaption>{_esc(label('shot_' + name))}</figcaption></figure>"
        for name, data in ((n, content.screenshots[n]) for n in ("desktop", "mobile") if content.screenshots.get(n))
    )
    rivals = [c for c in content.competitors if c.get("score") is not None]
    bars = ""
    if rivals and score:
        bars = (
            f'<div class="barrow you"><span class="name">{_esc(domain)}</span>'
            f'<span class="track"><i style="width:{score.total}%"></i></span><span class="v">{score.total}</span></div>'
        )
        bars += "".join(
            f'<div class="barrow"><span class="name">{_esc(c["domain"])}</span>'
            f'<span class="track"><i style="width:{int(c["score"])}%"></i></span><span class="v">{int(c["score"])}</span></div>'
            for c in rivals
        )
    if shots or bars:
        pages.append(
            f"""<section class="page"><div class="pad">
  {f'<div class="eyebrow">{_esc(label("shots_eyebrow"))}</div><h2>{_esc(label("shots_title"))}</h2><div class="shots">{shots}</div>' if shots else ""}
  {f'<div class="eyebrow" style="margin-top:10mm">{_esc(label("compare_eyebrow"))}</div><h2>{_esc(label("compare_title"))}</h2>{bars}' if bars else ""}
</div>{foot(len(pages) + 1)}</section>"""
        )

    # ---------------------------------------------------------- offer
    if content.offer:
        boxes = "".join(
            f'<div class="box {"pick" if option.recommended else ""}">'
            + (f'<span class="tag">{_esc(label("offer_recommended"))}</span>' if option.recommended else "")
            + f'<div class="t">{_esc(option.title)}</div><div class="price">{_esc(option.price)}</div>'
            f'<div class="d2">{_esc(option.description)}</div></div>'
            for option in content.offer
        )
        contact_lines = "".join(
            f'<div class="small muted">{_esc(line)}</div>'
            for line in (
                f"{label('ico_label')} {content.profile.company_id}" if content.profile.company_id else "",
                " · ".join(p for p in (content.profile.phone, content.profile.email) if p),
            )
            if line
        )
        pages.append(
            f"""<section class="page"><div class="pad">
  <div class="eyebrow">{_esc(label("offer_eyebrow"))}</div><h2>{_esc(label("offer_title"))}</h2>
  <div class="boxes">{boxes}</div>
  <p class="note">{_esc(label("offer_note"))}</p>
</div>
<div class="contact">{qr_svg(vcard(content.profile))}<div>
  <div style="font-weight:600">{_esc(content.profile.name)}</div>{contact_lines}
  <div class="small muted" style="margin-top:2mm">{_esc(label("contact_note"))}</div>
</div></div>{foot(len(pages) + 1)}</section>"""
        )

    style = STYLE.replace("__LOGOMM__", str(MAX_LOGO_HEIGHT_MM)).replace("__QRMM__", str(QR_SIZE_MM))
    return (
        f'<!doctype html><html lang="{_esc(language)}"><head><meta charset="utf-8">'
        f"<title>{_esc(label('doc_title'))} – {_esc(client)}</title>"
        f"<style>{_font_faces()}{style}</style></head><body>{''.join(pages)}</body></html>"
    )


def safe_pdf_name(content: PdfContent) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", f"audit-{_domain(content)}").strip("-")
    return f"{stem or 'audit'}.pdf"


# ------------------------------------------------------------------ render


async def render(html: str, *, timeout: float = 60.0) -> bytes:
    """The HTML as an A4 PDF. The page is given no network at all - it draws only what it carries."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - the desktop build always ships Playwright
        raise RuntimeError("Playwright is not installed (pip install 'webaudit[browser]')") from exc

    import os

    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(
            executable_path=os.environ.get("WEBAUDIT_CHROMIUM_PATH") or None,
            channel=None if os.environ.get("WEBAUDIT_CHROMIUM_PATH") else (os.environ.get("WEBAUDIT_BROWSER_CHANNEL") or None),
            args=["--disable-dev-shm-usage"],
        )
        try:
            page = await browser.new_page()
            # Nothing in the report comes from the network; refuse every request so it stays that way.
            await page.route("**/*", lambda route: route.abort())
            await page.set_content(html, wait_until="load", timeout=timeout * 1000)
            await page.emulate_media(media="print")
            return await page.pdf(format="A4", print_background=True, prefer_css_page_size=False)
        finally:
            await browser.close()
    finally:
        await playwright.stop()


def recommended_option(content: PdfContent, config: Config) -> int:
    """Which of the three choices carries the “I recommend” tag.

    Fixing problems one at a time stops making sense at some point: a site that scores badly
    overall, or whose design Claude rated poorly, needs a new one. Both numbers live in
    ``scoring.json`` so the owner can move the line without touching code.
    """
    rule = config.scoring.get("offer") or {}
    total = content.result.score.total if content.result.score else None
    if total is not None and total < rule.get("new_website_below_score", 0):
        return 2
    review = next((c.value for c in content.result.checks if c.id == "design_ai.review" and isinstance(c.value, dict)), None)
    design = review.get("score") if review else None
    if isinstance(design, int | float) and design < rule.get("new_website_below_design", 0):
        return 2
    return 1  # fix everything found: the usual answer


def default_offer(content: PdfContent, config: Config, issues: list[dict[str, Any]]) -> list[OfferOption]:
    """The three choices with empty prices; the operator writes them in the preview."""
    biggest = issues[0]["label"] if issues else ""
    pick = recommended_option(content, config)
    texts = (config.texts.get("pdf") or {}).get("offer_defaults") or {}
    entries = texts.get(content.language) or texts.get("en") or []
    options = []
    for index, entry in enumerate(entries):
        description = entry.get("description", "")
        options.append(
            OfferOption(
                title=entry.get("title", ""),
                price="",
                description=description.format(problem=biggest) if "{problem}" in description else description,
                recommended=index == pick,
            )
        )
    return options


__all__ = [
    "STATUS_COLOURS",
    "OfferOption",
    "PdfContent",
    "Profile",
    "build_html",
    "default_offer",
    "default_summary",
    "format_date",
    "DETAIL_LEVELS",
    "issues_for",
    "qr_svg",
    "recommended_option",
    "render",
    "safe_pdf_name",
    "status_of",
    "vcard",
]
