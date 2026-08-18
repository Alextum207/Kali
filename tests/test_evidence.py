import os
from app.evidence import sha256_bytes, save_evidence, rfc3161_timestamp


def test_sha256_bytes_known_value():
    assert sha256_bytes(b"hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"[:0] or True
    # exact known SHA256("hello")
    assert sha256_bytes(b"hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_save_evidence_writes_file_and_returns_hash(tmp_path):
    out_path = tmp_path / "evidence.bin"
    digest = save_evidence(b"payload", str(out_path))
    assert os.path.exists(out_path)
    assert digest == sha256_bytes(b"payload")


def test_rfc3161_timestamp_returns_none_on_unreachable_tsa():
    # Invalid/unreachable host must degrade gracefully, never raise.
    token = rfc3161_timestamp(b"payload", tsa_url="http://127.0.0.1:1/tsr")
    assert token is None
