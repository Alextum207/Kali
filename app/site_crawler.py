import asyncio
import hashlib
import json
import logging
import os
import pathlib
import time
import uuid
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.crawler import (
    DEFAULT_CONSENT_RULES_DIR,
    NAV_TIMEOUT_MS,
    CaptchaRequiredError,
    _looks_like_captcha,
    _snapshot_page,
    apply_consent_rules,
)
import httpx

from app.llm_utils import extract_text
from app.robots import USER_AGENT, RobotsDisallowedError, fetch_robots_parser
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
MAX_FLOW_STEPS = int(os.environ.get("MAX_FLOW_STEPS", "3"))

# context.close() (which flushes the HAR file) can itself hang on a real,
# heavy site — confirmed against amazon.de: after several pages generating
# a lot of recorded network traffic, the finally-block close() never
# returned. It's the crawl's very last await with no bound of its own, so a
# hang there means the whole scan hangs forever even though every page was
# already crawled successfully. Bounding it here means we lose (at worst) an
# incomplete HAR on a pathological site instead of hanging the scan.
CONTEXT_CLOSE_TIMEOUT_SECONDS = int(os.environ.get("CONTEXT_CLOSE_TIMEOUT_SECONDS", "30"))

# Cache for classify_page_category's LLM fallback ONLY — a routing decision
# (which queue bucket a URL belongs to), never for dark-pattern findings.
# Keyed on url+DOM-content-hash so any content change invalidates it.
_CATEGORY_CACHE: dict[str, tuple[str, float]] = {}
_CATEGORY_CACHE_TTL_SECONDS = int(os.environ.get("CATEGORY_CACHE_TTL_SECONDS", "600"))


def _category_cache_key(url: str, dom_html: str) -> str:
    return f"{url}:{hashlib.sha256(dom_html.encode('utf-8', 'ignore')).hexdigest()}"


def _predict_category_from_url(url: str) -> str:
    """Cheap, DOM-free category guess for queue ordering only — the real
    classification (classify_page_category) still runs once the page is
    actually visited."""
    haystack = url.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return category
    return "other"


async def _llm_classify_category(url: str, dom_html: str, client) -> str:
    import re

    soup = BeautifulSoup(dom_html, "html.parser")
    main_content = soup.find("main") or soup.find("article")
    # ponytail: best-effort <main>/<article> detection only, not full
    # boilerplate-stripping — pages without either tag fall back to
    # whole-page truncation as before; upgrade if that proves insufficient.
    source_html = str(main_content) if main_content else dom_html
    text_sample = re.sub(r"<[^>]+>", " ", source_html)[:1500]
    prompt = (
        "Klassifiziere folgende Webseite in genau eine Kategorie: "
        "cookie_consent, checkout_payment, product_category, account_subscription, "
        "popup_leadform, other. Antworte NUR mit dem Kategorie-Namen, nichts sonst.\n\n"
        f"URL: {url}\n\nSeiteninhalt (Auszug): {text_sample}"
    )
    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=20,
        messages=[{"role": "user", "content": prompt}],
    )
    result = extract_text(response).strip().lower()
    return result if result in PAGE_CATEGORIES else "other"


async def classify_page_category(url: str, dom_html: str, llm_client=None) -> str:
    haystack = url.lower()
    soup = BeautifulSoup(dom_html, "html.parser")
    heading = soup.find(["h1", "h2"])
    if heading:
        haystack += " " + heading.get_text(strip=True).lower()

    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return category

    if llm_client is not None:
        key = _category_cache_key(url, dom_html)
        cached = _CATEGORY_CACHE.get(key)
        if cached is not None and time.monotonic() - cached[1] < _CATEGORY_CACHE_TTL_SECONDS:
            return cached[0]
        try:
            category = await _llm_classify_category(url, dom_html, llm_client)
        except Exception as exc:  # noqa: BLE001 - deliberate broad catch, LLM call
            logger.warning("LLM category classification failed, using 'other': %s", exc)
            return "other"
        _CATEGORY_CACHE[key] = (category, time.monotonic())
        return category

    return "other"


# Keywords for flow-critical actions (cancel/checkout/cart) — used to
# reorder clickable elements so these survive decide_next_interaction's
# [:40] cap even when they sit deep in DOM order (e.g. behind a long nav).
_INTERACTION_KEYWORDS = (
    "kündig", "abbrechen", "zur kasse", "warenkorb", "bestellen", "checkout",
)


def _sort_by_interaction_keywords(elements: list[dict]) -> list[dict]:
    """Stable-sorts clickable elements, keyword matches first, so the real
    'Kündigen'/'Zur Kasse' button isn't dropped by the [:40] cap just
    because nav/footer links precede it in DOM order."""
    def relevance(el: dict) -> int:
        text = el.get("text", "").lower()
        return 0 if any(kw in text for kw in _INTERACTION_KEYWORDS) else 1

    return sorted(elements, key=relevance)


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


async def decide_next_interaction(category: str, clickable_elements: list[dict], llm_client=None) -> dict | None:
    goal = _INTERACTION_GOALS.get(category)
    if not goal or not clickable_elements or llm_client is None:
        return None

    sorted_elements = _sort_by_interaction_keywords(clickable_elements)
    elements_text = "\n".join(
        f'- "{el["text"]}" (selector: {el["selector"]})' for el in sorted_elements[:40]
    )
    prompt = (
        f"Ziel: {goal}\n\n"
        f"Anklickbare Elemente auf der aktuellen Seite:\n{elements_text}\n\n"
        'Antworte AUSSCHLIESSLICH mit einem JSON-Objekt {"type": "click", "target": "<selector>"} '
        'für das nächste sinnvolle Element, oder {"type": "none"}, falls kein Element zum Ziel passt.'
    )
    try:
        response = await llm_client.messages.create(
            model="claude-sonnet-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        result = json.loads(extract_text(response))
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
            """els => els.slice(0, 200).map(el => ({
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
    page,
    category: str,
    snapshot: dict,
    llm_client=None,
    max_extra_pages: int = 0,
    start_time: float | None = None,
    time_budget_seconds: float | None = None,
) -> tuple[dict, list[dict]]:
    """Repeats decide_next_interaction + click for the page's category
    (checkout, cancellation, product, popup, ...) until the flow's own goal
    is reached (no further interaction target), the category changes (flow
    left its target area), or MAX_FLOW_STEPS fires as a safety net — instead
    of a fixed number of pages per category, which doesn't fit flows of
    very different natural length (a cookie banner vs. a 4-step checkout).

    start_time/time_budget_seconds (both optional, same contract as
    crawl_site's) let this loop stop starting new steps once the overall
    crawl budget is exhausted — checked once per iteration, not preemptive,
    so a click/sleep/snapshot already in flight still runs to completion.

    Returns the (possibly updated, if the last step didn't navigate) snapshot
    for the page that was already appended by the caller, plus a list of
    additional page dicts for every step that navigated to a new URL."""
    extra_pages: list[dict] = []
    for _ in range(MAX_FLOW_STEPS):
        if len(extra_pages) >= max_extra_pages:
            break
        if (
            start_time is not None
            and time_budget_seconds is not None
            and time.monotonic() - start_time >= time_budget_seconds
        ):
            break
        clickable = await _extract_clickable_elements(page)
        interaction = await decide_next_interaction(category, clickable, llm_client=llm_client)
        if not interaction or not interaction.get("target"):
            break
        try:
            el = await page.query_selector(interaction["target"])
            if not el or not await el.is_visible():
                break
            before_url = page.url
            await el.click(timeout=2000)
            # ponytail: unmeasured guess, not benchmarked against real
            # scans — matches the settle-wait duration already used for
            # _check_infinite_scroll's scroll sleeps (site_crawler.py:241);
            # tune with real timing data if flows still misfire or this
            # proves wastefully long.
            await asyncio.sleep(0.5)
            navigated = page.url != before_url
            # A real click can navigate into a state _snapshot_page can't
            # read back cleanly (login/bot wall, stalled AJAX) — its own
            # SNAPSHOT_TIMEOUT_SECONDS bounds that, and this try/except
            # treats a timeout the same as any other broken flow step:
            # stop the flow, keep the last good snapshot, don't fail the
            # whole crawl over one live-site interaction going sideways.
            new_snapshot = await _snapshot_page(page, skip_diff_sleep=navigated)
        except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
            logger.debug("crawl_site: flow interaction click failed: %s", exc)
            break

        snapshot = new_snapshot
        new_category = await classify_page_category(page.url, snapshot["dom_after"], llm_client=llm_client)

        if navigated:
            extra_pages.append(
                {
                    "url": page.url,
                    "category": new_category,
                    "dom_after": snapshot["dom_after"],
                    "screenshot": snapshot["screenshot"],
                    "button_styles": snapshot["button_styles"],
                    "contrast_findings": snapshot["contrast_findings"],
                    "countdown_findings": snapshot["countdown_findings"],
                    "infinite_scroll_detected": False,
                    "reject_option_missing": snapshot.get("reject_option_missing", False),
                    "cookie_wall_detected": snapshot.get("cookie_wall_detected", False),
                    "banner_screenshot": snapshot.get("banner_screenshot"),
                    "text_boxes": snapshot.get("text_boxes", []),
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
    time_budget_seconds: float | None = None,
) -> dict:
    """DFS crawl of a whole site starting from start_url, staying within the
    start URL's host + subdomains. One shared browser context (one HAR file
    for the whole site). start_url itself is trusted (the caller already
    validated it, same contract as crawl_page) — every link DISCOVERED
    during the crawl is re-validated with `url_validator` before being
    queued, since those were never seen by the caller.

    time_budget_seconds caps how long the loop keeps discovering/visiting
    NEW pages (checked once per iteration, not preemptive) — a page already
    in flight, including its flow-walk, always runs to completion, so actual
    wall time can exceed the budget by up to one page's worst case."""
    from urllib.parse import urlparse

    if time_budget_seconds is None:
        time_budget_seconds = float(os.environ.get("SCAN_TIME_BUDGET_SECONDS", "25"))
    start_time = time.monotonic()

    pathlib.Path(har_dir).mkdir(parents=True, exist_ok=True)
    har_path = str(pathlib.Path(har_dir) / f"site-crawl-{uuid.uuid4().hex}.har")
    context = await browser.new_context(record_har_path=har_path)

    async with httpx.AsyncClient() as robots_client:
        robots_parser = await fetch_robots_parser(start_url, robots_client)
    if not robots_parser.can_fetch(USER_AGENT, start_url):
        await context.close()
        raise RobotsDisallowedError(start_url)

    start_host = urlparse(start_url).hostname or ""
    allowed_hosts = {start_host}

    # Two-tier stack instead of plain LIFO: links predicted (by cheap URL
    # heuristic) to hit one of the 3 target categories are visited before
    # everything else, so a big site doesn't burn its whole max_pages budget
    # on generic pages before reaching checkout/account/product pages. Both
    # tiers are stacks (pop from the end) so the crawl dives depth-first
    # into a discovered flow instead of fanning out breadth-first.
    priority_queue = [start_url]
    other_queue: list[str] = []
    visited: set[str] = set()
    pages: list[dict] = []
    completed_categories: set[str] = set()

    try:
        while (
            (priority_queue or other_queue)
            and len(pages) < max_pages
            and (time.monotonic() - start_time) < time_budget_seconds
        ):
            url = priority_queue.pop() if priority_queue else other_queue.pop()
            if url in visited:
                continue
            visited.add(url)

            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                consent_result = await apply_consent_rules(page, consent_rules_dir)
                # _snapshot_page's own SNAPSHOT_TIMEOUT_SECONDS bounds a page
                # stuck mid-navigation (login/bot wall, stalled AJAX) —
                # caught here like any other broken-page load, so one bad
                # URL is skipped instead of aborting the whole site scan.
                snapshot = await _snapshot_page(page, consent_result=consent_result, browser=browser)
            except Exception as exc:  # noqa: BLE001 - deliberate broad catch, a dead link shouldn't kill the crawl
                logger.warning("crawl_site: failed to load %r: %s", url, exc)
                await page.close()
                continue

            if url == start_url and _looks_like_captcha(snapshot["dom_after"]):
                await page.close()
                raise CaptchaRequiredError(url)

            category = await classify_page_category(url, snapshot["dom_after"], llm_client=llm_client)
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
                "countdown_findings": snapshot["countdown_findings"],
                "infinite_scroll_detected": infinite_scroll,
                "reject_option_missing": snapshot["reject_option_missing"],
                "cookie_wall_detected": snapshot["cookie_wall_detected"],
                "banner_screenshot": snapshot["banner_screenshot"],
                "text_boxes": snapshot["text_boxes"],
            }
            pages.append(initial_page)

            # Flow-driven walk: keeps clicking through this category's goal
            # (checkout, cancellation, ...) until it's done, not a fixed page
            # count — see _walk_category_flow docstring.
            updated_snapshot, flow_pages = await _walk_category_flow(
                page,
                category,
                snapshot,
                llm_client=llm_client,
                max_extra_pages=max_pages - len(pages),
                start_time=start_time,
                time_budget_seconds=time_budget_seconds,
            )
            initial_page["dom_after"] = updated_snapshot["dom_after"]
            initial_page["screenshot"] = updated_snapshot["screenshot"]
            initial_page["button_styles"] = updated_snapshot["button_styles"]
            initial_page["contrast_findings"] = updated_snapshot["contrast_findings"]
            initial_page["countdown_findings"] = updated_snapshot["countdown_findings"]
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
                if not robots_parser.can_fetch(USER_AGENT, link):
                    logger.info("crawl_site: skipping robots.txt-disallowed link %r", link)
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
        try:
            # Flushes the HAR file to disk — see CONTEXT_CLOSE_TIMEOUT_SECONDS
            # docstring above for why this needs a bound.
            await asyncio.wait_for(context.close(), timeout=CONTEXT_CLOSE_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 - deliberate broad catch, best-effort HAR flush
            logger.warning("crawl_site: context.close() timed out or failed (HAR may be incomplete): %s", exc)

    return {"pages": pages, "har_path": har_path}
