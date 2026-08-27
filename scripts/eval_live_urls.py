"""Run Kali's crawler against a curated live URL benchmark.

The benchmark is a proxy accuracy check: suspected URLs are dark-pattern-prone
start points, not ground-truth legal findings. robots/captcha/timeouts are
reported as blocked and excluded from the suspected/control proxy rates.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.crawler import CaptchaRequiredError  # noqa: E402
from app.db import get_findings, get_pages, init_db  # noqa: E402
from app.robots import RobotsDisallowedError  # noqa: E402
from app.scan import run_site_scan  # noqa: E402
from app.url_safety import validate_scan_url  # noqa: E402


VALID_LABELS = {"suspected", "control"}
BLOCKED_STATUSES = {"robots_disallowed", "captcha", "timeout"}
REQUIRED_COLUMNS = {"url", "label", "source", "expected_signal", "notes"}


@dataclass(frozen=True)
class BenchmarkUrl:
    url: str
    label: str
    source: str
    expected_signal: str
    notes: str


class _FakeBlock:
    def __init__(self, text: str):
        self.text = text
        self.type = "text"


class _FakeToolUseBlock:
    def __init__(self, name: str, input_: dict):
        self.type = "tool_use"
        self.name = name
        self.input = input_


class _FakeMessage:
    def __init__(self, content):
        self.content = [_FakeBlock(content)] if isinstance(content, str) else content


class NoFindingLLMClient:
    """Deterministic stand-in: no text findings and no LLM-driven clicks."""

    class _Messages:
        async def create(self, **kwargs):
            prompt_text = str(kwargs.get("messages", [{}])[0].get("content", ""))
            if "AUSSCHLIESSLICH mit einem JSON-Objekt" in prompt_text:
                return _FakeMessage('{"type": "none"}')
            tools = kwargs.get("tools") or []
            if tools and tools[0].get("name") == "report_findings":
                return _FakeMessage([_FakeToolUseBlock("report_findings", {"findings": []})])
            return _FakeMessage("[]")

    messages = _Messages()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_benchmark_urls(path: str | Path) -> list[BenchmarkUrl]:
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"{path} is missing columns: {', '.join(sorted(missing))}")

        entries: list[BenchmarkUrl] = []
        seen: set[str] = set()
        for line_no, row in enumerate(reader, start=2):
            url = (row.get("url") or "").strip()
            label = (row.get("label") or "").strip()
            source = (row.get("source") or "").strip()
            expected_signal = (row.get("expected_signal") or "").strip()
            notes = (row.get("notes") or "").strip()

            if not url:
                raise ValueError(f"{path}:{line_no} has an empty url")
            if url in seen:
                raise ValueError(f"{path}:{line_no} duplicates url {url!r}")
            seen.add(url)

            if label not in VALID_LABELS:
                raise ValueError(f"{path}:{line_no} has invalid label {label!r}")

            scheme = urlparse(url).scheme
            if scheme not in {"http", "https", "file"}:
                raise ValueError(f"{path}:{line_no} has unsupported URL scheme {scheme!r}")

            entries.append(
                BenchmarkUrl(
                    url=url,
                    label=label,
                    source=source,
                    expected_signal=expected_signal,
                    notes=notes,
                )
            )

    return entries


def select_entries(entries: list[BenchmarkUrl], *, label: str | None, limit: int | None) -> list[BenchmarkUrl]:
    if label:
        entries = [entry for entry in entries if entry.label == label]
    if limit is not None:
        entries = entries[:limit]
    return entries


def _safe_slug(index: int, url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or "file"
    path = (parsed.path or "root").strip("/") or "root"
    raw = f"{index:03d}-{host}-{path}"
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in raw.lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned[:90].strip("-")


def _pattern_counts(findings: list[dict]) -> dict[str, int]:
    return dict(sorted(Counter(f["pattern_type"] for f in findings).items()))


def _compact_evidence(evidence: dict) -> dict:
    compact = {}
    for key, value in evidence.items():
        if key.endswith("_sha256") or key == "citation":
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value
    return compact


def _finding_summary(finding: dict, page_url_by_id: dict[int, str]) -> dict:
    evidence = finding.get("evidence_data", {})
    return {
        "pattern_type": finding["pattern_type"],
        "confidence_score": finding["confidence_score"],
        "page_url": page_url_by_id.get(finding.get("page_id")),
        "quote": evidence.get("quote"),
        "screenshot_path": evidence.get("screenshot_path"),
        "evidence": _compact_evidence(evidence),
    }


def _base_record(entry: BenchmarkUrl, index: int) -> dict:
    return {
        "index": index,
        "url": entry.url,
        "label": entry.label,
        "source": entry.source,
        "expected_signal": entry.expected_signal,
        "notes": entry.notes,
        "started_at": _utc_now(),
    }


async def scan_entry(
    entry: BenchmarkUrl,
    *,
    index: int,
    browser,
    evidence_root: Path,
    max_pages: int,
    llm_client,
) -> dict:
    started = time.perf_counter()
    record = _base_record(entry, index)
    scan_dir = evidence_root / _safe_slug(index, entry.url)
    scan_dir.mkdir(parents=True, exist_ok=True)
    conn = init_db(str(scan_dir / "scan.db"))

    try:
        if urlparse(entry.url).scheme != "file":
            validate_scan_url(entry.url)
            url_validator = None
        else:
            url_validator = lambda url: None

        scan_id = await run_site_scan(
            entry.url,
            conn,
            str(scan_dir),
            browser,
            max_pages=max_pages,
            llm_client=llm_client,
            url_validator=url_validator,
        )
        pages = get_pages(conn, scan_id)
        findings = get_findings(conn, scan_id)
        if not pages:
            record.update(
                {
                    "status": "scan_error",
                    "blocked": False,
                    "error_type": "NoPagesCrawled",
                    "error_message": "scan completed without any crawled pages",
                    "scan_id": scan_id,
                    "evidence_dir": str(scan_dir),
                    "pages_crawled": 0,
                    "findings_count": 0,
                    "pattern_counts": {},
                    "findings": [],
                }
            )
        else:
            page_url_by_id = {page["id"]: page["url"] for page in pages}
            record.update(
                {
                    "status": "ok",
                    "blocked": False,
                    "scan_id": scan_id,
                    "evidence_dir": str(scan_dir),
                    "pages_crawled": len(pages),
                    "findings_count": len(findings),
                    "pattern_counts": _pattern_counts(findings),
                    "findings": [_finding_summary(finding, page_url_by_id) for finding in findings],
                }
            )
    except RobotsDisallowedError as exc:
        record.update(_error_fields("robots_disallowed", exc))
    except CaptchaRequiredError as exc:
        record.update(_error_fields("captcha", exc))
    except (asyncio.TimeoutError, PlaywrightTimeoutError) as exc:
        record.update(_error_fields("timeout", exc))
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.NetworkError) as exc:
        record.update(_error_fields("network_error", exc))
    except Exception as exc:  # noqa: BLE001 - benchmark keeps going per URL
        record.update(_error_fields("scan_error", exc))
    finally:
        conn.close()

    record["duration_seconds"] = round(time.perf_counter() - started, 3)
    record["finished_at"] = _utc_now()
    return record


def _error_fields(status: str, exc: Exception) -> dict:
    return {
        "status": status,
        "blocked": status in BLOCKED_STATUSES,
        "error_type": exc.__class__.__name__,
        "error_message": str(exc),
        "pages_crawled": 0,
        "findings_count": 0,
        "pattern_counts": {},
        "findings": [],
    }


def load_existing_records(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def append_jsonl(path: str | Path, record: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def summarize_results(records: list[dict]) -> dict:
    by_label = {}
    for label in sorted(VALID_LABELS):
        label_records = [record for record in records if record.get("label") == label]
        ok_records = [record for record in label_records if record.get("status") == "ok"]
        blocked_records = [record for record in label_records if record.get("status") in BLOCKED_STATUSES]
        with_findings = [record for record in ok_records if record.get("findings_count", 0) > 0]
        by_label[label] = {
            "total": len(label_records),
            "ok": len(ok_records),
            "blocked_or_excluded": len(blocked_records),
            "errors": len(label_records) - len(ok_records) - len(blocked_records),
            "with_any_finding": len(with_findings),
            "any_finding_rate_ok_only": _rate(len(with_findings), len(ok_records)),
            "pattern_counts_ok_only": _combined_pattern_counts(ok_records),
        }

    return {
        "generated_at": _utc_now(),
        "total_records": len(records),
        "status_counts": dict(sorted(Counter(record.get("status", "unknown") for record in records).items())),
        "suspected_detection_rate_any_ok_only": by_label["suspected"]["any_finding_rate_ok_only"],
        "control_false_positive_rate_any_ok_only": by_label["control"]["any_finding_rate_ok_only"],
        "by_label": by_label,
    }


def _combined_pattern_counts(records: list[dict]) -> dict[str, int]:
    counts = Counter()
    for record in records:
        counts.update(record.get("pattern_counts") or {})
    return dict(sorted(counts.items()))


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def write_summary(output_path: str | Path, summary: dict) -> Path:
    output_path = Path(output_path)
    summary_path = output_path.with_suffix(output_path.suffix + ".summary.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return summary_path


def make_llm_client(with_llm: bool):
    if not with_llm:
        return NoFindingLLMClient()

    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("--with-llm requires ANTHROPIC_API_KEY")
    return anthropic.AsyncAnthropic(api_key=api_key)


async def run_benchmark(args) -> dict:
    entries = select_entries(load_benchmark_urls(args.input), label=args.label, limit=args.limit)
    existing_records = load_existing_records(args.output) if args.resume else []
    completed_urls = {record["url"] for record in existing_records} if args.resume else set()
    todo = [entry for entry in entries if entry.url not in completed_urls]

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    evidence_root = Path(args.evidence_dir)
    evidence_root.mkdir(parents=True, exist_ok=True)
    llm_client = make_llm_client(args.with_llm)

    previous_budget = os.environ.get("SCAN_TIME_BUDGET_SECONDS")
    os.environ["SCAN_TIME_BUDGET_SECONDS"] = str(args.time_budget)

    new_records: list[dict] = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=not args.headed)
            try:
                for offset, entry in enumerate(todo, start=1):
                    index = entries.index(entry) + 1
                    print(f"[{offset}/{len(todo)}] {entry.label}: {entry.url}", flush=True)
                    record = await scan_entry(
                        entry,
                        index=index,
                        browser=browser,
                        evidence_root=evidence_root,
                        max_pages=args.max_pages,
                        llm_client=llm_client,
                    )
                    append_jsonl(args.output, record)
                    new_records.append(record)
                    print(
                        f"  -> {record['status']} pages={record['pages_crawled']} "
                        f"findings={record['findings_count']} in {record['duration_seconds']}s",
                        flush=True,
                    )
                    if args.delay and offset < len(todo):
                        await asyncio.sleep(args.delay)
            finally:
                await browser.close()
    finally:
        if previous_budget is None:
            os.environ.pop("SCAN_TIME_BUDGET_SECONDS", None)
        else:
            os.environ["SCAN_TIME_BUDGET_SECONDS"] = previous_budget

    all_records = existing_records + new_records
    summary = summarize_results(all_records)
    summary_path = write_summary(args.output, summary)
    print(f"Wrote {len(new_records)} new records to {args.output}")
    print(f"Wrote summary to {summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return summary


def parse_args(argv: list[str] | None = None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(root / "data" / "live_benchmark_urls.csv"))
    parser.add_argument("--output", default=str(root / "reports" / "live_benchmark" / "latest.jsonl"))
    parser.add_argument("--evidence-dir", default=str(root / "reports" / "live_benchmark" / "evidence"))
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--time-budget", type=float, default=20)
    parser.add_argument("--delay", type=float, default=2)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--label", choices=sorted(VALID_LABELS))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--with-llm", action="store_true")
    parser.add_argument("--headed", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    args = parse_args(argv)
    asyncio.run(run_benchmark(args))


if __name__ == "__main__":
    main()
