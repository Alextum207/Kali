import json
import os
from pathlib import Path

import pytest

from app.analysis.pipeline import run_analysis

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "mathur_test_examples.json"

pytestmark = pytest.mark.skipif(
    "ANTHROPIC_API_KEY" not in os.environ,
    reason="Requires a real Claude API key — run manually before the demo.",
)


def test_pipeline_detects_expected_pattern_per_example():
    examples = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    failures = []
    for ex in examples:
        findings = run_analysis(ex["html"], None)
        pattern_types = {f["pattern_type"] for f in findings}
        if ex["expected_pattern_type"] not in pattern_types:
            failures.append((ex["expected_pattern_type"], pattern_types))
    assert not failures, f"Missed expected patterns: {failures}"
