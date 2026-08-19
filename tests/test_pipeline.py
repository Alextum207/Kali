from app.analysis.pipeline import run_analysis

DOM_HTML = """
<html><body>
<form><input type="checkbox" id="newsletter" checked></form>
<main><p>No thanks, I enjoy paying full price for everything.</p></main>
</body></html>
"""


def _fake_classify_text(text, client=None):
    return [
        {
            "pattern_type": "Confirm Shaming",
            "confidence_score": 0.8,
            "evidence_data": {"quote": "No thanks, I enjoy paying full price for everything."},
        }
    ]


def test_run_analysis_combines_all_stages_with_norms(monkeypatch):
    monkeypatch.setattr("app.analysis.pipeline.classify_text", _fake_classify_text)

    button_styles = {
        "accept": {"width": 200, "height": 60, "bg_color": (0, 128, 0), "text_color": (255, 255, 255)},
        "reject": {"width": 60, "height": 20, "bg_color": (230, 230, 230), "text_color": (240, 240, 240)},
    }

    findings = run_analysis(DOM_HTML, button_styles)

    pattern_types = {f["pattern_type"] for f in findings}
    assert pattern_types == {"Pre-ticked Box", "Confirm Shaming", "Visuelle Asymmetrie (Button)"}
    for f in findings:
        assert f["target_norm"] != "Unbekannt"


def test_run_analysis_without_button_styles_skips_visual_stage(monkeypatch):
    monkeypatch.setattr("app.analysis.pipeline.classify_text", _fake_classify_text)
    findings = run_analysis(DOM_HTML, None)
    pattern_types = {f["pattern_type"] for f in findings}
    assert "Visuelle Asymmetrie (Button)" not in pattern_types
