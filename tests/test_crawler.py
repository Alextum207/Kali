import os
import pathlib
import pytest
from playwright.async_api import async_playwright
import time
from app.crawler import (
    crawl_page,
    find_low_contrast_legal_text,
    apply_consent_rules,
    _snapshot_page,
    _looks_like_captcha,
    LEGAL_TEXT_KEYWORDS,
)


def test_legal_text_keywords_is_shared_with_readability_module():
    from app.analysis.readability import _LEGAL_KEYWORDS

    assert _LEGAL_KEYWORDS is LEGAL_TEXT_KEYWORDS
    for kw in ("laufzeit", "kosten", "preis", "datenschutz", "rücktritt", "haftung", "widerspruch"):
        assert kw in LEGAL_TEXT_KEYWORDS


def test_looks_like_captcha_detects_recaptcha_iframe():
    dom = '<html><body><iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe></body></html>'
    assert _looks_like_captcha(dom) is True


def test_looks_like_captcha_detects_hcaptcha():
    dom = '<html><body><div class="h-captcha" data-sitekey="x"></div></body></html>'
    assert _looks_like_captcha(dom) is True


def test_looks_like_captcha_detects_german_challenge_text():
    dom = "<html><body><p>Bitte bestätigen Sie, dass Sie kein Roboter sind.</p></body></html>"
    assert _looks_like_captcha(dom) is True


def test_looks_like_captcha_returns_false_for_normal_page():
    dom = "<html><body><h1>Willkommen im Shop</h1><p>Produkte hier.</p></body></html>"
    assert _looks_like_captcha(dom) is False

FIXTURE_URL = pathlib.Path(__file__).parent.joinpath("fixtures/sample_page.html").as_uri()
CAMOUFLAGE_FIXTURE_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/camouflaged_text_page.html"
).as_uri()
REDDIT_CONSENT_FIXTURE_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/reddit_consent_page.html"
).as_uri()
REDDIT_RULE_PATH = (
    pathlib.Path(__file__).parent.parent / "data" / "consent_rules" / "reddit.json"
)


@pytest.mark.asyncio
async def test_crawl_page_captures_dom_change_and_button_styles(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        result = await crawl_page(FIXTURE_URL, browser, har_dir=str(tmp_path))
        await browser.close()

    assert "initial" in result["dom_before"]
    assert "changed" in result["dom_after"]
    assert isinstance(result["screenshot"], bytes) and len(result["screenshot"]) > 0
    assert result["button_styles"] is not None
    assert result["button_styles"]["accept"]["width"] == 200
    assert result["button_styles"]["reject"]["width"] == 60

    assert isinstance(result["har_path"], str) and result["har_path"]
    assert os.path.exists(result["har_path"])


@pytest.mark.asyncio
async def test_snapshot_page_skip_diff_sleep_skips_the_fixed_wait():
    """skip_diff_sleep=True (used after a flow-step navigation, where a
    fresh page already settled its own DOM) must not pay the 1.5s
    same-page-JS-diff wait that a non-navigating snapshot needs."""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(FIXTURE_URL)

        start = time.monotonic()
        await _snapshot_page(page, skip_diff_sleep=True)
        elapsed = time.monotonic() - start

        await browser.close()

    assert elapsed < 1.0  # well under the 1.5s fixed sleep it would pay otherwise


@pytest.mark.asyncio
async def test_find_low_contrast_legal_text_flags_camouflaged_clause():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(CAMOUFLAGE_FIXTURE_URL)
        findings = await find_low_contrast_legal_text(page)
        await browser.close()

    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Visuelle Tarnung (Kontrast)"
    assert "kündigung" in findings[0]["evidence_data"]["excerpt"].lower()


@pytest.mark.asyncio
async def test_apply_consent_rules_scopes_reddit_rules_bare_button_selector(tmp_path):
    """Regression test: reddit.json's only actionable rule is a bare "button"
    selector that only makes sense scoped to its `parent`/`childFilter`
    (a <section> that also contains the cookie-notice link). Verifies that
    scoping is reconstructed so (a) the correctly-scoped "Reject
    non-essential" button is clicked, and (b) an unrelated button elsewhere
    on the page (e.g. a product page's own "add to cart") is never touched."""
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "reddit.json").write_text(REDDIT_RULE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(REDDIT_CONSENT_FIXTURE_URL)
        await apply_consent_rules(page, str(rules_dir))
        consent_clicked = await page.evaluate("() => window.__consentClicked")
        unrelated_clicked = await page.evaluate("() => window.__unrelatedClicked")
        await browser.close()

    assert consent_clicked == "reject"
    assert unrelated_clicked is None
