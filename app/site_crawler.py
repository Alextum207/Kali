import asyncio
import json
import logging
import pathlib
import uuid
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.crawler import DEFAULT_CONSENT_RULES_DIR, _snapshot_page, apply_consent_rules
from app.url_safety import validate_scan_url

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


PAGE_CATEGORIES = (
    "cookie_consent",
    "checkout_payment",
    "product_category",
    "account_subscription",
    "popup_leadform",
    "other",
)

_CATEGORY_KEYWORDS = {
    "checkout_payment": ("checkout", "kasse", "warenkorb", "cart", "bestellung", "payment", "zahlung"),
    "account_subscription": ("/account", "/konto", "subscription", "kündig", "cancel", "mein abo"),
    "product_category": ("product", "produkt", "/p/", "kategorie", "category"),
}


def _llm_classify_category(url: str, dom_html: str, client) -> str:
    import re

    text_sample = re.sub(r"<[^>]+>", " ", dom_html)[:1500]
    prompt = (
        "Klassifiziere folgende Webseite in genau eine Kategorie: "
        "cookie_consent, checkout_payment, product_category, account_subscription, "
        "popup_leadform, other. Antworte NUR mit dem Kategorie-Namen, nichts sonst.\n\n"
        f"URL: {url}\n\nSeiteninhalt (Auszug): {text_sample}"
    )
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=20,
        messages=[{"role": "user", "content": prompt}],
    )
    result = response.content[0].text.strip().lower()
    return result if result in PAGE_CATEGORIES else "other"


def classify_page_category(url: str, dom_html: str, llm_client=None) -> str:
    haystack = url.lower()
    soup = BeautifulSoup(dom_html, "html.parser")
    heading = soup.find(["h1", "h2"])
    if heading:
        haystack += " " + heading.get_text(strip=True).lower()

    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return category

    if llm_client is not None:
        try:
            return _llm_classify_category(url, dom_html, llm_client)
        except Exception as exc:  # noqa: BLE001 - deliberate broad catch, LLM call
            logger.warning("LLM category classification failed, using 'other': %s", exc)

    return "other"


# One-line navigation goal per category; categories not listed here (or
# mapped to None) get no LLM-driven interaction — cookie_consent is already
# handled by apply_consent_rules, "other" has no specific journey to drive.
_INTERACTION_GOALS = {
    "checkout_payment": (
        "Klicke dich bis zum letzten Schritt vor der Zahlung durch "
        "(z.B. 'Weiter', 'Zur Kasse', 'Warenkorb ansehen'), aber löse "
        "NIEMALS eine echte Zahlung aus."
    ),
    "account_subscription": (
        "Suche einen Kündigungs- oder Konto-löschen-Link/Button und "
        "klicke ihn an, aber bestätige die Kündigung NICHT endgültig."
    ),
    "product_category": "Klicke auf ein Produkt und danach auf 'In den Warenkorb', falls vorhanden.",
    "popup_leadform": "Klicke den Schließen-Button (X) des Overlays, falls vorhanden.",
}


def decide_next_interaction(category: str, clickable_elements: list[dict], llm_client=None) -> dict | None:
    goal = _INTERACTION_GOALS.get(category)
    if not goal or not clickable_elements or llm_client is None:
        return None

    elements_text = "\n".join(
        f'- "{el["text"]}" (selector: {el["selector"]})' for el in clickable_elements[:40]
    )
    prompt = (
        f"Ziel: {goal}\n\n"
        f"Anklickbare Elemente auf der aktuellen Seite:\n{elements_text}\n\n"
        'Antworte AUSSCHLIESSLICH mit einem JSON-Objekt {"type": "click", "target": "<selector>"} '
        'für das nächste sinnvolle Element, oder {"type": "none"}, falls kein Element zum Ziel passt.'
    )
    try:
        response = llm_client.messages.create(
            model="claude-sonnet-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        result = json.loads(response.content[0].text)
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, LLM call
        logger.warning("decide_next_interaction failed, skipping: %s", exc)
        return None

    if result.get("type") == "click" and result.get("target"):
        return {"type": "click", "target": result["target"]}
    return None


async def _extract_clickable_elements(page) -> list[dict]:
    try:
        elements = await page.eval_on_selector_all(
            "a, button",
            """els => els.slice(0, 60).map(el => ({
                text: (el.textContent || el.value || '').trim().slice(0, 80),
                selector: el.tagName.toLowerCase() + (el.id ? '#' + el.id : ''),
            })).filter(e => e.text.length > 0)""",
        )
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
        logger.debug("_extract_clickable_elements failed: %s", exc)
        return []
    return elements


async def _check_infinite_scroll(page) -> bool:
    """Scrolls the page 3 times and checks whether the document keeps
    growing without bound — a technical proxy for infinite-scroll feeds,
    detectable within a single crawl (no multi-session behavioral data
    needed)."""
    try:
        heights = []
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)
            heights.append(await page.evaluate("document.body.scrollHeight"))
        return len(heights) >= 2 and heights[-1] > heights[0]
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
        logger.debug("_check_infinite_scroll failed: %s", exc)
        return False


async def crawl_site(
    start_url: str,
    browser,
    max_pages: int,
    har_dir: str,
    consent_rules_dir: str = DEFAULT_CONSENT_RULES_DIR,
    llm_client=None,
    url_validator=validate_scan_url,
) -> dict:
    """BFS crawl of a whole site starting from start_url, staying within the
    start URL's host + subdomains. One shared browser context (one HAR file
    for the whole site). start_url itself is trusted (the caller already
    validated it, same contract as crawl_page) — every link DISCOVERED
    during the crawl is re-validated with `url_validator` before being
    queued, since those were never seen by the caller."""
    from urllib.parse import urlparse

    pathlib.Path(har_dir).mkdir(parents=True, exist_ok=True)
    har_path = str(pathlib.Path(har_dir) / f"site-crawl-{uuid.uuid4().hex}.har")
    context = await browser.new_context(record_har_path=har_path)

    start_host = urlparse(start_url).hostname or ""
    allowed_hosts = {start_host}

    queue = [start_url]
    visited: set[str] = set()
    pages: list[dict] = []

    try:
        while queue and len(pages) < max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            page = await context.new_page()
            try:
                await page.goto(url)
            except Exception as exc:  # noqa: BLE001 - deliberate broad catch, a dead link shouldn't kill the crawl
                logger.warning("crawl_site: failed to load %r: %s", url, exc)
                await page.close()
                continue

            await apply_consent_rules(page, consent_rules_dir)
            snapshot = await _snapshot_page(page)
            category = classify_page_category(url, snapshot["dom_after"], llm_client=llm_client)
            infinite_scroll = (
                await _check_infinite_scroll(page) if category in ("product_category", "other") else False
            )

            clickable = await _extract_clickable_elements(page)
            interaction = decide_next_interaction(category, clickable, llm_client=llm_client)
            if interaction and interaction.get("target"):
                try:
                    el = await page.query_selector(interaction["target"])
                    if el and await el.is_visible():
                        await el.click(timeout=2000)
                        await asyncio.sleep(1.0)
                        snapshot["dom_after"] = await page.content()
                except Exception as exc:
                    logger.debug("crawl_site: interaction click failed: %s", exc)

            pages.append(
                {
                    "url": url,
                    "category": category,
                    "dom_after": snapshot["dom_after"],
                    "screenshot": snapshot["screenshot"],
                    "button_styles": snapshot["button_styles"],
                    "contrast_findings": snapshot["contrast_findings"],
                    "infinite_scroll_detected": infinite_scroll,
                }
            )

            for link in discover_links(snapshot["dom_after"], url, allowed_hosts):
                if link in visited or link in queue:
                    continue
                try:
                    url_validator(link)
                except ValueError as exc:
                    logger.info("crawl_site: skipping unsafe discovered link %r: %s", link, exc)
                    continue
                queue.append(link)

            await page.close()
    finally:
        await context.close()  # flushes the HAR file to disk

    return {"pages": pages, "har_path": har_path}
