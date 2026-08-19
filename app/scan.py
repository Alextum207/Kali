import os

import httpx

from app.crawler import crawl_page
from app.analysis.pipeline import run_analysis
from app.evidence import save_evidence, sha256_bytes, rfc3161_timestamp
from app.compliance import fetch_citation
from app.db import insert_scan, insert_finding

LEGAL_TEXT_MCP_BASE_URL = os.environ.get("LEGAL_TEXT_MCP_BASE_URL", "http://localhost:8091")


async def run_scan(url: str, conn, evidence_dir: str, browser=None) -> int:
    scan_id = insert_scan(conn, url)

    crawl_result = await crawl_page(url, browser, har_dir=evidence_dir)

    screenshot_path = os.path.join(evidence_dir, f"scan_{scan_id}_screenshot.png")
    screenshot_hash = save_evidence(crawl_result["screenshot"], screenshot_path)
    rfc3161_timestamp(crawl_result["screenshot"])  # best-effort, stored hash is the primary proof

    with open(crawl_result["har_path"], "rb") as f:
        har_hash = sha256_bytes(f.read())

    findings = run_analysis(crawl_result["dom_after"], crawl_result["button_styles"])

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
