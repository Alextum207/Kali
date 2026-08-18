import hashlib
import os
import logging

import rfc3161ng

logger = logging.getLogger(__name__)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_evidence(data: bytes, out_path: str) -> str:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    return sha256_bytes(data)


def rfc3161_timestamp(data: bytes, tsa_url: str = "http://freetsa.org/tsr") -> bytes | None:
    """Requests an official RFC3161 timestamp token. Returns None (never raises)
    if the TSA is unreachable — a scan must not fail just because a free
    timestamp authority is down."""
    try:
        timestamper = rfc3161ng.RemoteTimestamper(tsa_url, hashname="sha256")
        return timestamper.timestamp(data=data)
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, network call
        logger.warning("RFC3161 timestamp failed: %s", exc)
        return None
