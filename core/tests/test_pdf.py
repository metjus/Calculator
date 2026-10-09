"""Stage 5: the client PDF — what it says, in which language, and that it carries nothing external."""

from __future__ import annotations

import re
from datetime import date

from conftest import needs_browser

from webaudit import Config, Status
from webaudit.models import Area, Category, CheckResult, Issue, ScanResult, Score, SiteState
from webaudit.pdf import (
    QR_QUIET_ZONE,
    QR_SIZE_MM,
    STATUS_COLOURS,
    OfferOption,
    PdfContent,
    Profile,
    build_html,
    default_offer,
    format_date,
    issues_for,
    qr_svg,
    recommended_option,
    render,
    safe_pdf_name,
    status_of,
    vcard,
)
from webaudit.scoring import score

PROFILE = Profile(name="Matúš Š.", company_id="12345678", phone="+421 900 123 456", email="me@studio.sk")
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


def result() -> ScanResult:
    checks = [
        CheckResult(id="basics.https", area=Area.BASICS, status=Status.FAIL),
        CheckResult(id="mobile.viewport", area=Area.MOBILE, status=Status.FAIL),
        CheckResult(id="mobile.font_size", area=Area.MOBILE, status=Status.WARN),
        CheckResult(id="seo.title", area=Area.SEO, status=Status.PASS),
    ]
    config = Config.load()
    res = ScanResult(input_url="https://salon.sk/", url="https://salon.sk/", final_url="https://www.salon.sk/", state=SiteState.OK)
    res.checks = checks
    res.score = score(checks, config.scoring)
    res.issues = [
        Issue(check_id="mobile.viewport", area=Area.MOBILE, status=Status.FAIL, impact=6.5),
        Issue(check_id="basics.https", area=Area.BASICS, status=Status.FAIL, impact=17.4),
        Issue(check_id="mobile.font_size", area=Area.MOBILE, status=Status.WARN, impact=4.3),
    ]
    return res


def content(**kwargs) -> PdfContent:
    return PdfContent(result=result(), profile=PROFILE, today=date(2026, 10, 7), **kwargs)


def test_report_has_every_problem_in_three_parts() -> None:
    config = Config.load()
    item = content(client_name="Kaderníctvo Lena", screenshots={"desktop": JPEG, "mobile": JPEG})
    item.offer = default_offer(item, config, issues_for(item, config))
    item.offer[0].price = "180 €"
    html = build_html(item, config)

    assert "Kaderníctvo Lena" in html and "7. októbra 2026" in html
    assert "Čo je zle" in html and "Čo to spôsobuje" in html and "Riešenie" in html
    assert "Web nie je prispôsobený mobilom" in html  # the SK label of the first issue
    assert "Drobné písmo na mobile" in html and "Drobnosť" in html  # a warn keeps the softer wording
    assert html.index("Web nie je prispôsobený mobilom") < html.index("Web nemá zabezpečené pripojenie")  # ranked order kept
    assert "180 €" in html and "Odporúčam" in html and "ozvite sa a dohodneme sa" in html
    assert "<svg" in html and "IČO 12345678" in html  # the vCard QR and the operator's details
    assert "Hodnotenie po oblastiach" in html and "Mobil" in html  # areas in the report language
    # One number is a hero figure plus a meter, never a ring: a ring repeats the number inside it
    # and its arc never reached the 3:1 a graphical object needs in print.
    assert 'class="hero"' in html and 'class="meter"' in html and "<circle" not in html
    assert STATUS_COLOURS[status_of(item.result.score.total)][0] in html  # the measured, text-safe step


def test_every_status_colour_is_readable_as_text_and_as_a_bar() -> None:
    """The cover states the verdict in words and colour; the colour has to carry its weight."""

    def luminance(colour: str) -> float:
        channels = [int(colour.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    def contrast(one: str, two: str) -> float:
        light, dark = sorted((luminance(one), luminance(two)), reverse=True)
        return (light + 0.05) / (dark + 0.05)

    page = "#fffdf9"
    for status, (ink, track) in STATUS_COLOURS.items():
        assert contrast(ink, page) >= 4.5, f"{status} is too light to read as text"
        assert contrast(ink, track) >= 3.0, f"{status} bar does not stand out from its track"


def test_nothing_in_the_report_comes_from_the_network() -> None:
    """Everything is inlined, so a PDF can be made offline and leaks nothing by being opened."""
    item = content(screenshots={"desktop": JPEG})
    html = build_html(item, Config.load())
    assert 'src="data:image/jpeg;base64,' in html and "data:font/woff2" in html
    assert not re.search(r'(src|href)="(?!data:)', html)
    assert "http://" not in html and "https://" not in html.replace('xmlns="http://www.w3.org/2000/svg"', "")


def test_language_and_the_operator_s_choices_decide_what_is_printed() -> None:
    config = Config.load()
    czech = content(language="cs")
    assert "Co je špatně" in build_html(czech, config) and "7. října 2026" in build_html(czech, config)
    english = content(language="en")
    assert "What is wrong" in build_html(english, config) and "7 October 2026" in build_html(english, config)

    only_one = content(include=["basics.https"])
    html = build_html(only_one, config)
    assert "Web nemá zabezpečené pripojenie" in html and "Web nie je prispôsobený mobilom" not in html

    picked = content(summary="Vlastné zhrnutie.", offer=[OfferOption(title="Nový web", price="od 900 €", description="", recommended=True)])
    html = build_html(picked, config)
    assert "Vlastné zhrnutie." in html and "od 900 €" in html


def test_the_logo_is_printed_in_the_band() -> None:
    with_logo = content()
    with_logo.profile = Profile(name="Matúš Š.", phone="+421 900 123 456", logo=b"\x89PNG\r\n\x1a\nfake")
    html = build_html(with_logo, Config.load())
    assert 'class="logo" src="data:image/png;base64,' in html


def test_the_qr_code_carries_only_the_operator_s_own_contact() -> None:
    card = vcard(PROFILE)
    assert "FN:Matúš Š." in card and "TEL;TYPE=CELL:+421 900 123 456" in card and "EMAIL;TYPE=INTERNET:me@studio.sk" in card
    assert card.startswith("BEGIN:VCARD") and card.endswith("END:VCARD")
    assert "12345678" not in card  # the company id is printed beside the code, not scanned
    assert qr_svg(card).startswith("<svg")


def test_the_qr_code_scales_instead_of_cropping() -> None:
    """0.6.0 shipped a QR nobody could read: no viewBox, so the CSS size cropped it.

    The symbol must keep its four-module quiet zone and carry a viewBox covering the whole
    code, and a module must stay big enough on paper for a phone to resolve it.
    """
    svg = qr_svg(vcard(PROFILE))
    side = int(re.search(r'viewBox="0 0 (\d+) \1"', svg).group(1))
    marks = [(float(x), float(y)) for x, y in re.findall(r"M([\d.]+) ([\d.]+)", svg)]
    assert marks, "the symbol drew nothing"
    assert min(x for x, _ in marks) >= QR_QUIET_ZONE and min(y for _, y in marks) >= QR_QUIET_ZONE
    assert max(x for x, _ in marks) <= side - QR_QUIET_ZONE
    assert QR_SIZE_MM / side >= 0.5  # millimetres per module; phones read well above ~0.4

    html = build_html(content(), Config.load())
    assert f"width:{QR_SIZE_MM}mm" in html and "__QRMM__" not in html


def test_file_name_and_date_helpers() -> None:
    assert safe_pdf_name(content()) == "audit-salon.sk.pdf"
    assert format_date(date(2026, 1, 9), Config.load(), "sk") == "9. januára 2026"


@needs_browser
async def test_rendering_produces_a_pdf() -> None:
    config = Config.load()
    item = content(screenshots={"desktop": JPEG, "mobile": JPEG})
    item.offer = default_offer(item, config, issues_for(item, config))
    pdf = await render(build_html(item, config))
    assert pdf.startswith(b"%PDF-") and len(pdf) > 20_000


def test_the_recommended_option_follows_the_rule_not_the_middle_column() -> None:
    """A site past repairing gets “new website” recommended; the numbers are in scoring.json."""
    config = Config.load()
    weak = content()
    weak.result.score = Score(total=28, category=Category.CRITICAL, areas=[])
    assert recommended_option(weak, config) == 2

    fine = content()
    fine.result.score = Score(total=72, category=Category.OK, areas=[])
    assert recommended_option(fine, config) == 1

    # A decent score with a design Claude rated poorly still means a new website.
    ugly = content()
    ugly.result.score = Score(total=72, category=Category.OK, areas=[])
    ugly.result.checks = [
        *ugly.result.checks,
        CheckResult(id="design_ai.review", area=Area.DESIGN_AI, status=Status.FAIL, value={"score": 20}),
    ]
    assert recommended_option(ugly, config) == 2

    options = default_offer(ugly, config, issues_for(ugly, config))
    assert [o.recommended for o in options] == [False, False, True]
