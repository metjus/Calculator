"""Stage 5: the client PDF — what it says, in which language, and that it carries nothing external."""

from __future__ import annotations

import re
from datetime import date

from conftest import needs_browser

from webaudit import Config, Status
from webaudit.models import Area, CheckResult, Issue, ScanResult, SiteState
from webaudit.pdf import (
    OfferOption,
    PdfContent,
    Profile,
    build_html,
    default_offer,
    format_date,
    issues_for,
    qr_svg,
    render,
    safe_pdf_name,
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


def test_the_qr_code_carries_only_the_operator_s_own_contact() -> None:
    card = vcard(PROFILE)
    assert "FN:Matúš Š." in card and "TEL;TYPE=CELL:+421 900 123 456" in card and "EMAIL;TYPE=INTERNET:me@studio.sk" in card
    assert card.startswith("BEGIN:VCARD") and card.endswith("END:VCARD")
    assert qr_svg(card).startswith("<svg")


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
