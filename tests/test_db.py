from app.db import init_db, insert_scan, insert_finding, get_findings, get_scan

def test_scan_and_findings_roundtrip():
    conn = init_db(":memory:")
    scan_id = insert_scan(conn, "https://example.com")
    assert isinstance(scan_id, int)

    finding = {
        "pattern_type": "Confirm Shaming",
        "target_norm": "Art. 25 DSA",
        "confidence_score": 0.82,
        "evidence_data": {"screenshot_path": "shot.png"},
    }
    finding_id = insert_finding(conn, scan_id, finding)
    assert isinstance(finding_id, int)

    findings = get_findings(conn, scan_id)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Confirm Shaming"
    assert findings[0]["confidence_score"] == 0.82
    assert findings[0]["evidence_data"]["screenshot_path"] == "shot.png"

    scan = get_scan(conn, scan_id)
    assert scan["url"] == "https://example.com"


def test_pages_and_page_scoped_findings_roundtrip():
    from app.db import insert_page, get_pages, get_page_findings

    conn = init_db(":memory:")
    scan_id = insert_scan(conn, "https://example.com")
    page_id = insert_page(conn, scan_id, "https://example.com/checkout", "checkout_payment")
    assert isinstance(page_id, int)

    finding = {
        "pattern_type": "Trick Questions",
        "target_norm": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
        "confidence_score": 0.75,
        "evidence_data": {"selector_a": "#a", "selector_b": "#b"},
    }
    finding_id = insert_finding(conn, scan_id, finding, page_id=page_id)
    assert isinstance(finding_id, int)

    pages = get_pages(conn, scan_id)
    assert len(pages) == 1
    assert pages[0]["url"] == "https://example.com/checkout"
    assert pages[0]["category"] == "checkout_payment"

    page_findings = get_page_findings(conn, page_id)
    assert len(page_findings) == 1
    assert page_findings[0]["pattern_type"] == "Trick Questions"

    # backward compatible: existing scan-level insert (no page_id) still works
    legacy_finding = {
        "pattern_type": "Confirm Shaming",
        "target_norm": "Art. 25 DSA",
        "confidence_score": 0.8,
        "evidence_data": {},
    }
    insert_finding(conn, scan_id, legacy_finding)
    assert len(get_findings(conn, scan_id)) == 2


def test_init_db_adds_page_id_column_idempotently(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn1 = init_db(db_path)
    conn1.close()
    conn2 = init_db(db_path)  # second run on the same file must not raise
    cols = [row[1] for row in conn2.execute("PRAGMA table_info(findings)")]
    assert "page_id" in cols
    conn2.close()
