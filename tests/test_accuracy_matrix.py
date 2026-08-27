import pathlib

import pytest
from playwright.async_api import async_playwright

from app.db import get_findings, init_db
from app.scan import run_site_scan


FIXTURE_ROOT = pathlib.Path(__file__).parent / "fixtures" / "accuracy_matrix"


class _FakeBlock:
    def __init__(self, text):
        self.text = text
        self.type = "text"


class _FakeToolUseBlock:
    def __init__(self, name, input_):
        self.type = "tool_use"
        self.name = name
        self.input = input_


class _FakeMessage:
    def __init__(self, content):
        self.content = [_FakeBlock(content)] if isinstance(content, str) else content


class _ScriptedLLMClient:
    """Returns scripted click decisions, and no text findings."""

    class _Messages:
        def __init__(self, outer):
            self._outer = outer

        async def create(self, **kwargs):
            prompt_text = str(kwargs.get("messages", [{}])[0].get("content", ""))
            if "AUSSCHLIESSLICH mit einem JSON-Objekt" in prompt_text:
                idx = min(self._outer.calls, len(self._outer.responses) - 1)
                self._outer.calls += 1
                return _FakeMessage(self._outer.responses[idx])
            tools = kwargs.get("tools") or []
            if tools and tools[0].get("name") == "report_findings":
                return _FakeMessage([_FakeToolUseBlock("report_findings", {"findings": []})])
            return _FakeMessage("other")

    def __init__(self, responses=None):
        self.responses = list(responses or ['{"type": "none"}'])
        self.calls = 0
        self.messages = self._Messages(self)


async def _scan_fixture(tmp_path, fixture_name: str, *, max_pages: int = 1, llm_client=None):
    url = (FIXTURE_ROOT / fixture_name / "index.html").as_uri()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        conn = init_db(":memory:")
        scan_id = await run_site_scan(
            url,
            conn,
            str(tmp_path),
            browser,
            max_pages=max_pages,
            llm_client=llm_client or _ScriptedLLMClient(),
            url_validator=lambda url: None,
        )
        await browser.close()
    return get_findings(conn, scan_id)


def _types(findings):
    return {finding["pattern_type"] for finding in findings}


@pytest.mark.asyncio
async def test_docs_examples_do_not_trigger_text_pattern_false_positives(tmp_path):
    findings = await _scan_fixture(tmp_path, "docs_examples")
    pattern_types = _types(findings)

    assert "Fake Scarcity" not in pattern_types
    assert "Fake Social Proof" not in pattern_types
    assert "Forced Continuity" not in pattern_types
    assert "Fake Urgency" not in pattern_types


@pytest.mark.asyncio
async def test_real_product_scarcity_social_proof_and_urgency_still_work(tmp_path):
    findings = await _scan_fixture(tmp_path, "product_positive")
    pattern_types = _types(findings)

    assert "Fake Scarcity" in pattern_types
    assert "Fake Social Proof" in pattern_types
    assert "Fake Urgency" in pattern_types


@pytest.mark.asyncio
async def test_neutral_product_cards_do_not_trigger_marketplace_false_positives(tmp_path):
    findings = await _scan_fixture(tmp_path, "product_neutral")
    pattern_types = _types(findings)

    assert "Fake Scarcity" not in pattern_types
    assert "Fake Social Proof" not in pattern_types
    assert "Fake Urgency" not in pattern_types


@pytest.mark.asyncio
async def test_fair_cookie_banner_does_not_report_missing_reject(tmp_path):
    findings = await _scan_fixture(tmp_path, "cookie_fair")
    pattern_types = _types(findings)

    assert "Fehlende Reject-Option (Cookie-Banner)" not in pattern_types
    assert "Cookie Wall" not in pattern_types
    assert "Visuelle Asymmetrie (Button)" not in pattern_types


@pytest.mark.asyncio
async def test_non_cookie_ui_with_cookie_banner_id_does_not_report_cookie_finding(tmp_path):
    findings = await _scan_fixture(tmp_path, "cookie_non_consent_ui")
    pattern_types = _types(findings)

    assert "Fehlende Reject-Option (Cookie-Banner)" not in pattern_types
    assert "Cookie Wall" not in pattern_types


@pytest.mark.asyncio
async def test_cookie_banner_without_reject_is_still_reported(tmp_path):
    findings = await _scan_fixture(tmp_path, "cookie_no_reject")

    assert "Fehlende Reject-Option (Cookie-Banner)" in _types(findings)


@pytest.mark.asyncio
async def test_signup_default_consent_is_reported_but_plain_optout_is_not(tmp_path):
    default_consent = await _scan_fixture(tmp_path, "signup_default_consent")
    plain_optout = await _scan_fixture(tmp_path, "settings_plain_optout")

    assert "Trick Questions" in _types(default_consent)
    assert "Trick Questions" not in _types(plain_optout)


@pytest.mark.asyncio
async def test_checkout_flow_hidden_fee_is_reported_by_real_crawler_flow(tmp_path):
    client = _ScriptedLLMClient([
        '{"type": "click", "target": "a"}',
        '{"type": "none"}',
    ])
    url = (FIXTURE_ROOT / "checkout_hidden_fee" / "step1.html").as_uri()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        conn = init_db(":memory:")
        scan_id = await run_site_scan(
            url,
            conn,
            str(tmp_path),
            browser,
            max_pages=5,
            llm_client=client,
            url_validator=lambda url: None,
        )
        await browser.close()

    assert "Sneaking / Hidden Costs" in _types(get_findings(conn, scan_id))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fixture_name", "expected_pattern"),
    [
        # autoplay_positive/decoy_positive intentionally NOT here anymore:
        # both were recalibrated to 0.5 confidence (below
        # pipeline.MIN_CONFIDENCE=0.6) because a single autoplay attribute or
        # a single decoy-pricing pair is a weak, generic signal on its own —
        # see test_weak_signal_patterns_need_corroboration below, which
        # covers the intended new behavior for both. low_contrast_positive
        # stays here: find_low_contrast_legal_text runs via
        # crawler.py's _snapshot_page, outside run_analysis's MIN_CONFIDENCE
        # filter, so it's unaffected by that recalibration.
        ("low_contrast_positive", "Visuelle Tarnung (Kontrast)"),
    ],
)
async def test_other_positive_patterns_remain_detectable(tmp_path, fixture_name, expected_pattern):
    findings = await _scan_fixture(tmp_path, fixture_name)

    assert expected_pattern in _types(findings)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fixture_name", "expected_pattern"),
    [
        ("autoplay_positive", "Exploiting Addiction (Autoplay)"),
        ("decoy_positive", "Decoy Pricing"),
    ],
)
async def test_weak_signal_patterns_need_corroboration(tmp_path, fixture_name, expected_pattern):
    """Autoplay/Decoy Pricing were deliberately recalibrated to 0.5 confidence
    (precision-over-recall pass) — a lone occurrence no longer clears
    pipeline.MIN_CONFIDENCE=0.6, on the reasoning that a single generic
    attribute/pricing-pair signal is too weak to report by itself. Guards
    against silently regressing that decision back to "always report"."""
    findings = await _scan_fixture(tmp_path, fixture_name)
    assert expected_pattern not in _types(findings)
