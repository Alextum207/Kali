import pytest
from app.url_safety import validate_scan_url


def test_rejects_file_scheme():
    with pytest.raises(ValueError):
        validate_scan_url("file:///etc/passwd")


def test_rejects_loopback_host():
    with pytest.raises(ValueError):
        validate_scan_url("http://127.0.0.1/admin")


def test_rejects_localhost_hostname():
    with pytest.raises(ValueError):
        validate_scan_url("http://localhost:8080/")


def test_rejects_link_local_metadata_ip():
    with pytest.raises(ValueError):
        validate_scan_url("http://169.254.169.254/latest/meta-data/")


def test_allows_normal_https_url():
    validate_scan_url("https://example.com")  # should not raise
