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


# Direct template rendering tests (independent of WeasyPrint PDF generation)
# These verify the actual citation rendering logic in the Jinja2 template.

def test_template_renders_citation_when_present():
    """Test that citation text appears in rendered HTML when provided."""
    from jinja2 import Environment, FileSystemLoader
    templates_dir = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("report.html")

    findings = [
        {"pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA", "confidence_score": 0.8,
         "evidence_data": {
             "quote": "No thanks, I hate saving money",
             "citation": "Art. 25 DSA: Verbot manipulativer Online-Schnittstellen"
         }},
    ]
    html = template.render(url="https://example.com", findings=findings)

    # Verify citation text is in the HTML
    assert "Art. 25 DSA: Verbot manipulativer Online-Schnittstellen" in html
    # Verify it's wrapped in the citation span
    assert '<span class="citation">Art. 25 DSA: Verbot manipulativer Online-Schnittstellen</span>' in html


def test_template_does_not_render_none_as_text():
    """Test that citation: None does not render the literal string 'None' in HTML."""
    from jinja2 import Environment, FileSystemLoader
    templates_dir = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("report.html")

    findings = [
        {"pattern_type": "Fake Urgency", "target_norm": "UWG §§ 5, 5a", "confidence_score": 0.9,
         "evidence_data": {
             "quote": "Only 2 left!",
             "citation": None
         }},
    ]
    html = template.render(url="https://example.com", findings=findings)

    # Verify "None" does not appear in HTML (would indicate broken template)
    assert '<span class="citation">None</span>' not in html
    assert ">None<" not in html
    # Verify the evidence quote is still there
    assert "Only 2 left!" in html


def test_template_handles_missing_citation_key():
    """Test that rendering works when citation key is entirely absent from evidence_data."""
    from jinja2 import Environment, FileSystemLoader
    templates_dir = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("report.html")

    findings = [
        {"pattern_type": "Pre-ticked Box", "target_norm": "Art. 7 Abs. 4 DSGVO", "confidence_score": 0.75,
         "evidence_data": {
             "selector": "input[type='checkbox'][checked]"
             # no "citation" key at all
         }},
    ]
    html = template.render(url="https://example.com", findings=findings)

    # Verify no citation span appears
    assert '<span class="citation">' not in html
    # Verify the evidence selector is still there
    assert "input[type='checkbox'][checked]" in html
