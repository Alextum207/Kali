import asyncio
import os

import httpx

from app.crawler import crawl_page
from app.site_crawler import crawl_site
from app.analysis.pipeline import run_analysis, IMPACT_MAP
from app.evidence import save_evidence, sha256_bytes, rfc3161_timestamp
from app.compliance import fetch_citation, map_to_norm
from app.db import insert_scan, insert_finding, insert_page

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


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _read_and_hash(path: str) -> str:
    with open(path, "rb") as f:
        return sha256_bytes(f.read())


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

    findings = await run_analysis(crawl_result["dom_after"], crawl_result["button_styles"])

    citation_cache: dict[str, str | None] = {}
    async with httpx.AsyncClient(base_url=LEGAL_TEXT_MCP_BASE_URL, timeout=5.0) as client:
        for finding in findings:
            finding["evidence_data"]["screenshot_path"] = screenshot_path
            finding["evidence_data"]["screenshot_sha256"] = screenshot_hash
            finding["evidence_data"]["har_path"] = crawl_result["har_path"]
            finding["evidence_data"]["har_sha256"] = har_hash
            norm = finding["target_norm"]
            if norm not in citation_cache:
                citation_cache[norm] = await fetch_citation(norm, LEGAL_TEXT_MCP_BASE_URL, client=client)
            finding["evidence_data"]["citation"] = citation_cache[norm]
            insert_finding(conn, scan_id, finding)

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
    llm_client=None,
) -> tuple[int, list[dict]]:
    async with sem:
        screenshot_hash = await asyncio.to_thread(
            save_evidence, page_data["screenshot"], screenshot_path
        )
        _fire_and_forget(asyncio.to_thread(rfc3161_timestamp, page_data["screenshot"]))

        findings = await run_analysis(
            page_data["dom_after"], page_data["button_styles"], llm_client=llm_client
        )

        for contrast_finding in page_data.get("contrast_findings", []):
            contrast_finding["target_norm"] = map_to_norm(contrast_finding["pattern_type"])
            contrast_finding["evidence_data"]["impact"] = IMPACT_MAP.get(contrast_finding["pattern_type"], "–")
            findings.append(contrast_finding)

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

        for finding in findings:
            finding["evidence_data"]["screenshot_path"] = screenshot_path
            finding["evidence_data"]["screenshot_sha256"] = screenshot_hash
            finding["evidence_data"]["har_path"] = har_path
            finding["evidence_data"]["har_sha256"] = har_hash
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
    cookies: list[dict] | None = None,
) -> int:
    if max_pages is None:
        max_pages = int(os.environ.get("MAX_PAGES_PER_SCAN", "15"))

    scan_id = insert_scan(conn, start_url)

    # url_validator is only forwarded when the caller overrides it (tests
    # exercising file:// fixtures, same pattern as crawl_site's own default
    # param) — production always relies on crawl_site's own default
    # (validate_scan_url). cookies (Chrome-extension handoff) is likewise
    # only forwarded when given, in chrome.cookies.getAll() shape.
    crawl_kwargs = {"max_pages": max_pages, "har_dir": evidence_dir, "llm_client": llm_client}
    if url_validator is not None:
        crawl_kwargs["url_validator"] = url_validator
    if cookies is not None:
        crawl_kwargs["cookies"] = cookies

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
        results = await asyncio.gather(*[
            _analyze_page(
                page_id,
                page_data,
                sem,
                client,
                citation_cache,
                os.path.join(evidence_dir, f"scan_{scan_id}_page_{page_id}_screenshot.png"),
                site_result["har_path"],
                har_hash,
                llm_client=llm_client,
            )
            for page_id, page_data in zip(page_ids, site_result["pages"])
        ])

    for page_id, findings in results:
        for finding in findings:
            insert_finding(conn, scan_id, finding, page_id=page_id)

    return scan_id
