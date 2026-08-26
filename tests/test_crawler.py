import asyncio
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
    _capture_text_element_boxes,
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


def test_looks_like_captcha_ignores_dormant_recaptcha_loader_script():
    # Regression: be-gipsy.de (Weebly) preloads this on every page for a
    # contact-form widget that's never rendered — no captcha ever shown.
    dom = '<html><head><script>_W.recaptchaUrl = "https://www.google.com/recaptcha/api.js";</script></head><body><h1>Shop</h1></body></html>'
    assert _looks_like_captcha(dom) is False


def test_looks_like_captcha_detects_turnstile():
    dom = '<html><body><div class="cf-turnstile" data-sitekey="x"></div></body></html>'
    assert _looks_like_captcha(dom) is True

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
async def test_snapshot_page_times_out_instead_of_hanging_forever(monkeypatch):
    """Root cause of a real-world crawl hang: _snapshot_page's Playwright
    calls (page.content(), etc.) have no timeout of their own — NAV_TIMEOUT_MS
    only bounds the initial page.goto(). A real site can leave the page in a
    state where page.content() never resolves (e.g. mid-navigation after a
    flow-walk click into a login/bot wall) — _snapshot_page must bound that
    with its own timeout instead of hanging the whole crawl forever."""
    import app.crawler as crawler_module

    monkeypatch.setattr(crawler_module, "SNAPSHOT_TIMEOUT_SECONDS", 0.5)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(FIXTURE_URL)

        async def hangs_forever(*args, **kwargs):
            await asyncio.Event().wait()

        monkeypatch.setattr(page, "content", hangs_forever)

        start = time.monotonic()
        with pytest.raises(asyncio.TimeoutError):
            await _snapshot_page(page)
        elapsed = time.monotonic() - start

        await browser.close()

    assert elapsed < 5.0  # bounded by SNAPSHOT_TIMEOUT_SECONDS, not left hanging


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
async def test_find_low_contrast_legal_text_ignores_promotional_price_copy():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("""
            <main>
              <h1 style="color:#111;background:#fff">Shop</h1>
              <p style="color:#111;background:#fff">Normale Produktbeschreibung</p>
              <span style="color:#fff;background:#fff">Preishits auf CD</span>
              <span style="color:#fff;background:#fff">Preiswerte Empfehlungen</span>
              <span style="color:#fff;background:#fff">tolino eReader zum Aktionspreis</span>
            </main>
        """)
        findings = await find_low_contrast_legal_text(page)
        await browser.close()

    assert findings == []


@pytest.mark.asyncio
async def test_find_low_contrast_legal_text_ignores_small_but_readable_legal_link():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("""
            <main>
              <h1 style="color:#777;background:#fff">Pricing</h1>
              <a style="font-size:10px;color:#000;background:#fff">Privacy Policy</a>
            </main>
        """)
        findings = await find_low_contrast_legal_text(page)
        await browser.close()

    assert findings == []


@pytest.mark.asyncio
async def test_find_low_contrast_legal_text_ignores_short_legal_navigation_links():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("""
            <main>
              <h1 style="color:#111;background:#fff">Docs</h1>
              <a style="color:#eee;background:#fff">Privacy</a>
              <a style="color:#eee;background:#fff">Terms</a>
              <a style="color:#eee;background:#fff">AGB</a>
            </main>
        """)
        findings = await find_low_contrast_legal_text(page)
        await browser.close()

    assert findings == []


@pytest.mark.asyncio
async def test_find_low_contrast_legal_text_does_not_match_fee_inside_words():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("""
            <main>
              <h1 style="color:#111;background:#fff">Documentation</h1>
              <a style="color:#eee;background:#fff">Feed exports</a>
              <span style="color:#eee;background:#fff">5 free projects are included</span>
            </main>
        """)
        findings = await find_low_contrast_legal_text(page)
        await browser.close()

    assert findings == []


@pytest.mark.asyncio
async def test_find_low_contrast_legal_text_ignores_hidden_elements():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("""
            <main>
              <h1 style="color:#111;background:#fff">Checkout</h1>
              <p style="display:none;color:#fff;background:#fff">Kündigung nur schriftlich möglich.</p>
              <p style="visibility:hidden;color:#fff;background:#fff">Gesamtpreis zzgl. Servicegebühr.</p>
            </main>
        """)
        findings = await find_low_contrast_legal_text(page)
        await browser.close()

    assert findings == []


@pytest.mark.asyncio
async def test_find_low_contrast_legal_text_flags_hidden_cost_notice():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("""
            <main>
              <h1 style="color:#111;background:#fff">Checkout</h1>
              <p style="color:#111;background:#fff">Sichtbarer Bestellhinweis</p>
              <p style="font-size:8px;color:#fff;background:#fff">Gesamtpreis zzgl. Versandkosten und Servicegebühr.</p>
            </main>
        """)
        findings = await find_low_contrast_legal_text(page)
        await browser.close()

    assert len(findings) == 1
    assert "versandkosten" in findings[0]["evidence_data"]["excerpt"].lower()


@pytest.mark.asyncio
async def test_capture_text_element_boxes_returns_position_and_text():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(FIXTURE_URL)
        boxes = await _capture_text_element_boxes(page)
        await browser.close()

    texts = {b["text"] for b in boxes}
    assert "Akzeptieren" in texts
    assert "Ablehnen" in texts
    accept_box = next(b for b in boxes if b["text"] == "Akzeptieren")
    assert accept_box["width"] > 0 and accept_box["height"] > 0


TALL_PAGE_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/tall_page_with_below_fold_text.html"
).as_uri()


@pytest.mark.asyncio
async def test_snapshot_page_captures_full_page_so_below_fold_quotes_stay_in_bounds():
    """Regression: found via a real scan against amazon.de — every
    'markiert ansehen' (annotated) evidence image was pixel-identical to
    the plain screenshot. Root cause: _snapshot_page's page.screenshot()
    had no full_page=True, so it only captured the viewport (Playwright's
    1280x720 default) — but _capture_text_element_boxes reports
    getBoundingClientRect() positions for every leaf text element on the
    whole page, including ones below the fold. Highlighting a below-fold
    quote against a viewport-only screenshot draws the marker outside the
    captured image — silently invisible, no error, no crash."""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(TALL_PAGE_URL)
        snapshot = await _snapshot_page(page)
        await browser.close()

    below_fold_box = next(b for b in snapshot["text_boxes"] if b["text"] == "9,99 Euro ab dem 2. Monat")
    assert below_fold_box["y"] > 720  # genuinely below Playwright's default viewport height

    from PIL import Image
    import io
    img = Image.open(io.BytesIO(snapshot["screenshot"]))
    assert img.size[1] > below_fold_box["y"]  # the capture must actually extend that far down

    from app.analysis.screenshot_annotate import highlight_quote_in_screenshot
    annotated = highlight_quote_in_screenshot(
        snapshot["screenshot"], "9,99 Euro ab dem 2. Monat", snapshot["text_boxes"]
    )
    assert annotated is not None
    assert annotated != snapshot["screenshot"]  # something was actually drawn, not silently a no-op


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
async def test_detect_cookie_wall_times_out_instead_of_hanging_forever():
    """Regression: page.evaluate() has no timeout of its own — a stalled
    page (confirmed live against amazon.de/verbraucherzentrale.de) used to
    hang this check forever, burning the whole per-page
    CONSENT_TIMEOUT_SECONDS budget on one call. Must fail fast instead."""

    class _HangingPage:
        async def evaluate(self, _script):
            await asyncio.sleep(3600)  # never resolves within the test

    detected = await asyncio.wait_for(_detect_cookie_wall(_HangingPage()), timeout=6)
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


@pytest.mark.asyncio
async def test_apply_consent_rules_captures_banner_screenshot_before_reject_click(tmp_path):
    """A screenshot of the banner must exist as its own evidence artifact,
    taken before the reject click removes it from the page — otherwise
    there's no proof of what the banner actually looked like."""
    rules_dir = _write_rule(tmp_path, "asymmetric.json", ASYMMETRIC_RULE)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(ASYMMETRIC_CONSENT_FIXTURE_URL)
        result = await apply_consent_rules(page, rules_dir)
        await browser.close()

    assert result["banner_screenshot"] is not None
    assert isinstance(result["banner_screenshot"], bytes)


@pytest.mark.asyncio
async def test_apply_consent_rules_banner_screenshot_none_when_no_banner_present(tmp_path):
    rules_dir = _write_rule(tmp_path, "no_reject.json", NO_REJECT_RULE)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(FIXTURE_URL)
        result = await apply_consent_rules(page, rules_dir)
        await browser.close()

    assert result["banner_screenshot"] is None


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
        result = await verify_countdown_reset(page, [finding], browser=browser)
        await browser.close()

    assert result == [finding]  # confirmed reset -> kept
    assert finding["confidence_score"] > 0.7
    assert "clock_verified" in finding["evidence_data"]


COUNTDOWN_EXPIRES_FIXTURE_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/countdown_expires_page.html"
).as_uri()


@pytest.mark.asyncio
async def test_verify_countdown_reset_drops_finding_when_timer_expires_correctly():
    """A countdown that correctly shows "Abgelaufen" instead of restarting
    isn't manipulative — it must not be reported as a Fake Urgency finding
    at all (only confirmed resets get labeled, not every element that
    merely matches a countdown-ish CSS class/id)."""
    finding = {
        "pattern_type": "Fake Urgency",
        "confidence_score": 0.7,
        "evidence_data": {"selector": "#countdown"},
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(COUNTDOWN_EXPIRES_FIXTURE_URL)
        result = await verify_countdown_reset(page, [finding], browser=browser)
        await browser.close()

    assert result == []


class _FakeClock:
    async def install(self):
        pass

    async def fast_forward(self, duration):
        pass


class _FakeCountdownLocator:
    def __init__(self, page):
        self._page = page

    async def inner_text(self, timeout=None):
        return next(self._page._locator_texts)


class _FakeCountdownLocatorWrapper:
    def __init__(self, page):
        self.first = _FakeCountdownLocator(page)


class _FakeCountdownPage:
    """Deterministic double for verify_countdown_reset's page argument — real
    browser timing (see debug against countdown_reset_page.html) can make
    text_before == text_after by coincidence (a full-value reset lands
    exactly back on the same displayed string), so the diff-capture logic
    itself is tested here with controlled inputs instead of relying on a
    real fixture's timing."""

    def __init__(self, locator_texts, body_texts):
        self.clock = _FakeClock()
        self.url = "https://example.com/deal"
        self._locator_texts = iter(locator_texts)
        self._body_texts = iter(body_texts)

    async def reload(self):
        pass

    def locator(self, selector):
        return _FakeCountdownLocatorWrapper(self)

    async def inner_text(self, selector):
        return next(self._body_texts)


@pytest.mark.asyncio
async def test_verify_countdown_reset_records_time_diff_sample():
    from app.crawler import verify_countdown_reset

    finding = {
        "pattern_type": "Fake Urgency",
        "confidence_score": 0.7,
        "evidence_data": {"selector": "#countdown"},
    }
    page = _FakeCountdownPage(
        locator_texts=["02:00", "02:00"],
        body_texts=["Angebot endet in: 02:00", "Angebot endet in: 01:55 - Neuer Hinweis"],
    )

    await verify_countdown_reset(page, [finding])

    assert "time_diff_sample" in finding["evidence_data"]
    assert "01:55" in finding["evidence_data"]["time_diff_sample"]


def test_parse_timer_seconds_handles_mmss_and_hhmmss():
    from app.crawler import _parse_timer_seconds

    assert _parse_timer_seconds("02:00") == 120
    assert _parse_timer_seconds("01:02:03") == 3723
    assert _parse_timer_seconds("no digits here") is None


class _FakeLocator:
    def __init__(self, text):
        self._text = text

    async def inner_text(self, timeout=None):
        return self._text


class _FakeLocatorWrapper:
    def __init__(self, text):
        self.first = _FakeLocator(text)


class _FakePageB:
    def __init__(self, text):
        self._text = text

    async def goto(self, url, wait_until=None, timeout=None):
        pass

    def locator(self, selector):
        return _FakeLocatorWrapper(self._text)


class _FakeContext:
    def __init__(self, page_b):
        self._page_b = page_b
        self.closed = False

    async def new_page(self):
        return self._page_b

    async def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, page_b):
        self._page_b = page_b

    async def new_context(self):
        return _FakeContext(self._page_b)


class _FakePageA:
    url = "https://example.com/deal"


@pytest.mark.asyncio
async def test_verify_cross_session_countdown_flags_matching_value():
    from app.crawler import _verify_cross_session_countdown

    finding = {"confidence_score": 0.7, "evidence_data": {}}
    browser = _FakeBrowser(_FakePageB("02:00"))

    await _verify_cross_session_countdown(_FakePageA(), browser, "#countdown", "02:00", finding)

    assert finding["confidence_score"] > 0.7
    assert "cross_session_match" in finding["evidence_data"]


@pytest.mark.asyncio
async def test_verify_cross_session_countdown_ignores_different_value():
    from app.crawler import _verify_cross_session_countdown

    finding = {"confidence_score": 0.7, "evidence_data": {}}
    browser = _FakeBrowser(_FakePageB("01:30"))

    await _verify_cross_session_countdown(_FakePageA(), browser, "#countdown", "02:00", finding)

    assert finding["confidence_score"] == 0.7
    assert "cross_session_match" not in finding["evidence_data"]
