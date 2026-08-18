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


@pytest.mark.asyncio
async def test_fetch_citation_returns_text_on_success():
    def handler(request):
        return httpx.Response(200, json={"text": "Art. 25 DSA Volltext..."})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8091") as client:
        text = await fetch_citation("Art. 25 DSA", "http://localhost:8091", client=client)
    assert text == "Art. 25 DSA Volltext..."


@pytest.mark.asyncio
async def test_fetch_citation_returns_none_on_connection_error():
    def handler(request):
        raise httpx.ConnectError("no server", request=request)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8091") as client:
        text = await fetch_citation("Art. 25 DSA", "http://localhost:8091", client=client)
    assert text is None
