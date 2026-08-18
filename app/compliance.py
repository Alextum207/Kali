import logging
import httpx

logger = logging.getLogger(__name__)

NORM_MAP = {
    "Fake Urgency": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Fake Scarcity": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Fake Social Proof": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Hidden Costs": "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB",
    "Unklare Button-Beschriftung": "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB",
    "Confirm Shaming": "Art. 25 DSA",
    "Visuelle Asymmetrie (Button)": "Art. 25 DSA",
    "Obstruction": "Art. 25 DSA",
    "Pre-ticked Box": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "Verdeckter Opt-out": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "Preisaufschlag": "PAngV",
}


def map_to_norm(pattern_type: str) -> str:
    return NORM_MAP.get(pattern_type, "Unbekannt")


# Endpoint path is the assumed REST shape of legal-text-mcp-de's HTTP API
# (mirrors the "legal://laws/{law}/norms/{id}" resource URI documented in the
# repo). VERIFY against the running server's /docs (uvx legal-text-mcp-de
# serve) and adjust this path if the OpenAPI schema differs.
NORM_LOOKUP_PATH = "/search"


async def fetch_citation(
    norm: str, base_url: str, client: "httpx.AsyncClient | None" = None
) -> str | None:
    """Fetches the cite-grade statute text for a norm from legal-text-mcp-de.
    Returns None (never raises) if the server is unreachable or the norm
    isn't found — a missing citation must not block report generation."""
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(base_url=base_url, timeout=5.0)
    try:
        response = await client.get(NORM_LOOKUP_PATH, params={"q": norm})
        response.raise_for_status()
        return response.json().get("text")
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, network call
        logger.warning("legal-text-mcp-de lookup failed for %r: %s", norm, exc)
        return None
    finally:
        if owns_client:
            await client.aclose()
