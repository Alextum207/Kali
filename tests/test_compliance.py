import httpx
import pytest
from app.compliance import map_to_norm, fetch_citation
from app.analysis.llm_classify import PATTERN_TYPES


def test_map_known_patterns():
    assert map_to_norm("Fake Urgency") == "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3"
    assert map_to_norm("Confirm Shaming") == "Art. 25 DSA"
    assert map_to_norm("Pre-ticked Box") == "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO"


def test_map_unknown_pattern_returns_placeholder():
    assert map_to_norm("Something Weird") == "Unbekannt"


def test_map_removed_dead_entries_returns_placeholder():
    """These 4 NORM_MAP entries were never referenced by any finding
    producer (LLM prompt or heuristics) — removed as dead weight."""
    for pattern_type in [
        "Unklare Button-Beschriftung",
        "Obstruction",
        "Verdeckter Opt-out",
        "Preisaufschlag",
    ]:
        assert map_to_norm(pattern_type) == "Unbekannt"


def test_llm_prompt_pattern_types_all_resolve_to_a_norm():
    """Contract test: every pattern_type Claude is instructed to emit (per
    llm_classify.PATTERN_TYPES, the actual tool-schema enum) must resolve
    through map_to_norm. Prevents drift between the prompt's vocabulary and
    NORM_MAP's keys."""
    for pattern_type in PATTERN_TYPES:
        assert map_to_norm(pattern_type) != "Unbekannt", pattern_type


def test_map_heuristic_and_visual_pattern_types():
    """Same contract, for the non-LLM pattern types produced by the DOM
    heuristics, readability check, and generic contrast scan."""
    heuristic_pattern_types = [
        "Trick Questions",
        "Exploiting Addiction (Autoplay)",
        "Exploiting Addiction (Infinite Scroll)",
        "Verständnis-Barriere (Sprachkomplexität)",
        "Visuelle Tarnung (Kontrast)",
    ]
    for pattern_type in heuristic_pattern_types:
        assert map_to_norm(pattern_type) != "Unbekannt", pattern_type


@pytest.mark.asyncio
async def test_fetch_citation_returns_text_on_success():
    def handler(request):
        # Real SearchResponse from legal-text-mcp-de HTTP API
        return httpx.Response(200, json={
            "query": "Art. 25 DSA",
            "results": [
                {"norm": {"text": "Art. 25 DSA Volltext..."}}
            ],
            "count": 1
        })
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8080") as client:
        text = await fetch_citation("Art. 25 DSA", "http://localhost:8080", client=client)
    assert text == "Art. 25 DSA Volltext..."


@pytest.mark.asyncio
async def test_fetch_citation_returns_none_on_connection_error():
    def handler(request):
        raise httpx.ConnectError("no server", request=request)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8080") as client:
        text = await fetch_citation("Art. 25 DSA", "http://localhost:8080", client=client)
    assert text is None  # "Art. 25 DSA" has no local STATUTE_TEXTS fallback


@pytest.mark.asyncio
async def test_fetch_citation_falls_back_to_local_statute_text_when_live_lookup_empty():
    def handler(request):
        return httpx.Response(200, json={"query": "x", "results": [], "count": 0})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8080") as client:
        text = await fetch_citation(
            "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3", "http://localhost:8080", client=client
        )
    assert text is not None
    assert "§ 5 UWG" in text


@pytest.mark.asyncio
async def test_fetch_citation_prefers_live_result_over_local_fallback():
    def handler(request):
        return httpx.Response(200, json={
            "results": [{"norm": {"text": "Live-Text hat Vorrang"}}]
        })
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8080") as client:
        text = await fetch_citation(
            "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3", "http://localhost:8080", client=client
        )
    assert text == "Live-Text hat Vorrang"


def test_aggregate_risk_score_empty_findings():
    from app.compliance import aggregate_risk_score

    result = aggregate_risk_score([])

    assert result == {"score": 0.0, "level": "niedrig", "by_category": {}}


def test_aggregate_risk_score_low_level():
    from app.compliance import aggregate_risk_score

    result = aggregate_risk_score([
        {"pattern_type": "Pre-ticked Box", "confidence_score": 0.2},
    ])

    assert result["score"] == pytest.approx(0.25)
    assert result["level"] == "niedrig"
    assert result["by_category"] == {"Pre-ticked Box": 1}


def test_aggregate_risk_score_medium_level():
    from app.compliance import aggregate_risk_score

    result = aggregate_risk_score([
        {"pattern_type": "Confirm Shaming", "confidence_score": 0.5},
    ])

    assert result["score"] == pytest.approx(0.55)
    assert result["level"] == "mittel"


def test_aggregate_risk_score_high_level_and_multiple_categories():
    from app.compliance import aggregate_risk_score

    result = aggregate_risk_score([
        {"pattern_type": "Confirm Shaming", "confidence_score": 0.9},
        {"pattern_type": "Confirm Shaming", "confidence_score": 0.9},
        {"pattern_type": "Fake Urgency", "confidence_score": 0.9},
    ])

    assert result["level"] == "hoch"
    assert result["score"] <= 1.0
    assert result["by_category"] == {"Confirm Shaming": 2, "Fake Urgency": 1}
