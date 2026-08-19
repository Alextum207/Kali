import logging
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def discover_links(dom_html: str, base_url: str, allowed_hosts: set[str]) -> list[str]:
    """Extracts internal navigation links from a page. Filters to
    `allowed_hosts` (exact match or subdomain), drops anchors/mailto/tel/js
    links, and dedupes. Does NOT enforce http(s)-only or SSRF safety — that
    is `app.url_safety.validate_scan_url`'s job, applied by the caller
    before navigating to any of these URLs."""
    soup = BeautifulSoup(dom_html, "html.parser")
    seen: set[str] = set()
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href).split("#")[0]
        parsed = urlparse(absolute)
        host = parsed.hostname or ""
        if not any(host == h or host.endswith("." + h) for h in allowed_hosts):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)
    return links
