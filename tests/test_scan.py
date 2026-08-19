import os

import pytest
from app.db import init_db, get_findings
from app.evidence import sha256_bytes
from app.scan import run_scan
from app.db import get_pages, get_page_findings
from app.scan import run_site_scan

FAKE_HAR_BYTES = b'{"log": {"fake": true}}'


def _fake_crawl_result(har_dir):
    har_path = os.path.join(har_dir, "fake-crawl.har")
    with open(har_path, "wb") as f:
        f.write(FAKE_HAR_BYTES)
    return {
        "dom_before": "<html><body><input type='checkbox' id='nl' checked></body></html>",
        "dom_after": "<html><body><input type='checkbox' id='nl' checked></body></html>",
        "screenshot": b"\x89PNG-fake-bytes",
        "har_path": har_path,
        "button_styles": None,
    }


@pytest.mark.asyncio
async def test_run_scan_persists_findings_with_evidence(tmp_path, monkeypatch):
    async def fake_crawl_page(url, browser, har_dir=None):
        assert har_dir == str(tmp_path)
        return _fake_crawl_result(har_dir)

    async def fake_run_analysis(dom_html, button_styles, llm_client=None):
        return [
            {
                "pattern_type": "Pre-ticked Box",
                "target_norm": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
                "confidence_score": 0.9,
                "evidence_data": {"selector": "#nl"},
            }
        ]

    async def fake_fetch_citation(norm, base_url, client=None):
        return f"citation for {norm}"

    monkeypatch.setattr("app.scan.crawl_page", fake_crawl_page)
    monkeypatch.setattr("app.scan.run_analysis", fake_run_analysis)
    monkeypatch.setattr("app.scan.fetch_citation", fake_fetch_citation)

    conn = init_db(":memory:")
    scan_id = await run_scan("https://example.com", conn, str(tmp_path), browser=None)

    findings = get_findings(conn, scan_id)
    assert len(findings) == 1
    evidence = findings[0]["evidence_data"]
    assert "screenshot_sha256" in evidence
    assert "screenshot_path" in evidence
    assert evidence["har_path"].startswith(str(tmp_path))
    assert evidence["har_sha256"] == sha256_bytes(FAKE_HAR_BYTES)
    assert evidence["citation"] == "citation for Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO"


@pytest.mark.asyncio
async def test_run_scan_citation_none_does_not_crash(tmp_path, monkeypatch):
    async def fake_crawl_page(url, browser, har_dir=None):
        return _fake_crawl_result(har_dir)

    async def fake_run_analysis(dom_html, button_styles, llm_client=None):
        return [
            {
                "pattern_type": "Pre-ticked Box",
                "target_norm": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
                "confidence_score": 0.9,
                "evidence_data": {"selector": "#nl"},
            }
        ]

    async def fake_fetch_citation(norm, base_url, client=None):
        return None

    monkeypatch.setattr("app.scan.crawl_page", fake_crawl_page)
    monkeypatch.setattr("app.scan.run_analysis", fake_run_analysis)
    monkeypatch.setattr("app.scan.fetch_citation", fake_fetch_citation)

    conn = init_db(":memory:")
    scan_id = await run_scan("https://example.com", conn, str(tmp_path), browser=None)

    findings = get_findings(conn, scan_id)
    assert findings[0]["evidence_data"]["citation"] is None


FAKE_SITE_RESULT = {
    "pages": [
        {
            "url": "https://example.com",
            "category": "other",
            "dom_after": "<html><body><input type='checkbox' id='nl' checked></body></html>",
            "screenshot": b"\x89PNG-fake-bytes-1",
            "button_styles": None,
            "infinite_scroll_detected": False,
        },
        {
            "url": "https://example.com/checkout",
            "category": "checkout_payment",
            "dom_after": "<html><body><p>checkout page</p></body></html>",
            "screenshot": b"\x89PNG-fake-bytes-2",
            "button_styles": None,
            "infinite_scroll_detected": False,
        },
    ],
    "har_path": "",  # set to a real temp file path in the test setup below
}


@pytest.mark.asyncio
async def test_run_site_scan_persists_pages_and_page_scoped_findings(tmp_path, monkeypatch):
    har_file = tmp_path / "site.har"
    har_file.write_bytes(b"{}")
    FAKE_SITE_RESULT["har_path"] = str(har_file)

    async def fake_crawl_site(start_url, browser, max_pages, har_dir, llm_client=None):
        return FAKE_SITE_RESULT

    call_count = {"n": 0}

    async def fake_run_analysis(dom_html, button_styles, llm_client=None, page=None):
        call_count["n"] += 1
        if "checkbox" in dom_html:
            return [
                {
                    "pattern_type": "Pre-ticked Box",
                    "target_norm": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
                    "confidence_score": 0.9,
                    "evidence_data": {"selector": "#nl"},
                }
            ]
        return []

    monkeypatch.setattr("app.scan.crawl_site", fake_crawl_site)
    monkeypatch.setattr("app.scan.run_analysis", fake_run_analysis)

    conn = init_db(":memory:")
    scan_id = await run_site_scan("https://example.com", conn, str(tmp_path), browser=None, max_pages=5)

    pages = get_pages(conn, scan_id)
    assert len(pages) == 2
    assert {p["category"] for p in pages} == {"other", "checkout_payment"}

    checkout_page = next(p for p in pages if p["category"] == "checkout_payment")
    other_page = next(p for p in pages if p["category"] == "other")

    assert get_page_findings(conn, other_page["id"])[0]["pattern_type"] == "Pre-ticked Box"
    assert get_page_findings(conn, checkout_page["id"]) == []

    all_scan_findings = get_findings(conn, scan_id)
    assert len(all_scan_findings) == 1
    evidence = all_scan_findings[0]["evidence_data"]
    assert "har_path" in evidence and "har_sha256" in evidence
    assert "screenshot_path" in evidence and "screenshot_sha256" in evidence
