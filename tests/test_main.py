from fastapi.testclient import TestClient
import app.main as main_module


def test_start_scan_and_view_findings(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    async def fake_run_site_scan(url, conn, evidence_dir, browser=None, max_pages=None, llm_client=None):
        from app.db import insert_scan, insert_finding
        scan_id = insert_scan(conn, url)
        insert_finding(conn, scan_id, {
            "pattern_type": "Confirm Shaming",
            "target_norm": "Art. 25 DSA",
            "confidence_score": 0.8,
            "evidence_data": {"quote": "No thanks"},
        })
        return scan_id

    monkeypatch.setattr(main_module, "run_site_scan", fake_run_site_scan)

    with TestClient(main_module.app) as client:
        response = client.post("/scans", data={"url": "https://example.com"}, follow_redirects=False)
        assert response.status_code == 303  # redirect to scan detail
        scan_url = response.headers["location"]

        detail = client.get(scan_url)
        assert detail.status_code == 200
        assert "Confirm Shaming" in detail.text


def test_start_scan_accepts_optional_max_pages_field(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    received = {}

    async def fake_run_site_scan(url, conn, evidence_dir, browser=None, max_pages=None, llm_client=None):
        received["max_pages"] = max_pages
        from app.db import insert_scan
        return insert_scan(conn, url)

    monkeypatch.setattr(main_module, "run_site_scan", fake_run_site_scan)

    with TestClient(main_module.app) as client:
        response = client.post("/scans", data={"url": "https://example.com", "max_pages": "3"}, follow_redirects=False)

    assert response.status_code == 303
    assert received["max_pages"] == 3


def test_dashboard_renders():
    with TestClient(main_module.app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Scan starten" in response.text


def test_scan_detail_404_for_missing_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    with TestClient(main_module.app) as client:
        response = client.get("/scans/9999")
        assert response.status_code == 404


def test_scan_report_404_for_missing_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    with TestClient(main_module.app) as client:
        response = client.get("/scans/9999/report.pdf")
        assert response.status_code == 404


def test_start_scan_rejects_unsafe_url(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    with TestClient(main_module.app) as client:
        response = client.post("/scans", data={"url": "file:///etc/passwd"}, follow_redirects=False)
        assert response.status_code == 400
