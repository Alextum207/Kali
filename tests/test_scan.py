import asyncio
import os
import time

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
    monkeypatch.setattr("app.scan.rfc3161_timestamp", lambda data: None)

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
    monkeypatch.setattr("app.scan.rfc3161_timestamp", lambda data: None)

    conn = init_db(":memory:")
    scan_id = await run_scan("https://example.com", conn, str(tmp_path), browser=None)

    findings = get_findings(conn, scan_id)
    assert findings[0]["evidence_data"]["citation"] is None


@pytest.mark.asyncio
async def test_run_scan_does_not_block_on_slow_rfc3161(tmp_path, monkeypatch):
    """rfc3161_timestamp's result is discarded (best-effort) — run_scan must
    not wait for it. Compares a fast vs. a deliberately slow (0.5s)
    rfc3161_timestamp: if it were awaited, run_scan would take ~0.5s longer
    in the slow case. Uses a relative comparison, not an absolute wall-clock
    threshold, since run_scan's own baseline (e.g. httpx.AsyncClient
    setup/teardown) already varies noticeably across machines/environments —
    an absolute threshold would be measuring that noise, not the fire-and-
    forget behavior this test actually cares about."""
    async def fake_crawl_page(url, browser, har_dir=None):
        return _fake_crawl_result(har_dir)

    async def fake_run_analysis(dom_html, button_styles, llm_client=None):
        return []

    monkeypatch.setattr("app.scan.crawl_page", fake_crawl_page)
    monkeypatch.setattr("app.scan.run_analysis", fake_run_analysis)

    conn = init_db(":memory:")

    monkeypatch.setattr("app.scan.rfc3161_timestamp", lambda data: None)
    start = time.monotonic()
    await run_scan("https://example.com", conn, str(tmp_path), browser=None)
    fast_elapsed = time.monotonic() - start

    def slow_rfc3161(data):
        time.sleep(0.5)
        return None

    monkeypatch.setattr("app.scan.rfc3161_timestamp", slow_rfc3161)
    start = time.monotonic()
    await run_scan("https://example.com", conn, str(tmp_path), browser=None)
    slow_elapsed = time.monotonic() - start

    # If rfc3161_timestamp were awaited, slow_elapsed would be ~0.5s more
    # than fast_elapsed. Fire-and-forget means the difference should be
    # small — well under half of the 0.5s the slow mock actually sleeps.
    assert slow_elapsed - fast_elapsed < 0.25


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
    monkeypatch.setattr("app.scan.rfc3161_timestamp", lambda data: None)

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


@pytest.mark.asyncio
async def test_run_site_scan_caches_citation_fetch_per_norm(tmp_path, monkeypatch):
    """Two pages each produce a finding mapping to the same target_norm —
    fetch_citation must be called once for that norm, not once per finding."""
    har_file = tmp_path / "site-citation-cache.har"
    har_file.write_bytes(b"{}")
    site_result = {
        "pages": [
            {
                "url": "https://example.com/a",
                "category": "other",
                "dom_after": "<html><body><input type='checkbox' id='nl' checked></body></html>",
                "screenshot": b"\x89PNG-fake-bytes-a",
                "button_styles": None,
                "infinite_scroll_detected": False,
            },
            {
                "url": "https://example.com/b",
                "category": "other",
                "dom_after": "<html><body><input type='checkbox' id='nl' checked></body></html>",
                "screenshot": b"\x89PNG-fake-bytes-b",
                "button_styles": None,
                "infinite_scroll_detected": False,
            },
        ],
        "har_path": str(har_file),
    }

    async def fake_crawl_site(start_url, browser, max_pages, har_dir, llm_client=None):
        return site_result

    async def fake_run_analysis(dom_html, button_styles, llm_client=None, page=None):
        return [
            {
                "pattern_type": "Pre-ticked Box",
                "target_norm": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
                "confidence_score": 0.9,
                "evidence_data": {"selector": "#nl"},
            }
        ]

    citation_calls = {"n": 0}

    async def fake_fetch_citation(norm, base_url, client=None):
        citation_calls["n"] += 1
        return f"citation for {norm}"

    monkeypatch.setattr("app.scan.crawl_site", fake_crawl_site)
    monkeypatch.setattr("app.scan.run_analysis", fake_run_analysis)
    monkeypatch.setattr("app.scan.fetch_citation", fake_fetch_citation)
    monkeypatch.setattr("app.scan.rfc3161_timestamp", lambda data: None)

    conn = init_db(":memory:")
    scan_id = await run_site_scan("https://example.com", conn, str(tmp_path), browser=None, max_pages=5)

    all_scan_findings = get_findings(conn, scan_id)
    assert len(all_scan_findings) == 2  # one finding per page
    assert citation_calls["n"] == 1  # but only one fetch — both share the same norm


@pytest.mark.asyncio
async def test_run_site_scan_respects_analysis_concurrency_limit(tmp_path, monkeypatch):
    """Post-crawl per-page analysis must not run more than
    SCAN_ANALYSIS_CONCURRENCY pages' worth of work at once."""
    har_file = tmp_path / "site-concurrency.har"
    har_file.write_bytes(b"{}")
    site_result = {
        "pages": [
            {
                "url": f"https://example.com/{i}",
                "category": "other",
                "dom_after": "<html><body>page</body></html>",
                "screenshot": f"\x89PNG-fake-{i}".encode(),
                "button_styles": None,
                "infinite_scroll_detected": False,
            }
            for i in range(6)
        ],
        "har_path": str(har_file),
    }

    async def fake_crawl_site(start_url, browser, max_pages, har_dir, llm_client=None):
        return site_result

    in_flight = {"current": 0, "max_seen": 0}

    async def fake_run_analysis(dom_html, button_styles, llm_client=None, page=None):
        in_flight["current"] += 1
        in_flight["max_seen"] = max(in_flight["max_seen"], in_flight["current"])
        await asyncio.sleep(0.05)  # hold the slot long enough for overlap to be observable
        in_flight["current"] -= 1
        return []

    monkeypatch.setattr("app.scan.crawl_site", fake_crawl_site)
    monkeypatch.setattr("app.scan.run_analysis", fake_run_analysis)
    monkeypatch.setattr("app.scan.rfc3161_timestamp", lambda data: None)
    monkeypatch.setattr("app.scan._ANALYSIS_CONCURRENCY", 2)

    conn = init_db(":memory:")
    await run_site_scan("https://example.com", conn, str(tmp_path), browser=None, max_pages=10)

    assert in_flight["max_seen"] <= 2


@pytest.mark.asyncio
async def test_run_site_scan_sets_impact_for_contrast_and_infinite_scroll_findings(tmp_path, monkeypatch):
    """Contrast/infinite-scroll findings are built directly in scan.py, not
    via app.analysis.pipeline.run_analysis — they must still get an
    'impact' entry (from pipeline.IMPACT_MAP) like every other finding does,
    for the Auswirkung column in scan_detail.html/report.html."""
    har_file = tmp_path / "site-impact.har"
    har_file.write_bytes(b"{}")
    site_result = {
        "pages": [
            {
                "url": "https://example.com",
                "category": "other",
                "dom_after": "<html><body>page</body></html>",
                "screenshot": b"\x89PNG-fake",
                "button_styles": None,
                "infinite_scroll_detected": True,
                "contrast_findings": [
                    {
                        "pattern_type": "Visuelle Tarnung (Kontrast)",
                        "confidence_score": 0.6,
                        "evidence_data": {"selector": "p.legal"},
                    }
                ],
            },
        ],
        "har_path": str(har_file),
    }

    async def fake_crawl_site(start_url, browser, max_pages, har_dir, llm_client=None):
        return site_result

    async def fake_run_analysis(dom_html, button_styles, llm_client=None, page=None):
        return []

    monkeypatch.setattr("app.scan.crawl_site", fake_crawl_site)
    monkeypatch.setattr("app.scan.run_analysis", fake_run_analysis)
    monkeypatch.setattr("app.scan.rfc3161_timestamp", lambda data: None)

    conn = init_db(":memory:")
    scan_id = await run_site_scan("https://example.com", conn, str(tmp_path), browser=None, max_pages=5)

    findings = get_findings(conn, scan_id)
    by_type = {f["pattern_type"]: f for f in findings}
    assert by_type["Visuelle Tarnung (Kontrast)"]["evidence_data"]["impact"] != "–"
    assert by_type["Exploiting Addiction (Infinite Scroll)"]["evidence_data"]["impact"] != "–"
