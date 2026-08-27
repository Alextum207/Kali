import pytest
from app.analysis.pipeline import filter_unverified_llm_findings, run_analysis

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


async def _fake_classify_text(text, client=None):
    # Quotes whatever text it was given — mirrors an honest LLM, so the
    # finding survives run_analysis's new quote verification on any input
    # (including pages whose extracted text doesn't contain the sentence
    # below, like the minimal baseline DOM in the boost test).
    return [
        {
            "pattern_type": "Confirm Shaming",
            "confidence_score": 0.8,
            "evidence_data": {"quote": text},
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
    async def _empty_classify_text(text, client=None):
        return []

    monkeypatch.setattr("app.analysis.pipeline.classify_text", _empty_classify_text)
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
async def test_run_analysis_finds_regex_patterns(monkeypatch):
    async def _empty_classify_text(text, client=None):
        return []

    monkeypatch.setattr("app.analysis.pipeline.classify_text", _empty_classify_text)
    dom = """
    <html><body><main><p>Only 3 items available, order now.</p></main></body></html>
    """
    findings = await run_analysis(dom, None)
    scarcity = next(f for f in findings if f["pattern_type"] == "Fake Scarcity")
    assert scarcity["target_norm"] != "Unbekannt"


def _llm_finding(quote):
    return {
        "pattern_type": "Confirm Shaming",
        "confidence_score": 0.8,
        "evidence_data": {"quote": quote},
    }


def test_filter_keeps_verbatim_quote():
    source = "Leider wollen Sie wohl immer den vollen Preis bezahlen. Noch mehr Text hier."
    findings = [_llm_finding("den vollen Preis bezahlen")]
    assert filter_unverified_llm_findings(findings, source) == findings


def test_filter_drops_hallucinated_quote():
    source = "Ein ganz normaler Absatz über Versandkosten und Lieferzeiten."
    findings = [_llm_finding("Sie arme Tropf, Sie zahlen immer Vollpreis")]
    assert filter_unverified_llm_findings(findings, source) == []


def test_filter_tolerates_punctuation_drift():
    # Typographic quotes/dashes in the model's quote vs. plain text on the page.
    source = "No thanks, I enjoy paying full price for everything!"
    findings = [_llm_finding("\u201eNo thanks, I enjoy paying full price for everything!\u201c")]
    assert filter_unverified_llm_findings(findings, source) == findings


def test_filter_normalizes_whitespace_and_case():
    source = "Zeile 1\n     Zeile 2 mit  vielen   Leerzeichen"
    findings = [_llm_finding("zeile 2 MIT vielen Leerzeichen")]
    assert filter_unverified_llm_findings(findings, source) == findings


def test_filter_drops_empty_or_missing_quote():
    source = "irgendein Text"
    no_quote = {"pattern_type": "Nagging", "confidence_score": 0.5, "evidence_data": {}}
    empty_quote = _llm_finding("")
    assert filter_unverified_llm_findings([no_quote, empty_quote], source) == []


@pytest.mark.asyncio
async def test_run_analysis_drops_llm_finding_with_unverifiable_quote(monkeypatch):
    async def _hallucinating_classify_text(text, client=None):
        return [
            _llm_finding("Dieser Satz kommt im Text garantiert nicht vor."),
            _llm_finding("paying full price"),
        ]

    monkeypatch.setattr("app.analysis.pipeline.classify_text", _hallucinating_classify_text)
    findings = await run_analysis(DOM_HTML, None)
    confirm_shamings = [f for f in findings if f["pattern_type"] == "Confirm Shaming"]
    # Only the verbatim-quote finding survives; the hallucinated one is gone.
    assert len(confirm_shamings) == 1
    assert confirm_shamings[0]["evidence_data"]["quote"] == "paying full price"


@pytest.mark.asyncio
async def test_run_analysis_drops_findings_below_min_confidence(monkeypatch):
    async def _empty_classify_text(text, client=None):
        return []

    def _fake_decoy_pricing(dom_html):
        return [
            {"pattern_type": "Decoy Pricing", "confidence_score": 0.55, "evidence_data": {"note": "below"}},
            {"pattern_type": "Decoy Pricing", "confidence_score": 0.65, "evidence_data": {"note": "above"}},
        ]

    monkeypatch.setattr("app.analysis.pipeline.classify_text", _empty_classify_text)
    monkeypatch.setattr("app.analysis.pipeline.find_decoy_pricing", _fake_decoy_pricing)

    findings = await run_analysis("<html><body></body></html>", None)
    notes = {f["evidence_data"]["note"] for f in findings if f["pattern_type"] == "Decoy Pricing"}
    assert notes == {"above"}


@pytest.mark.asyncio
async def test_run_analysis_skips_page_dependent_checks_without_page(monkeypatch):
    async def _empty_classify_text(text, client=None):
        return []

    monkeypatch.setattr("app.analysis.pipeline.classify_text", _empty_classify_text)
    # Must not raise even though page=None - find_low_contrast_legal_text is
    # page-dependent and simply skipped when no page object is provided.
    findings = await run_analysis(DOM_HTML, None, page=None)
    assert isinstance(findings, list)
