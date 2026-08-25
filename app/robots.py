"""robots.txt-Respekt: prüft die Start-URL vor jedem Scan und jeden neu
entdeckten Link während des Crawls gegen das robots.txt der Zieldomain.
Ein Disallow auf der Start-URL bricht den gesamten Scan sofort ab, bevor
irgendeine Seite besucht wird — kein Umgehen, keine Teilerhebung.
ponytail: nur das robots.txt der Start-Domain wird geladen (keine
Subdomain-eigenen robots.txt), da crawl_site sowieso nur innerhalb von
Start-Host + Subdomains bleibt."""
import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "KaliDarkPatternMonitor"


class RobotsDisallowedError(Exception):
    """Raised when the target site's robots.txt disallows the start URL —
    the scan aborts before visiting any page. Same pattern as
    CaptchaRequiredError in app/crawler.py."""

    def __init__(self, url: str):
        super().__init__(f"robots.txt disallows scanning: {url}")
        self.url = url


async def fetch_robots_parser(base_url: str, client: httpx.AsyncClient) -> RobotFileParser:
    """Fetches and parses robots.txt for base_url's origin. Fail-open
    (allows everything) if robots.txt is missing (4xx/5xx) or unreachable
    (timeout, unsupported scheme like file://, DNS failure) — a missing
    robots.txt is the normal case for most sites, not a reason to abort."""
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        response = await client.get(robots_url, timeout=5.0)
        if response.status_code >= 400:
            parser.parse([])
        else:
            parser.parse(response.text.splitlines())
    except Exception as exc:  # noqa: BLE001 - network call, fail open by design
        logger.info("robots.txt fetch failed for %r: %s — allowing all", robots_url, exc)
        parser.parse([])
    return parser
