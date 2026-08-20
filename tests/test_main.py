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


def test_start_scan_passes_llm_client_when_api_key_set(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))
    monkeypatch.setattr(main_module, "_LLM_CLIENT", "fake-client")

    received = {}

    async def fake_run_site_scan(url, conn, evidence_dir, browser=None, max_pages=None, llm_client=None):
        received["llm_client"] = llm_client
        from app.db import insert_scan
        return insert_scan(conn, url)

    monkeypatch.setattr(main_module, "run_site_scan", fake_run_site_scan)

    with TestClient(main_module.app) as client:
        client.post("/scans", data={"url": "https://example.com"}, follow_redirects=False)

    assert received["llm_client"] == "fake-client"


def test_start_scan_llm_client_none_without_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))
    monkeypatch.setattr(main_module, "_LLM_CLIENT", None)

    received = {}

    async def fake_run_site_scan(url, conn, evidence_dir, browser=None, max_pages=None, llm_client=None):
        received["llm_client"] = llm_client
        from app.db import insert_scan
        return insert_scan(conn, url)

    monkeypatch.setattr(main_module, "run_site_scan", fake_run_site_scan)

    with TestClient(main_module.app) as client:
        client.post("/scans", data={"url": "https://example.com"}, follow_redirects=False)

    assert received["llm_client"] is None


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


def test_start_scan_from_extension_forwards_cookies_and_returns_scan_id(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    received = {}

    async def fake_run_site_scan(url, conn, evidence_dir, browser=None, max_pages=None, llm_client=None, url_validator=None, cookies=None):
        received["url"] = url
        received["cookies"] = cookies
        from app.db import insert_scan
        return insert_scan(conn, url)

    monkeypatch.setattr(main_module, "run_site_scan", fake_run_site_scan)

    chrome_cookies = [
        {"name": "session", "value": "abc123", "domain": "example.com", "path": "/",
         "secure": True, "httpOnly": True, "sameSite": "lax", "expirationDate": 1999999999.0},
    ]

    with TestClient(main_module.app) as client:
        response = client.post(
            "/scans/extension",
            json={"url": "https://example.com", "cookies": chrome_cookies},
        )

    assert response.status_code == 200
    assert isinstance(response.json()["scan_id"], int)
    assert received["url"] == "https://example.com"
    assert received["cookies"] == chrome_cookies


def test_start_scan_from_extension_rejects_unsafe_url(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    with TestClient(main_module.app) as client:
        response = client.post(
            "/scans/extension",
            json={"url": "file:///etc/passwd", "cookies": []},
        )
        assert response.status_code == 400


def test_start_scan_from_extension_returns_409_when_captcha_required(tmp_path, monkeypatch):
    from app.crawler import CaptchaRequiredError

    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    async def fake_run_site_scan(*args, **kwargs):
        raise CaptchaRequiredError("https://example.com")

    monkeypatch.setattr(main_module, "run_site_scan", fake_run_site_scan)

    with TestClient(main_module.app) as client:
        response = client.post(
            "/scans/extension",
            json={"url": "https://example.com", "cookies": []},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == {"error": "captcha_required", "url": "https://example.com"}


def test_start_scan_returns_409_when_captcha_required(tmp_path, monkeypatch):
    from app.crawler import CaptchaRequiredError

    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    async def fake_run_site_scan(*args, **kwargs):
        raise CaptchaRequiredError("https://example.com")

    monkeypatch.setattr(main_module, "run_site_scan", fake_run_site_scan)

    with TestClient(main_module.app) as client:
        response = client.post("/scans", data={"url": "https://example.com"}, follow_redirects=False)

    assert response.status_code == 409
    assert "https://example.com" in response.json()["detail"]


def test_page_detail_shows_findings_for_one_page(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    from app.db import init_db, insert_scan, insert_page, insert_finding

    conn = init_db(str(tmp_path / "test.db"))
    scan_id = insert_scan(conn, "https://example.com")
    page_id = insert_page(conn, scan_id, "https://example.com/checkout", "checkout_payment")
    insert_finding(
        conn, scan_id,
        {"pattern_type": "Trick Questions", "target_norm": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
         "confidence_score": 0.7, "evidence_data": {}},
        page_id=page_id,
    )
    conn.close()

    with TestClient(main_module.app) as client:
        response = client.get(f"/scans/{scan_id}/pages/{page_id}")

    assert response.status_code == 200
    assert "Trick Questions" in response.text


def test_scan_detail_lists_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    from app.db import init_db, insert_scan, insert_page

    conn = init_db(str(tmp_path / "test.db"))
    scan_id = insert_scan(conn, "https://example.com")
    insert_page(conn, scan_id, "https://example.com/checkout", "checkout_payment")
    conn.close()

    with TestClient(main_module.app) as client:
        response = client.get(f"/scans/{scan_id}")

    assert response.status_code == 200
    assert "checkout_payment" in response.text
