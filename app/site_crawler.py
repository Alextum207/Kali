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

# The 3 categories predictable from a URL alone (unlike cookie_consent and
# popup_leadform, which are states detected on whatever page they occur on,
# not link targets to steer toward) — used to prioritize the crawl queue.
TARGET_CATEGORIES = ("checkout_payment", "account_subscription", "product_category")

# Safety cap on decide_next_interaction/click loops within one category flow
# (e.g. multi-step checkout) — a ceiling against dead-loop pages, not a goal.
MAX_FLOW_STEPS = 5


def _predict_category_from_url(url: str) -> str:
    """Cheap, DOM-free category guess for queue ordering only — the real
    classification (classify_page_category) still runs once the page is
    actually visited."""
    haystack = url.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return category
    return "other"


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


async def _walk_category_flow(
    page, category: str, snapshot: dict, llm_client=None, max_extra_pages: int = 0
) -> tuple[dict, list[dict]]:
    """Repeats decide_next_interaction + click for the page's category
    (checkout, cancellation, product, popup, ...) until the flow's own goal
    is reached (no further interaction target), the category changes (flow
    left its target area), or MAX_FLOW_STEPS fires as a safety net — instead
    of a fixed number of pages per category, which doesn't fit flows of
    very different natural length (a cookie banner vs. a 4-step checkout).

    Returns the (possibly updated, if the last step didn't navigate) snapshot
    for the page that was already appended by the caller, plus a list of
    additional page dicts for every step that navigated to a new URL."""
    extra_pages: list[dict] = []
    for _ in range(MAX_FLOW_STEPS):
        if len(extra_pages) >= max_extra_pages:
            break
        clickable = await _extract_clickable_elements(page)
        interaction = decide_next_interaction(category, clickable, llm_client=llm_client)
        if not interaction or not interaction.get("target"):
            break
        try:
            el = await page.query_selector(interaction["target"])
            if not el or not await el.is_visible():
                break
            before_url = page.url
            await el.click(timeout=2000)
            await asyncio.sleep(1.0)
        except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
            logger.debug("crawl_site: flow interaction click failed: %s", exc)
            break

        snapshot = await _snapshot_page(page)
        new_category = classify_page_category(page.url, snapshot["dom_after"], llm_client=llm_client)

        if page.url != before_url:
            extra_pages.append(
                {
                    "url": page.url,
                    "category": new_category,
                    "dom_after": snapshot["dom_after"],
                    "screenshot": snapshot["screenshot"],
                    "button_styles": snapshot["button_styles"],
                    "contrast_findings": snapshot["contrast_findings"],
                    "infinite_scroll_detected": False,
                }
            )

        if new_category != category:
            break
        category = new_category

    return snapshot, extra_pages


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

    # Two-tier queue instead of plain FIFO: links predicted (by cheap URL
    # heuristic) to hit one of the 3 target categories are visited before
    # everything else, so a big site doesn't burn its whole max_pages budget
    # on generic pages before reaching checkout/account/product pages.
    priority_queue = [start_url]
    other_queue: list[str] = []
    visited: set[str] = set()
    pages: list[dict] = []
    completed_categories: set[str] = set()

    try:
        while (priority_queue or other_queue) and len(pages) < max_pages:
            url = priority_queue.pop(0) if priority_queue else other_queue.pop(0)
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

            initial_page = {
                "url": url,
                "category": category,
                "dom_after": snapshot["dom_after"],
                "screenshot": snapshot["screenshot"],
                "button_styles": snapshot["button_styles"],
                "contrast_findings": snapshot["contrast_findings"],
                "infinite_scroll_detected": infinite_scroll,
            }
            pages.append(initial_page)

            # Flow-driven walk: keeps clicking through this category's goal
            # (checkout, cancellation, ...) until it's done, not a fixed page
            # count — see _walk_category_flow docstring.
            updated_snapshot, flow_pages = await _walk_category_flow(
                page, category, snapshot, llm_client=llm_client, max_extra_pages=max_pages - len(pages)
            )
            initial_page["dom_after"] = updated_snapshot["dom_after"]
            initial_page["screenshot"] = updated_snapshot["screenshot"]
            initial_page["button_styles"] = updated_snapshot["button_styles"]
            initial_page["contrast_findings"] = updated_snapshot["contrast_findings"]
            pages.extend(flow_pages)
            for flow_page in flow_pages:
                visited.add(flow_page["url"])
            for visited_page in [initial_page, *flow_pages]:
                if visited_page["category"] in TARGET_CATEGORIES:
                    completed_categories.add(visited_page["category"])

            all_targets_done = len(completed_categories) >= len(TARGET_CATEGORIES)
            for link in discover_links(snapshot["dom_after"], url, allowed_hosts):
                if link in visited or link in priority_queue or link in other_queue:
                    continue
                try:
                    url_validator(link)
                except ValueError as exc:
                    logger.info("crawl_site: skipping unsafe discovered link %r: %s", link, exc)
                    continue
                predicted = _predict_category_from_url(link)
                if predicted in TARGET_CATEGORIES:
                    # Always keep following target-category links, even if
                    # that category was already visited once — e.g. cart.html
                    # and checkout.html both predict checkout_payment, but
                    # checkout.html is a deeper step of the same flow, not a
                    # duplicate. "Completed" only gates generic other links.
                    priority_queue.append(link)
                elif not all_targets_done:
                    other_queue.append(link)
                # else: all 3 target categories already covered and this is
                # a generic link — drop it, that's the point of focusing.

            await page.close()
    finally:
        await context.close()  # flushes the HAR file to disk

    return {"pages": pages, "har_path": har_path}
