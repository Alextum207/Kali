import asyncio
import logging
import os

import httpx

from app.crawler import crawl_page
from app.site_crawler import crawl_site, CHECKOUT_PAYMENT_CATEGORY
from app.analysis.heuristics import find_price_increase_in_flow
from app.analysis.pipeline import run_analysis, IMPACT_MAP
from app.analysis.screenshot_annotate import highlight_quote_in_screenshot
from app.evidence import save_evidence, sha256_bytes, rfc3161_timestamp
from app.compliance import fetch_citation, map_to_norm
from app.db import insert_scan, insert_finding, insert_page, mark_scan_status

logger = logging.getLogger(__name__)

LEGAL_TEXT_MCP_BASE_URL = os.environ.get("LEGAL_TEXT_MCP_BASE_URL", "http://localhost:8091")

# Analysis-phase-only concurrency (post-crawl: screenshot hashing, LLM text
# classification, citation fetch) — the crawl itself stays strictly
# sequential (one Playwright page at a time), this only parallelizes the
# independent I/O-bound work that happens after the browser is done with a
# page. DB writes (insert_page/insert_finding) are never done inside this
# concurrency — sqlite3.Connection isn't safe for concurrent use.
_ANALYSIS_CONCURRENCY = int(os.environ.get("SCAN_ANALYSIS_CONCURRENCY", "5"))

# Keeps a reference to fire-and-forget background tasks (RFC3161 timestamps)
# so they aren't garbage-collected mid-flight — asyncio only holds a weak
# reference to a task once nothing else does.
_background_tasks: set = set()

# Findings _crawl_time_findings builds directly from apply_consent_rules's
# consent_result (app/crawler.py) — the only ones a pre-close banner
# screenshot is evidence for.
_COOKIE_BANNER_PATTERN_TYPES = ("Fehlende Reject-Option (Cookie-Banner)", "Cookie Wall")


async def _save_banner_screenshot(page_data: dict, out_path: str) -> tuple[str | None, str | None]:
    """(path, sha256) for the pre-close cookie-banner screenshot, or
    (None, None) if this page never showed one (the common case — most
    pages don't re-show a banner once cookies are set)."""
    banner_screenshot = page_data.get("banner_screenshot")
    if not banner_screenshot:
        return None, None
    banner_hash = await asyncio.to_thread(save_evidence, banner_screenshot, out_path)
    return out_path, banner_hash


async def _save_annotated_screenshot(
    page_data: dict, quote: str, screenshot_bytes: bytes, out_path: str
) -> tuple[str | None, str | None]:
    """(path, sha256) for a copy of the page screenshot with the box that
    best matches `quote` highlighted, or (None, None) if there are no
    captured text boxes for this page or none of them match well enough —
    the finding then falls back to the plain screenshot, same as before
    this feature existed."""
    text_boxes = page_data.get("text_boxes")
    if not text_boxes:
        return None, None
    annotated = await asyncio.to_thread(highlight_quote_in_screenshot, screenshot_bytes, quote, text_boxes)
    if annotated is None:
        return None, None
    annotated_hash = await asyncio.to_thread(save_evidence, annotated, out_path)
    return out_path, annotated_hash


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _read_and_hash(path: str) -> str | None:
    """None if the HAR file doesn't exist — crawl_site's context.close()
    (which flushes the HAR) has its own CONTEXT_CLOSE_TIMEOUT_SECONDS bound
    and can abandon a slow flush on a heavy real site, leaving no file at
    `path` at all. That's now a known, accepted outcome (see
    site_crawler.py), not a reason to fail the whole scan over a missing
    piece of evidence."""
    try:
        with open(path, "rb") as f:
            return sha256_bytes(f.read())
    except FileNotFoundError:
        return None


def _crawl_time_findings(page_data: dict) -> list[dict]:
    """Findings that depend on crawl-time state run_analysis never sees
    (contrast scan, infinite-scroll, missing cookie-banner reject option,
    countdown-reset verification) — shared by run_scan (single page) and
    _analyze_page (site crawl) so neither path silently drops them."""
    findings = []
    for contrast_finding in page_data.get("contrast_findings", []):
        contrast_finding["target_norm"] = map_to_norm(contrast_finding["pattern_type"])
        contrast_finding["evidence_data"]["impact"] = IMPACT_MAP.get(contrast_finding["pattern_type"], "–")
        findings.append(contrast_finding)

    # Structural countdown candidates, already clock-verified by
    # app/crawler.py::_snapshot_page while the page was still live (see
    # verify_countdown_reset — needs a real page, can't run in the
    # DOM-string-only analysis pipeline).
    for countdown_finding in page_data.get("countdown_findings", []):
        countdown_finding["target_norm"] = map_to_norm(countdown_finding["pattern_type"])
        countdown_finding["evidence_data"]["impact"] = IMPACT_MAP.get(countdown_finding["pattern_type"], "–")
        findings.append(countdown_finding)

    if page_data.get("infinite_scroll_detected"):
        findings.append({
            "pattern_type": "Exploiting Addiction (Infinite Scroll)",
            "target_norm": map_to_norm("Exploiting Addiction (Infinite Scroll)"),
            "confidence_score": 0.6,
            "evidence_data": {
                "note": "document height grew across 3 scroll iterations without an end indicator",
                "impact": IMPACT_MAP.get("Exploiting Addiction (Infinite Scroll)", "–"),
            },
        })

    if page_data.get("reject_option_missing"):
        findings.append({
            "pattern_type": "Fehlende Reject-Option (Cookie-Banner)",
            "target_norm": map_to_norm("Fehlende Reject-Option (Cookie-Banner)"),
            "confidence_score": 0.5,
            "evidence_data": {
                "impact": IMPACT_MAP.get("Fehlende Reject-Option (Cookie-Banner)", "–"),
            },
        })

    # Distinct from "reject fehlt": a cookie wall additionally blocks the
    # main content itself (overflow:hidden while the banner shows), not
    # just the reject button being absent — see
    # app/crawler.py::_detect_cookie_wall for the passive-only check.
    if page_data.get("cookie_wall_detected"):
        findings.append({
            "pattern_type": "Cookie Wall",
            "target_norm": map_to_norm("Cookie Wall"),
            "confidence_score": 0.55,
            "evidence_data": {
                "note": "Hauptinhalt durch overflow:hidden blockiert, solange Consent-Banner sichtbar ist",
                "impact": IMPACT_MAP.get("Cookie Wall", "–"),
            },
        })

    return findings


def _checkout_price_increase_findings(
    page_ids: list[int], pages: list[dict], evidence_dir: str, scan_id: int
) -> list[tuple[dict, int]]:
    """Groups (page_id, page_data) pairs by flow_group (app/site_crawler.py
    ::crawl_site tags an initial_page and its flow_pages with the same id)
    and runs find_price_increase_in_flow on each checkout_payment group.
    Returns (finding, page_id) pairs ready for insert_finding — page_id is
    the LATER step's, where the price jump became visible; the earlier
    step's already-saved screenshot is attached as a second evidence image
    (baseline_screenshot_path) rather than a new one being taken."""
    groups: dict[int, list[tuple[int, dict]]] = {}
    for page_id, page_data in zip(page_ids, pages):
        flow_group = page_data.get("flow_group")
        if flow_group is None:
            continue
        groups.setdefault(flow_group, []).append((page_id, page_data))

    results = []
    for group in groups.values():
        if group[0][1].get("category") != CHECKOUT_PAYMENT_CATEGORY:
            continue
        group_pages = [page_data for _, page_data in group]
        for finding in find_price_increase_in_flow(group_pages):
            finding["target_norm"] = map_to_norm(finding["pattern_type"])
            finding["evidence_data"]["impact"] = IMPACT_MAP.get(finding["pattern_type"], "–")
            baseline_page_id = group[finding["evidence_data"]["baseline_page_index"]][0]
            later_page_id = group[finding["evidence_data"]["later_page_index"]][0]
            finding["evidence_data"]["screenshot_path"] = os.path.join(
                evidence_dir, f"scan_{scan_id}_page_{later_page_id}_screenshot.png"
            )
            finding["evidence_data"]["baseline_screenshot_path"] = os.path.join(
                evidence_dir, f"scan_{scan_id}_page_{baseline_page_id}_screenshot.png"
            )
            results.append((finding, later_page_id))
    return results


async def run_scan(url: str, conn, evidence_dir: str, browser=None) -> int:
    scan_id = insert_scan(conn, url)

    crawl_result = await crawl_page(url, browser, har_dir=evidence_dir)

    screenshot_path = os.path.join(evidence_dir, f"scan_{scan_id}_screenshot.png")
    screenshot_hash = await asyncio.to_thread(
        save_evidence, crawl_result["screenshot"], screenshot_path
    )
    # best-effort, stored hash is the primary proof — never block the scan
    # on a slow/unreachable free timestamp authority.
    _fire_and_forget(asyncio.to_thread(rfc3161_timestamp, crawl_result["screenshot"]))

    har_hash = await asyncio.to_thread(_read_and_hash, crawl_result["har_path"])

    banner_screenshot_path, banner_screenshot_hash = await _save_banner_screenshot(
        crawl_result, os.path.join(evidence_dir, f"scan_{scan_id}_banner_screenshot.png")
    )

    findings = await run_analysis(crawl_result["dom_after"], crawl_result["button_styles"])
    findings.extend(_crawl_time_findings(crawl_result))

    citation_cache: dict[str, str | None] = {}
    async with httpx.AsyncClient(base_url=LEGAL_TEXT_MCP_BASE_URL, timeout=5.0) as client:
        for i, finding in enumerate(findings):
            finding["evidence_data"]["screenshot_path"] = screenshot_path
            finding["evidence_data"]["screenshot_sha256"] = screenshot_hash
            finding["evidence_data"]["har_path"] = crawl_result["har_path"]
            finding["evidence_data"]["har_sha256"] = har_hash
            if banner_screenshot_path and finding["pattern_type"] in _COOKIE_BANNER_PATTERN_TYPES:
                finding["evidence_data"]["banner_screenshot_path"] = banner_screenshot_path
                finding["evidence_data"]["banner_screenshot_sha256"] = banner_screenshot_hash
            quote = finding["evidence_data"].get("quote")
            if quote:
                annotated_path, annotated_hash = await _save_annotated_screenshot(
                    crawl_result, quote, crawl_result["screenshot"],
                    os.path.join(evidence_dir, f"scan_{scan_id}_finding_{i}_annotated.png"),
                )
                if annotated_path:
                    finding["evidence_data"]["screenshot_annotated_path"] = annotated_path
                    finding["evidence_data"]["screenshot_annotated_sha256"] = annotated_hash
            norm = finding["target_norm"]
            if norm not in citation_cache:
                citation_cache[norm] = await fetch_citation(norm, LEGAL_TEXT_MCP_BASE_URL, client=client)
            finding["evidence_data"]["citation"] = citation_cache[norm]
            insert_finding(conn, scan_id, finding)

    mark_scan_status(conn, scan_id, "done")
    return scan_id


async def _analyze_page(
    page_id: int,
    page_data: dict,
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    citation_cache: dict,
    screenshot_path: str,
    har_path: str,
    har_hash: str,
    banner_screenshot_path: str,
    evidence_dir: str,
    llm_client=None,
) -> tuple[int, list[dict]]:
    async with sem:
        screenshot_hash = await asyncio.to_thread(
            save_evidence, page_data["screenshot"], screenshot_path
        )
        _fire_and_forget(asyncio.to_thread(rfc3161_timestamp, page_data["screenshot"]))

        saved_banner_path, banner_hash = await _save_banner_screenshot(page_data, banner_screenshot_path)

        findings = await run_analysis(
            page_data["dom_after"], page_data["button_styles"], llm_client=llm_client
        )

        findings.extend(_crawl_time_findings(page_data))

        for i, finding in enumerate(findings):
            finding["evidence_data"]["screenshot_path"] = screenshot_path
            finding["evidence_data"]["screenshot_sha256"] = screenshot_hash
            finding["evidence_data"]["har_path"] = har_path
            finding["evidence_data"]["har_sha256"] = har_hash
            if saved_banner_path and finding["pattern_type"] in _COOKIE_BANNER_PATTERN_TYPES:
                finding["evidence_data"]["banner_screenshot_path"] = saved_banner_path
                finding["evidence_data"]["banner_screenshot_sha256"] = banner_hash
            quote = finding["evidence_data"].get("quote")
            if quote:
                annotated_path, annotated_hash = await _save_annotated_screenshot(
                    page_data, quote, page_data["screenshot"],
                    os.path.join(evidence_dir, f"scan_page_{page_id}_finding_{i}_annotated.png"),
                )
                if annotated_path:
                    finding["evidence_data"]["screenshot_annotated_path"] = annotated_path
                    finding["evidence_data"]["screenshot_annotated_sha256"] = annotated_hash
            norm = finding["target_norm"]
            # ponytail: citation_cache dict has a benign race under
            # concurrency (two tasks both miss the cache and double-fetch
            # the same norm) — not a correctness issue since fetch_citation
            # is idempotent, so no lock. Add one only if that stops holding.
            if norm not in citation_cache:
                citation_cache[norm] = await fetch_citation(norm, LEGAL_TEXT_MCP_BASE_URL, client=client)
            finding["evidence_data"]["citation"] = citation_cache[norm]

        return page_id, findings


async def run_site_scan(
    start_url: str,
    conn,
    evidence_dir: str,
    browser,
    max_pages: int | None = None,
    llm_client=None,
    url_validator=None,
    scan_id: int | None = None,
) -> int:
    if max_pages is None:
        max_pages = int(os.environ.get("MAX_PAGES_PER_SCAN", "15"))

    # scan_id is passed in when the caller (app.main's POST /scans) already
    # created the row up front to redirect immediately and run the actual
    # crawl in the background — insert_scan here only covers direct callers
    # (tests, run_site_scan used standalone) that haven't done that.
    if scan_id is None:
        scan_id = insert_scan(conn, start_url)

    # url_validator is only forwarded when the caller overrides it (tests
    # exercising file:// fixtures, same pattern as crawl_site's own default
    # param) — production always relies on crawl_site's own default
    # (validate_scan_url).
    crawl_kwargs = {"max_pages": max_pages, "har_dir": evidence_dir, "llm_client": llm_client}
    if url_validator is not None:
        crawl_kwargs["url_validator"] = url_validator

    site_result = await crawl_site(start_url, browser, **crawl_kwargs)

    har_hash = await asyncio.to_thread(_read_and_hash, site_result["har_path"])

    # insert_page first, sequentially — sqlite3.Connection isn't safe for
    # concurrent use, so every DB write stays on this one coroutine. Only
    # the independent per-page analysis work (below) runs concurrently.
    page_ids = [
        insert_page(conn, scan_id, page_data["url"], page_data["category"])
        for page_data in site_result["pages"]
    ]

    citation_cache: dict[str, str | None] = {}
    sem = asyncio.Semaphore(_ANALYSIS_CONCURRENCY)
    async with httpx.AsyncClient(base_url=LEGAL_TEXT_MCP_BASE_URL, timeout=5.0) as client:
        tasks = [
            _analyze_page(
                page_id,
                page_data,
                sem,
                client,
                citation_cache,
                os.path.join(evidence_dir, f"scan_{scan_id}_page_{page_id}_screenshot.png"),
                site_result["har_path"],
                har_hash,
                os.path.join(evidence_dir, f"scan_{scan_id}_page_{page_id}_banner_screenshot.png"),
                evidence_dir,
                llm_client=llm_client,
            )
            for page_id, page_data in zip(page_ids, site_result["pages"])
        ]
        # as_completed instead of gather: write each page's findings to the
        # DB as soon as its analysis finishes, not all at once at the end —
        # this is what lets a client polling/reloading scan_detail.html see
        # findings show up while the scan is still running.
        for coro in asyncio.as_completed(tasks):
            page_id, findings = await coro
            for finding in findings:
                insert_finding(conn, scan_id, finding, page_id=page_id)

    # Cross-page: needs every page's screenshot already saved to disk
    # (guaranteed once every task above has completed) and isn't tied to a
    # single page the way the per-page findings above are. Best-effort like
    # every other finding source in this file — a bug here must not lose
    # the findings already collected and written above, or leave the scan
    # stuck instead of marked done.
    try:
        price_findings = _checkout_price_increase_findings(
            page_ids, site_result["pages"], evidence_dir, scan_id
        )
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, see above
        logger.warning("run_site_scan: _checkout_price_increase_findings failed: %s", exc)
        price_findings = []
    for finding, later_page_id in price_findings:
        insert_finding(conn, scan_id, finding, page_id=later_page_id)

    mark_scan_status(conn, scan_id, "done")
    return scan_id
