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
    from app.compliance import EVIDENCE_HINTS
    html = template.render(url="https://example.com", findings=findings, evidence_hints=EVIDENCE_HINTS)

    # Verify "None" does not appear in HTML (would indicate broken template)
    assert '<span class="citation">None</span>' not in html
    assert ">None<" not in html
    # Verify the evidence quote is still there
    assert "Only 2 left!" in html
    # Verify the evidence-gathering hint for this pattern_type is rendered
    assert EVIDENCE_HINTS["Fake Urgency"] in html


def test_template_renders_impact_link_time_screenshot_columns():
    """Test that the new Auswirkung/Link/Zeit/Screenshot columns render,
    with a defensive fallback when a field is missing."""
    from jinja2 import Environment, FileSystemLoader
    templates_dir = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("report.html")

    findings = [
        {"pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA", "confidence_score": 0.8,
         "created_at": "2026-08-20 10:00:00", "page_url": "https://example.com/checkout",
         "screenshot_url": "/evidence/scan_1_screenshot.png",
         "evidence_data": {"quote": "No thanks", "impact": "Verbraucher wird emotional zur Zustimmung gedrängt"}},
        {"pattern_type": "Pre-ticked Box", "target_norm": "Art. 7 Abs. 4 DSGVO", "confidence_score": 0.75,
         "evidence_data": {"selector": "input[type='checkbox']"}},  # no impact/page_url/screenshot_url/created_at
    ]
    html = template.render(url="https://example.com", findings=findings)

    assert "Verbraucher wird emotional zur Zustimmung gedrängt" in html
    assert "https://example.com/checkout" in html
    assert "2026-08-20 10:00:00" in html
    assert "/evidence/scan_1_screenshot.png" in html
    # Second finding is missing impact/page_url/screenshot_url entirely -
    # must not crash and must fall back to "–" for impact.
    assert "–" in html


def test_generate_pdf_report_embeds_screenshot_as_data_uri(tmp_path, monkeypatch):
    """generate_pdf_report must read evidence_data.screenshot_path off disk
    and pass an embedded base64 image to the template, instead of just the
    screenshot_url text — verified via the same captured-render-kwargs
    trick as the risk/by_norm test below, since the real PDF is binary."""
    import base64

    screenshot_path = tmp_path / "scan_1_screenshot.png"
    screenshot_path.write_bytes(b"\x89PNG-fake-bytes")

    captured = {}

    class _CapturingTemplate:
        def render(self, **kwargs):
            captured.update(kwargs)
            return "<html></html>"

    import app.reports as reports_module
    monkeypatch.setattr(reports_module._env, "get_template", lambda name: _CapturingTemplate())

    findings = [
        {"pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA", "confidence_score": 0.9,
         "evidence_data": {"screenshot_path": str(screenshot_path)}},
    ]
    out_path = str(tmp_path / "report.pdf")
    reports_module.generate_pdf_report("https://example.com", findings, out_path)

    data_uri = captured["findings"][0]["evidence_data"]["screenshot_data_uri"]
    assert data_uri == "data:image/png;base64," + base64.b64encode(b"\x89PNG-fake-bytes").decode("ascii")
    # Original findings list/dict passed by the caller must stay untouched
    # (it's also used to render scan_detail.html) — _embed_screenshot must
    # copy, not mutate.
    assert "screenshot_data_uri" not in findings[0]["evidence_data"]


def test_generate_pdf_report_skips_missing_screenshot_file_gracefully(tmp_path, monkeypatch):
    """A screenshot_path pointing at a file that no longer exists on disk
    must not crash report generation — best-effort, evidence data is more
    important than one missing image."""
    captured = {}

    class _CapturingTemplate:
        def render(self, **kwargs):
            captured.update(kwargs)
            return "<html></html>"

    import app.reports as reports_module
    monkeypatch.setattr(reports_module._env, "get_template", lambda name: _CapturingTemplate())

    findings = [
        {"pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA", "confidence_score": 0.9,
         "evidence_data": {"screenshot_path": str(tmp_path / "does_not_exist.png")}},
    ]
    out_path = str(tmp_path / "report.pdf")
    reports_module.generate_pdf_report("https://example.com", findings, out_path)

    assert "screenshot_data_uri" not in captured["findings"][0]["evidence_data"]


def test_generate_pdf_report_computes_risk_and_norm_summary(tmp_path, monkeypatch):
    """generate_pdf_report must pass risk + by_norm into the template
    context — verified by capturing the render() call args instead of
    parsing the binary PDF."""
    captured = {}

    class _CapturingTemplate:
        def render(self, **kwargs):
            captured.update(kwargs)
            return "<html></html>"

    import app.reports as reports_module
    monkeypatch.setattr(reports_module._env, "get_template", lambda name: _CapturingTemplate())

    findings = [
        {"pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA", "confidence_score": 0.9,
         "evidence_data": {}},
        {"pattern_type": "Fake Urgency", "target_norm": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
         "confidence_score": 0.9, "evidence_data": {}},
    ]
    out_path = str(tmp_path / "report.pdf")
    reports_module.generate_pdf_report("https://example.com", findings, out_path)

    assert captured["risk"]["level"] == "hoch"
    assert captured["by_norm"] == {"Art. 25 DSA": 1, "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3": 1}


def test_report_template_renders_cover_and_norm_summary_when_risk_given():
    from jinja2 import Environment, FileSystemLoader

    templates_dir = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("report.html")

    findings = [
        {"pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA", "confidence_score": 0.9,
         "evidence_data": {}},
    ]
    html = template.render(
        url="https://example.com",
        findings=findings,
        risk={"score": 0.9, "level": "hoch", "by_category": {"Confirm Shaming": 1}},
        by_norm={"Art. 25 DSA": 1},
    )

    assert "badge-hoch" in html
    assert "Art. 25 DSA" in html


def test_report_template_renders_without_risk_context():
    """Direct template.render() calls without risk/by_norm (as used
    elsewhere in this file) must not crash and must not render a cover
    section."""
    from jinja2 import Environment, FileSystemLoader

    templates_dir = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("report.html")

    html = template.render(url="https://example.com", findings=[])

    assert "badge-" not in html


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
