from fastapi.testclient import TestClient
import app.main as main_module


def test_start_scan_and_view_findings(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    async def fake_run_scan(url, conn, evidence_dir, browser=None):
        from app.db import insert_scan, insert_finding
        scan_id = insert_scan(conn, url)
        insert_finding(conn, scan_id, {
            "pattern_type": "Confirm Shaming",
            "target_norm": "Art. 25 DSA",
            "confidence_score": 0.8,
            "evidence_data": {"quote": "No thanks"},
        })
        return scan_id

    monkeypatch.setattr(main_module, "run_scan", fake_run_scan)

    client = TestClient(main_module.app)

    response = client.post("/scans", data={"url": "https://example.com"}, follow_redirects=False)
    assert response.status_code == 303  # redirect to scan detail
    scan_url = response.headers["location"]

    detail = client.get(scan_url)
    assert detail.status_code == 200
    assert "Confirm Shaming" in detail.text


def test_dashboard_renders():
    client = TestClient(main_module.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Scan starten" in response.text
