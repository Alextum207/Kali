import os

import httpx

from app.crawler import crawl_page
from app.site_crawler import crawl_site
from app.analysis.pipeline import run_analysis
from app.evidence import save_evidence, sha256_bytes, rfc3161_timestamp
from app.compliance import fetch_citation, map_to_norm
from app.db import insert_scan, insert_finding, insert_page

LEGAL_TEXT_MCP_BASE_URL = os.environ.get("LEGAL_TEXT_MCP_BASE_URL", "http://localhost:8091")


async def run_scan(url: str, conn, evidence_dir: str, browser=None) -> int:
    scan_id = insert_scan(conn, url)

    crawl_result = await crawl_page(url, browser, har_dir=evidence_dir)

    screenshot_path = os.path.join(evidence_dir, f"scan_{scan_id}_screenshot.png")
    screenshot_hash = save_evidence(crawl_result["screenshot"], screenshot_path)
    rfc3161_timestamp(crawl_result["screenshot"])  # best-effort, stored hash is the primary proof

    with open(crawl_result["har_path"], "rb") as f:
        har_hash = sha256_bytes(f.read())

    findings = await run_analysis(crawl_result["dom_after"], crawl_result["button_styles"])

    async with httpx.AsyncClient(base_url=LEGAL_TEXT_MCP_BASE_URL, timeout=5.0) as client:
        for finding in findings:
            finding["evidence_data"]["screenshot_path"] = screenshot_path
            finding["evidence_data"]["screenshot_sha256"] = screenshot_hash
            finding["evidence_data"]["har_path"] = crawl_result["har_path"]
            finding["evidence_data"]["har_sha256"] = har_hash
            finding["evidence_data"]["citation"] = await fetch_citation(
                finding["target_norm"], LEGAL_TEXT_MCP_BASE_URL, client=client
            )
            insert_finding(conn, scan_id, finding)

    return scan_id


async def run_site_scan(
    start_url: str,
    conn,
    evidence_dir: str,
    browser,
    max_pages: int | None = None,
    llm_client=None,
) -> int:
    if max_pages is None:
        max_pages = int(os.environ.get("MAX_PAGES_PER_SCAN", "15"))

    scan_id = insert_scan(conn, start_url)

    site_result = await crawl_site(
        start_url, browser, max_pages=max_pages, har_dir=evidence_dir, llm_client=llm_client
    )

    with open(site_result["har_path"], "rb") as f:
        har_hash = sha256_bytes(f.read())

    async with httpx.AsyncClient(base_url=LEGAL_TEXT_MCP_BASE_URL, timeout=5.0) as client:
        for page_data in site_result["pages"]:
            page_id = insert_page(conn, scan_id, page_data["url"], page_data["category"])

            screenshot_path = os.path.join(
                evidence_dir, f"scan_{scan_id}_page_{page_id}_screenshot.png"
            )
            screenshot_hash = save_evidence(page_data["screenshot"], screenshot_path)
            rfc3161_timestamp(page_data["screenshot"])  # best-effort, stored hash is the primary proof

            findings = await run_analysis(page_data["dom_after"], page_data["button_styles"], llm_client=llm_client)

            for contrast_finding in page_data.get("contrast_findings", []):
                contrast_finding["target_norm"] = map_to_norm(contrast_finding["pattern_type"])
                findings.append(contrast_finding)

            if page_data.get("infinite_scroll_detected"):
                findings.append({
                    "pattern_type": "Exploiting Addiction (Infinite Scroll)",
                    "target_norm": map_to_norm("Exploiting Addiction (Infinite Scroll)"),
                    "confidence_score": 0.6,
                    "evidence_data": {"note": "document height grew across 3 scroll iterations without an end indicator"},
                })

            for finding in findings:
                finding["evidence_data"]["screenshot_path"] = screenshot_path
                finding["evidence_data"]["screenshot_sha256"] = screenshot_hash
                finding["evidence_data"]["har_path"] = site_result["har_path"]
                finding["evidence_data"]["har_sha256"] = har_hash
                finding["evidence_data"]["citation"] = await fetch_citation(
                    finding["target_norm"], LEGAL_TEXT_MCP_BASE_URL, client=client
                )
                insert_finding(conn, scan_id, finding, page_id=page_id)

    return scan_id
