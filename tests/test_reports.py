import os
from app.reports import generate_pdf_report


def test_generate_pdf_report_creates_nonempty_file(tmp_path):
    findings = [
        {"pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA", "confidence_score": 0.8,
         "evidence_data": {"quote": "No thanks, I hate saving money"}},
    ]
    out_path = str(tmp_path / "report.pdf")
    result = generate_pdf_report("https://example.com", findings, out_path)
    assert result == out_path
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0


def test_generate_pdf_report_with_citation(tmp_path):
    """Test that citation is rendered when present in evidence_data."""
    findings = [
        {"pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA", "confidence_score": 0.8,
         "evidence_data": {
             "quote": "No thanks, I hate saving money",
             "citation": "Art. 25 DSA: Verbot manipulativer Online-Schnittstellen"
         }},
    ]
    out_path = str(tmp_path / "report_with_citation.pdf")
    result = generate_pdf_report("https://example.com", findings, out_path)
    assert result == out_path
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0


def test_generate_pdf_report_with_missing_citation(tmp_path):
    """Test that rendering works when citation is None."""
    findings = [
        {"pattern_type": "Fake Urgency", "target_norm": "UWG §§ 5, 5a", "confidence_score": 0.9,
         "evidence_data": {
             "quote": "Only 2 left!",
             "citation": None
         }},
    ]
    out_path = str(tmp_path / "report_no_citation.pdf")
    result = generate_pdf_report("https://example.com", findings, out_path)
    assert result == out_path
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0


def test_generate_pdf_report_with_multiple_findings(tmp_path):
    """Test PDF generation with multiple findings, some with citations."""
    findings = [
        {"pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA", "confidence_score": 0.8,
         "evidence_data": {
             "quote": "No thanks, I hate saving money",
             "citation": "Art. 25 DSA: Verbot manipulativer Online-Schnittstellen"
         }},
        {"pattern_type": "Fake Urgency", "target_norm": "UWG §§ 5, 5a", "confidence_score": 0.9,
         "evidence_data": {
             "selector": ".urgency-badge",
             "citation": None
         }},
        {"pattern_type": "Pre-ticked Box", "target_norm": "Art. 7 Abs. 4 DSGVO", "confidence_score": 0.75,
         "evidence_data": {
             "selector": "input[type='checkbox'][checked]"
         }},
    ]
    out_path = str(tmp_path / "report_multi.pdf")
    result = generate_pdf_report("https://example.com", findings, out_path)
    assert result == out_path
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0


def test_generate_pdf_report_creates_directory_if_needed(tmp_path):
    """Test that output directory is created if it doesn't exist."""
    subdir = tmp_path / "reports" / "nested"
    out_path = str(subdir / "report.pdf")
    findings = [
        {"pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA", "confidence_score": 0.8,
         "evidence_data": {"quote": "No thanks"}},
    ]
    result = generate_pdf_report("https://example.com", findings, out_path)
    assert result == out_path
    assert os.path.exists(out_path)
