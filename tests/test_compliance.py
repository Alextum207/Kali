import httpx
import pytest
from app.compliance import map_to_norm, fetch_citation


def test_map_known_patterns():
    assert map_to_norm("Fake Urgency") == "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3"
    assert map_to_norm("Confirm Shaming") == "Art. 25 DSA"
    assert map_to_norm("Pre-ticked Box") == "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO"
    assert map_to_norm("Hidden Costs") == "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB"
    assert map_to_norm("Preisaufschlag") == "PAngV"


def test_map_unknown_pattern_returns_placeholder():
    assert map_to_norm("Something Weird") == "Unbekannt"


def test_llm_prompt_pattern_types_all_resolve_to_a_norm():
    """Contract test: every pattern_type Claude is instructed to emit (per
    llm_classify.SYSTEM_PROMPT's enum list) must resolve through map_to_norm.
    Prevents drift between the prompt's vocabulary and NORM_MAP's keys."""
    prompt_pattern_types = [
        "Fake Urgency",
        "Fake Scarcity",
        "Fake Social Proof",
        "Confirm Shaming",
        "Sneaking / Hidden Costs",
        "Forced Continuity",
        "Decoy Pricing",
        "Nagging",
        "Roach Motel",
        "Forced Path",
    ]
    for pattern_type in prompt_pattern_types:
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
