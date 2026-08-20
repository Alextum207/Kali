import pytest
from app.analysis.pipeline import run_analysis

DOM_HTML = """
<html><body>
<form><input type="checkbox" id="newsletter" checked></form>
<main><p>No thanks, I enjoy paying full price for everything.</p></main>
</body></html>
"""

TRICK_QUESTION_DOM = """
<html><body>
<form>
  <input type="checkbox" id="a"><label for="a">Ich möchte Angebote erhalten</label>
  <input type="checkbox" id="b" checked><label for="b">Ich möchte NICHT kontaktiert werden</label>
</form>
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


@pytest.mark.asyncio
async def test_run_analysis_combines_all_stages_with_norms(monkeypatch):
    monkeypatch.setattr("app.analysis.pipeline.classify_text", _fake_classify_text)

    button_styles = {
        "accept": {"width": 200, "height": 60, "bg_color": (0, 128, 0), "text_color": (255, 255, 255)},
        "reject": {"width": 60, "height": 20, "bg_color": (230, 230, 230), "text_color": (240, 240, 240)},
    }

    findings = await run_analysis(DOM_HTML, button_styles)

    pattern_types = {f["pattern_type"] for f in findings}
    assert pattern_types == {"Pre-ticked Box", "Confirm Shaming", "Visuelle Asymmetrie (Button)"}
    for f in findings:
        assert f["target_norm"] != "Unbekannt"
        assert f["evidence_data"]["impact"] != "–"


@pytest.mark.asyncio
async def test_run_analysis_without_button_styles_skips_visual_stage(monkeypatch):
    monkeypatch.setattr("app.analysis.pipeline.classify_text", _fake_classify_text)
    findings = await run_analysis(DOM_HTML, None)
    pattern_types = {f["pattern_type"] for f in findings}
    assert "Visuelle Asymmetrie (Button)" not in pattern_types


@pytest.mark.asyncio
async def test_run_analysis_finds_trick_questions(monkeypatch):
    monkeypatch.setattr("app.analysis.pipeline.classify_text", lambda text, client=None: [])
    findings = await run_analysis(TRICK_QUESTION_DOM, None)
    assert any(f["pattern_type"] == "Trick Questions" for f in findings)


@pytest.mark.asyncio
async def test_run_analysis_boosts_confidence_when_multiple_pattern_types_cooccur(monkeypatch):
    monkeypatch.setattr("app.analysis.pipeline.classify_text", _fake_classify_text)
    baseline = await run_analysis("<html><body><main><p>x</p></main></body></html>", None)
    baseline_confirm_shaming = next(f for f in baseline if f["pattern_type"] == "Confirm Shaming")

    boosted = await run_analysis(DOM_HTML, None)  # also has Pre-ticked Box
    boosted_confirm_shaming = next(f for f in boosted if f["pattern_type"] == "Confirm Shaming")

    assert boosted_confirm_shaming["confidence_score"] > baseline_confirm_shaming["confidence_score"]


@pytest.mark.asyncio
async def test_run_analysis_skips_page_dependent_checks_without_page(monkeypatch):
    monkeypatch.setattr("app.analysis.pipeline.classify_text", lambda text, client=None: [])
    # Must not raise even though page=None - find_low_contrast_legal_text is
    # page-dependent and simply skipped when no page object is provided.
    findings = await run_analysis(DOM_HTML, None, page=None)
    assert isinstance(findings, list)
