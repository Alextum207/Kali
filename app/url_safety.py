"""Server-side URL validation to stop the crawler being used as an SSRF proxy.

POST /scans hands an arbitrary user-supplied URL to a real headless Chromium.
Without this check a caller could point it at file:// paths, cloud metadata
IPs (169.254.169.254), or internal services (localhost, private ranges) and
have the result stored as "evidence".
"""
import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}


def _is_unsafe_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    # is_private doesn't consistently cover loopback/link-local across Python
    # versions, so check them explicitly in addition.
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def validate_scan_url(url: str) -> None:
    """Raises ValueError with a human-readable reason if `url` is unsafe to crawl."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"URL scheme {parsed.scheme!r} is not allowed (only http/https)")
    if not parsed.hostname:
        raise ValueError("URL has no hostname")

    try:
        addrinfo = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host {parsed.hostname!r}: {exc}") from exc

    for *_rest, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        if _is_unsafe_ip(ip_str):
            raise ValueError(
                f"URL host {parsed.hostname!r} resolves to a private/loopback/link-local "
                f"address ({ip_str}) and is not allowed"
            )
