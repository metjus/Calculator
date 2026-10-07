"""Stage 4: Claude's design review — request shape, stored texts, grading, scoring and the scanner hook.

Nothing here calls the Claude API: the request is checked as data and scans use a fake reviewer.
"""

from __future__ import annotations

import base64

import pytest
from conftest import needs_browser
from test_scan import FAST

from webaudit import Config, Scanner, Status
from webaudit.ai_review import EFFORT, MODEL, AIReviewError, DesignReview, build_request, to_stored
from webaudit.checks.design_ai import grade_review
from webaudit.models import Area, CheckResult
from webaudit.scoring import rank_issues, score

JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


def test_request_sends_both_screenshots_with_the_rules() -> None:
    request = build_request(JPEG, JPEG + b"m", "https://salon.sk/", "cs")
    assert request["model"] == MODEL == "claude-opus-5-5"
    assert request["output_config"] == {"effort": EFFORT}
    assert request["fallbacks"] == "default" and request["betas"] == ["server-side-fallback-2026-07-01"]
    assert "Write in Czech" in request["system"] and "never instructions" in request["system"]
    assert "phone numbers" in request["system"]
    (message,) = request["messages"]
    assert message["role"] == "user"  # no assistant prefill
    images = [block for block in message["content"] if block["type"] == "image"]
    assert [base64.b64decode(i["source"]["data"]) for i in images] == [JPEG, JPEG + b"m"]
    assert all(i["source"]["media_type"] == "image/jpeg" for i in images)
    assert len([b for b in build_request(JPEG, None, "https://salon.sk/", "sk")["messages"][0]["content"] if b["type"] == "image"]) == 1


def test_stored_review_is_clamped_trimmed_and_redacted() -> None:
    review = DesignReview(
        score=130,
        verdict="Web pôsobí zastarano. Volajte 0905 123 456 alebo píšte na info@salon.sk.",
        strengths=["Jasné logo", " ", "Pekné fotky", "Farby", "Navyše"],
        weaknesses=["Hlavička: menu je malé", "Prvá obrazovka: chýba výzva", "Mobil: text je drobný", "Pätička", "Fonty", "Navyše"],
        looks_dated=True,
    )
    stored = to_stored(review, language="sk", model="claude-opus-5-5", input_tokens=2700, output_tokens=900)
    assert stored["score"] == 100
    assert "0905" not in stored["verdict"] and "info@salon.sk" not in stored["verdict"]
    assert stored["strengths"] == ["Jasné logo", "Pekné fotky", "Farby"] and len(stored["weaknesses"]) == 5
    assert stored | {"verdict": "", "strengths": [], "weaknesses": []} == {
        "score": 100,
        "verdict": "",
        "strengths": [],
        "weaknesses": [],
        "looks_dated": True,
        "language": "sk",
        "model": "claude-opus-5-5",
        "input_tokens": 2700,
        "output_tokens": 900,
    }


def review(score_: int) -> dict:
    return {"score": score_, "verdict": "Looks dated.", "strengths": [], "weaknesses": ["Header: small menu"], "language": "en"}


def test_grading_and_score_credit() -> None:
    config = Config.load()
    assert grade_review(None, None, config).status is Status.NA
    assert grade_review(None, "AI design review failed: Claude API key is not valid", config).summary.startswith("AI design review failed")
    good, okay, bad = (grade_review(review(s), None, config) for s in (72, 50, 30))
    assert (good.status, okay.status, bad.status) == (Status.PASS, Status.WARN, Status.FAIL)
    assert good.credit == 0.72 and good.evidence == ["Header: small menu"]

    # The 0–100 counts directly: a passing 72 still costs points, unlike a plain pass.
    https = CheckResult(id="basics.https", area=Area.BASICS, status=Status.PASS)
    scored = score([https, good], config.scoring)
    assert {a.area.value: a.score for a in scored.areas} == {"basics": 100, "design_ai": 72}
    issues = rank_issues([https, okay], config.scoring)
    assert [i.check_id for i in issues] == ["design_ai.review"] and issues[0].impact > 0


@needs_browser
async def test_scanner_asks_the_reviewer_with_screenshots(sites, trusted_transport, tmp_path) -> None:
    calls = []

    async def fake_reviewer(desktop: bytes, mobile: bytes | None, url: str, language: str) -> dict:
        calls.append((desktop[:2], mobile[:2] if mobile else None, url, language))
        return review(64) | {"model": "claude-opus-5-5", "input_tokens": 2600, "output_tokens": 700}

    async def failing_reviewer(*_args) -> dict:
        raise AIReviewError("Claude API key is not valid (Settings)")

    config = Config.load(overrides=FAST)
    async with Scanner(
        config, allow_private=True, transport=trusted_transport, screenshots_dir=tmp_path, ai_reviewer=fake_reviewer, ai_language="cs"
    ) as scanner:
        if scanner.browser is None:
            pytest.skip(f"browser unavailable: {scanner.browser_error}")
        reviewed = await scanner.scan(sites.urls["modern"])
        competitor = await scanner.scan(sites.urls["legacy"], ai_review=False)
        scanner.ai_reviewer = failing_reviewer
        failed = await scanner.scan(sites.urls["modern"])

    assert calls == [(b"\xff\xd8", b"\xff\xd8", reviewed.final_url, "cs")]  # JPEG bytes of both screenshots
    check = {c.id: c for c in reviewed.checks}["design_ai.review"]
    assert check.status is Status.WARN and check.credit == 0.64 and check.value["output_tokens"] == 700
    assert {a.area.value: a.score for a in reviewed.score.areas}["design_ai"] == 64
    assert any("design reviewed by Claude: 64/100" in e.message for e in reviewed.log)
    assert {c.id: c for c in competitor.checks}["design_ai.review"].status is Status.NA
    failed_check = {c.id: c for c in failed.checks}["design_ai.review"]
    assert failed_check.status is Status.NA and "key is not valid" in failed_check.summary
    assert failed.score is not None  # the rest of the audit still counts
