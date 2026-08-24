import os
import pathlib
import pytest
from playwright.async_api import async_playwright
import time
import json

from app.crawler import (
    crawl_page,
    find_low_contrast_legal_text,
    apply_consent_rules,
    _snapshot_page,
    _looks_like_captcha,
    _matches_present_detector,
    _detect_cookie_wall,
    verify_countdown_reset,
    LEGAL_TEXT_KEYWORDS,
)
from app.analysis.pipeline import run_analysis


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
ASYMMETRIC_CONSENT_FIXTURE_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/asymmetric_consent_page.html"
).as_uri()
NO_REJECT_CONSENT_FIXTURE_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/no_reject_consent_page.html"
).as_uri()

# Synthetic rule (not a real vendored Consent-O-Matic file — kept local to
# this test) resolving both an accept and a reject click target scoped to
# #cookie-banner, for asserting real-selector style capture end to end.
ASYMMETRIC_RULE = {
    "asymmetric-test-site": {
        "detectors": [
            {"presentMatcher": [{"type": "css", "target": {"selector": "#cookie-banner"}}]}
        ],
        "methods": [
            {
                "action": {
                    "type": "click",
                    "target": {"selector": "button", "textFilter": ["Alle akzeptieren"]},
                    "parent": {"selector": "#cookie-banner"},
                },
                "name": "DO_CONSENT_ACCEPT",
            },
            {
                "action": {
                    "type": "click",
                    "target": {"selector": "button", "textFilter": ["Ablehnen"]},
                    "parent": {"selector": "#cookie-banner"},
                },
                "name": "DO_CONSENT_REJECT",
            },
        ],
    }
}

# Synthetic rule whose banner is only ever confirmed present via
# #cookie-banner and which has no reject-shaped click target and no
# "type": "consent" toggle structure — the one case that should genuinely
# be flagged as a missing reject option.
NO_REJECT_RULE = {
    "no-reject-test-site": {
        "detectors": [
            {"presentMatcher": [{"type": "css", "target": {"selector": "#cookie-banner"}}]}
        ],
        "methods": [
            {
                "action": {
                    "type": "click",
                    "target": {"selector": "button", "textFilter": ["Accept all"]},
                    "parent": {"selector": "#cookie-banner"},
                },
                "name": "DO_CONSENT",
            }
        ],
    }
}


def _write_rule(tmp_path, filename: str, rule: dict) -> str:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(exist_ok=True)
    (rules_dir / filename).write_text(json.dumps(rule), encoding="utf-8")
    return str(rules_dir)


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


@pytest.mark.asyncio
async def test_apply_consent_rules_captures_real_reject_style_before_click(tmp_path):
    """reject_style must reflect the real DOM element found via the rule's
    own selector — captured before the click removes it from the page —
    not the dead #accept/#reject ID probe in _snapshot_page."""
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "reddit.json").write_text(REDDIT_RULE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(REDDIT_CONSENT_FIXTURE_URL)
        result = await apply_consent_rules(page, str(rules_dir))
        await browser.close()

    assert result["reject_style"] is not None
    assert result["accept_style"] is not None
    assert result["reject_option_missing"] is False


@pytest.mark.asyncio
async def test_apply_consent_rules_feeds_real_selectors_into_button_asymmetry(tmp_path):
    rules_dir = _write_rule(tmp_path, "asymmetric.json", ASYMMETRIC_RULE)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(ASYMMETRIC_CONSENT_FIXTURE_URL)
        consent_result = await apply_consent_rules(page, rules_dir)
        await browser.close()

    button_styles = {"accept": consent_result["accept_style"], "reject": consent_result["reject_style"]}
    assert button_styles["accept"]["width"] == 220
    assert button_styles["reject"]["width"] == 50

    findings = await run_analysis("<html><body></body></html>", button_styles)
    assert any(f["pattern_type"] == "Visuelle Asymmetrie (Button)" for f in findings)


@pytest.mark.asyncio
async def test_matches_present_detector_accepts_non_list_present_matcher():
    """~19/205 vendored Consent-O-Matic rules (e.g. chandago, cookieLab,
    EvidonIFrame) store `presentMatcher` as a single object instead of
    wrapping it in a list. Root cause of the JS port's "object is not
    iterable" console errors (consent.js's matchesPresentDetector) — the
    Python side has the same unguarded assumption, just silently swallowed
    by apply_consent_rules's blanket try/except, which drops these rules
    from ever being detected as present instead of crashing loudly."""
    rule = {
        "chandago": {
            "detectors": [
                {"presentMatcher": {"type": "css", "target": {"selector": "#ac-Banner"}}}
            ]
        }
    }

    class _FakePage:
        async def query_selector(self, selector):
            return object() if selector == "#ac-Banner" else None

    result = await _matches_present_detector(_FakePage(), rule)
    assert result == ("chandago", "#ac-Banner")


COOKIE_WALL_FIXTURE_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/cookie_wall_page.html"
).as_uri()


@pytest.mark.asyncio
async def test_detect_cookie_wall_flags_overflow_hidden_body():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(COOKIE_WALL_FIXTURE_URL)
        detected = await _detect_cookie_wall(page)
        await browser.close()

    assert detected is True


@pytest.mark.asyncio
async def test_detect_cookie_wall_false_for_normal_scrollable_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(NO_REJECT_CONSENT_FIXTURE_URL)
        detected = await _detect_cookie_wall(page)
        await browser.close()

    assert detected is False


@pytest.mark.asyncio
async def test_apply_consent_rules_distinguishes_cookie_wall_from_missing_reject(tmp_path):
    """The two signals must stay separate: a banner with no reject option
    on an otherwise-normal page is `reject_option_missing` only; a banner
    that also blocks the page underneath it (overflow:hidden) additionally
    sets `cookie_wall_detected` — never conflated into one flag."""
    rules_dir = _write_rule(tmp_path, "no_reject.json", NO_REJECT_RULE)

    async with async_playwright() as p:
        browser = await p.chromium.launch()

        normal_page = await browser.new_page()
        await normal_page.goto(NO_REJECT_CONSENT_FIXTURE_URL)
        normal_result = await apply_consent_rules(normal_page, rules_dir)

        walled_page = await browser.new_page()
        await walled_page.goto(COOKIE_WALL_FIXTURE_URL)
        walled_result = await apply_consent_rules(walled_page, rules_dir)

        await browser.close()

    assert normal_result["reject_option_missing"] is True
    assert normal_result["cookie_wall_detected"] is False

    assert walled_result["reject_option_missing"] is True
    assert walled_result["cookie_wall_detected"] is True


@pytest.mark.asyncio
async def test_apply_consent_rules_flags_missing_reject_option(tmp_path):
    rules_dir = _write_rule(tmp_path, "no_reject.json", NO_REJECT_RULE)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(NO_REJECT_CONSENT_FIXTURE_URL)
        result = await apply_consent_rules(page, rules_dir)
        await browser.close()

    assert result["reject_option_missing"] is True


@pytest.mark.asyncio
async def test_apply_consent_rules_does_not_flag_missing_reject_when_reject_exists(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "reddit.json").write_text(REDDIT_RULE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(REDDIT_CONSENT_FIXTURE_URL)
        result = await apply_consent_rules(page, str(rules_dir))
        await browser.close()

    assert result["reject_option_missing"] is False


@pytest.mark.asyncio
async def test_apply_consent_rules_does_not_flag_missing_reject_when_banner_absent(tmp_path):
    """The no-reject rule's presentMatcher (#cookie-banner) never matches a
    page that doesn't have that banner at all — no claim should be made."""
    rules_dir = _write_rule(tmp_path, "no_reject.json", NO_REJECT_RULE)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(FIXTURE_URL)
        result = await apply_consent_rules(page, rules_dir)
        await browser.close()

    assert result["reject_option_missing"] is False


COUNTDOWN_RESET_FIXTURE_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/countdown_reset_page.html"
).as_uri()


@pytest.mark.asyncio
async def test_verify_countdown_reset_boosts_confidence_when_timer_restarts():
    """The fixture's countdown silently restarts a fresh 2-minute window
    instead of expiring — jumping the page's clock forward must catch that
    and both raise confidence and record the clock_verified evidence note."""
    finding = {
        "pattern_type": "Fake Urgency",
        "confidence_score": 0.7,
        "evidence_data": {"selector": "#countdown"},
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(COUNTDOWN_RESET_FIXTURE_URL)
        await verify_countdown_reset(page, [finding])
        await browser.close()

    assert finding["confidence_score"] > 0.7
    assert "clock_verified" in finding["evidence_data"]


COUNTDOWN_EXPIRES_FIXTURE_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/countdown_expires_page.html"
).as_uri()


@pytest.mark.asyncio
async def test_verify_countdown_reset_leaves_confidence_unchanged_when_timer_expires():
    """A countdown that correctly shows "Abgelaufen" instead of restarting
    must not get boosted — only a note is added, confidence stays as-is
    (per the explicit no-auto-downgrade decision: false-negative risk in
    the comparison heuristic shouldn't turn into a false all-clear)."""
    finding = {
        "pattern_type": "Fake Urgency",
        "confidence_score": 0.7,
        "evidence_data": {"selector": "#countdown"},
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(COUNTDOWN_EXPIRES_FIXTURE_URL)
        await verify_countdown_reset(page, [finding])
        await browser.close()

    assert finding["confidence_score"] == 0.7
    assert "clock_verified" in finding["evidence_data"]
