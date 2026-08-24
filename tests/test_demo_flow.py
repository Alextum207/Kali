"""Minimal regression suite for the submission-safe demo flow (Start-URL ->
Crawl -> Erkennung -> Report -> UI). Not meant to duplicate existing
coverage — SSRF (tests/test_main.py::test_start_scan_rejects_unsafe_url,
tests/test_crawler.py's app.url_safety tests) and CAPTCHA
(tests/test_main.py::test_start_scan_marks_status_error_when_captcha_required,
tests/test_crawler.py's _looks_like_captcha tests) already have dedicated
tests — this file only pins down the specific guarantees the demo depends
on: the extension's JS is syntactically valid, the fake_shop fixture
produces at least 3 deterministic findings, and the PDF report route never
raises regardless of whether the real PDF engine is available.
"""
import glob
import pathlib
import subprocess

import pytest
from playwright.async_api import async_playwright

from app.db import init_db, get_findings
from app.scan import run_site_scan

FAKE_SHOP_URL = pathlib.Path(__file__).parent.joinpath("fixtures/fake_shop/index.html").as_uri()
EXTENSION_DIR = pathlib.Path(__file__).parent.parent / "vendor" / "pattern-highlighter" / "chrome"


def test_extension_javascript_is_syntactically_valid():
    """`node --check` over every .js file the extension ships — the same
    manual check used throughout development, pinned as an actual test so a
    future edit can't silently reintroduce a syntax error before a demo."""
    js_files = glob.glob(str(EXTENSION_DIR / "**" / "*.js"), recursive=True)
    assert js_files, "expected to find extension .js files"
    for path in js_files:
        result = subprocess.run(
            ["node", "--check", path], capture_output=True, text=True
        )
        assert result.returncode == 0, f"{path}: {result.stderr}"


def test_extension_consent_rules_json_is_valid():
    """The extension loads data/consent-rules.json at runtime
    (scripts/consent.js::loadRules) — a syntax error there would silently
    break cookie-banner detection for the whole extension, not just fail
    loudly like a JS syntax error would."""
    import json

    path = EXTENSION_DIR / "data" / "consent-rules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) > 0


@pytest.mark.asyncio
async def test_fake_shop_fixture_produces_at_least_three_deterministic_findings(tmp_path):
    """The demo's primary, network-independent path: scanning the local
    fake_shop fixture must reliably surface at least the 3 deterministic
    (non-LLM) pattern types it's built for, with no Anthropic API call
    needed (llm_client=None) — this is what the demo can rely on even if
    the network/API is unavailable during the presentation."""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        conn = init_db(":memory:")

        scan_id = await run_site_scan(
            FAKE_SHOP_URL, conn, str(tmp_path), browser,
            max_pages=10, llm_client=None,
            url_validator=lambda url: None,  # file:// fixtures aren't http(s)
        )

        await browser.close()

    findings = get_findings(conn, scan_id)
    pattern_types = {f["pattern_type"] for f in findings}

    assert len(findings) >= 3
    assert "Fake Urgency" in pattern_types
    assert "Trick Questions" in pattern_types
    assert "Visuelle Tarnung (Kontrast)" in pattern_types
    assert "Fehlende Reject-Option (Cookie-Banner)" in pattern_types


def test_scan_report_route_never_raises_regardless_of_pdf_engine(tmp_path, monkeypatch):
    """Covered in detail by
    tests/test_main.py::test_scan_report_falls_back_to_html_when_pdf_generation_fails
    and tests/test_reports.py — this test just pins the demo-critical
    guarantee in one place: the report route always returns 200, whether
    the real PDF engine (mocked in CI, broken on this dev machine per
    TECHNISCHE-UEBERSICHT.md) is available or not."""
    from fastapi.testclient import TestClient
    import app.main as main_module
    from app.db import init_db, insert_scan, insert_finding

    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    conn = init_db(str(tmp_path / "test.db"))
    scan_id = insert_scan(conn, "https://example.com")
    insert_finding(conn, scan_id, {
        "pattern_type": "Fake Urgency", "target_norm": "UWG §§ 5, 5a",
        "confidence_score": 0.7, "evidence_data": {},
    })
    conn.close()

    with TestClient(main_module.app) as client:
        response = client.get(f"/scans/{scan_id}/report.pdf")

    assert response.status_code == 200
