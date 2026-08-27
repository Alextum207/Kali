import csv
import pathlib

import pytest

from scripts.eval_live_urls import (
    BLOCKED_STATUSES,
    BenchmarkUrl,
    _finding_summary,
    load_benchmark_urls,
    parse_args,
    run_benchmark,
    select_entries,
    summarize_results,
)
import scripts.eval_live_urls as eval_live_urls


ROOT = pathlib.Path(__file__).parent.parent
BENCHMARK_CSV = ROOT / "data" / "live_benchmark_urls.csv"
ROUND2_BENCHMARK_CSV = ROOT / "data" / "live_benchmark_urls_round2.csv"
FIXTURE_ROOT = pathlib.Path(__file__).parent / "fixtures" / "accuracy_matrix"


def test_live_benchmark_url_list_has_expected_shape():
    entries = load_benchmark_urls(BENCHMARK_CSV)

    assert len(entries) == 100
    assert sum(1 for entry in entries if entry.label == "suspected") == 50
    assert sum(1 for entry in entries if entry.label == "control") == 50
    assert len({entry.url for entry in entries}) == 100
    assert all(entry.source for entry in entries)


def test_round2_live_benchmark_url_list_has_expected_shape_and_no_round1_overlap():
    round1 = load_benchmark_urls(BENCHMARK_CSV)
    round2 = load_benchmark_urls(ROUND2_BENCHMARK_CSV)

    assert len(round2) == 100
    assert sum(1 for entry in round2 if entry.label == "suspected") == 50
    assert sum(1 for entry in round2 if entry.label == "control") == 50
    assert len({entry.url for entry in round2}) == 100
    assert {entry.url for entry in round1}.isdisjoint({entry.url for entry in round2})


def test_live_benchmark_loader_rejects_bad_labels(tmp_path):
    path = tmp_path / "urls.csv"
    path.write_text(
        "url,label,source,expected_signal,notes\n"
        "https://example.com,maybe,manual,none,bad\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid label"):
        load_benchmark_urls(path)


def test_live_benchmark_selection_can_filter_and_limit():
    entries = [
        BenchmarkUrl("https://a.test", "suspected", "manual", "none", ""),
        BenchmarkUrl("https://b.test", "control", "manual", "none", ""),
        BenchmarkUrl("https://c.test", "control", "manual", "none", ""),
    ]

    selected = select_entries(entries, label="control", limit=1)

    assert [entry.url for entry in selected] == ["https://b.test"]


def test_live_benchmark_summary_excludes_blocked_from_proxy_rates():
    records = [
        {"label": "suspected", "status": "ok", "findings_count": 2, "pattern_counts": {"Fake Urgency": 2}},
        {"label": "suspected", "status": "captcha", "findings_count": 0, "pattern_counts": {}},
        {"label": "control", "status": "ok", "findings_count": 1, "pattern_counts": {"Fake Scarcity": 1}},
        {"label": "control", "status": "robots_disallowed", "findings_count": 0, "pattern_counts": {}},
    ]

    summary = summarize_results(records)

    assert summary["suspected_detection_rate_any_ok_only"] == 1.0
    assert summary["control_false_positive_rate_any_ok_only"] == 1.0
    assert summary["by_label"]["suspected"]["blocked_or_excluded"] == 1
    assert summary["by_label"]["control"]["blocked_or_excluded"] == 1
    assert {"robots_disallowed", "captcha", "timeout"} == BLOCKED_STATUSES


def test_live_benchmark_finding_summary_keeps_reviewable_evidence_details():
    summary = _finding_summary(
        {
            "pattern_type": "Visuelle Tarnung (Kontrast)",
            "confidence_score": 0.6,
            "page_id": 7,
            "evidence_data": {
                "selector": "p.legal",
                "excerpt": "Gesamtpreis zzgl. Versandkosten",
                "contrast_ratio": 1.2,
                "screenshot_path": "/tmp/screenshot.png",
                "screenshot_sha256": "abc",
                "citation": "long legal text",
            },
        },
        {7: "https://shop.test/checkout"},
    )

    assert summary["page_url"] == "https://shop.test/checkout"
    assert summary["evidence"]["selector"] == "p.legal"
    assert summary["evidence"]["excerpt"] == "Gesamtpreis zzgl. Versandkosten"
    assert summary["evidence"]["contrast_ratio"] == 1.2
    assert "screenshot_sha256" not in summary["evidence"]
    assert "citation" not in summary["evidence"]


@pytest.mark.asyncio
async def test_live_benchmark_runner_scans_local_fixtures(tmp_path):
    product_positive = (FIXTURE_ROOT / "product_positive" / "index.html").as_uri()
    docs_examples = (FIXTURE_ROOT / "docs_examples" / "index.html").as_uri()
    input_path = tmp_path / "urls.csv"
    with input_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["url", "label", "source", "expected_signal", "notes"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "url": product_positive,
                "label": "suspected",
                "source": "local_fixture",
                "expected_signal": "scarcity",
                "notes": "positive fixture",
            }
        )
        writer.writerow(
            {
                "url": docs_examples,
                "label": "control",
                "source": "local_fixture",
                "expected_signal": "none",
                "notes": "negative fixture",
            }
        )

    output_path = tmp_path / "benchmark.jsonl"
    args = parse_args(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--max-pages",
            "1",
            "--time-budget",
            "10",
            "--delay",
            "0",
        ]
    )

    summary = await run_benchmark(args)

    assert output_path.exists()
    assert output_path.with_suffix(".jsonl.summary.json").exists()
    assert summary["total_records"] == 2
    assert summary["by_label"]["suspected"]["ok"] == 1
    assert summary["by_label"]["control"]["ok"] == 1


@pytest.mark.asyncio
async def test_live_benchmark_marks_zero_page_scans_as_errors(tmp_path, monkeypatch):
    from app.db import insert_scan

    async def fake_run_site_scan(start_url, conn, evidence_dir, browser, **kwargs):
        return insert_scan(conn, start_url)

    monkeypatch.setattr(eval_live_urls, "run_site_scan", fake_run_site_scan)
    record = await eval_live_urls.scan_entry(
        BenchmarkUrl(
            "file:///tmp/no-pages.html",
            "control",
            "local_fixture",
            "none",
            "zero page regression",
        ),
        index=1,
        browser=object(),
        evidence_root=tmp_path,
        max_pages=1,
        llm_client=eval_live_urls.NoFindingLLMClient(),
    )

    assert record["status"] == "scan_error"
    assert record["error_type"] == "NoPagesCrawled"
    assert record["pages_crawled"] == 0
    assert record["duration_seconds"] >= 0
