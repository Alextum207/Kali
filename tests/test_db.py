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
