import pytest
from app.db import init_db, get_findings
from app.scan import run_scan

FAKE_CRAWL_RESULT = {
    "dom_before": "<html><body><input type='checkbox' id='nl' checked></body></html>",
    "dom_after": "<html><body><input type='checkbox' id='nl' checked></body></html>",
    "screenshot": b"\x89PNG-fake-bytes",
    "har_path": "/tmp/fake-crawl.har",
    "button_styles": None,
}


@pytest.mark.asyncio
async def test_run_scan_persists_findings_with_evidence(tmp_path, monkeypatch):
    async def fake_crawl_page(url, browser):
        return FAKE_CRAWL_RESULT

    def fake_run_analysis(dom_html, button_styles, llm_client=None):
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
    assert evidence["har_path"] == "/tmp/fake-crawl.har"
    assert evidence["citation"] == "citation for Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO"


@pytest.mark.asyncio
async def test_run_scan_citation_none_does_not_crash(tmp_path, monkeypatch):
    async def fake_crawl_page(url, browser):
        return FAKE_CRAWL_RESULT

    def fake_run_analysis(dom_html, button_styles, llm_client=None):
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
