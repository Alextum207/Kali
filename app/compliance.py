import logging
from collections import Counter

import httpx

logger = logging.getLogger(__name__)

NORM_MAP = {
    "Fake Urgency": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Fake Scarcity": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Fake Social Proof": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Sneaking / Hidden Costs": "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB",
    "Confirm Shaming": "Art. 25 DSA",
    "Visuelle Asymmetrie (Button)": "Art. 25 DSA",
    "Pre-ticked Box": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "Trick Questions": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "Forced Continuity": "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB",
    "Decoy Pricing": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Nagging": "Art. 25 DSA",
    "Roach Motel": "Art. 25 DSA",
    "Forced Path": "Art. 25 DSA",
    "Exploiting Addiction (Autoplay)": "Art. 25 DSA",
    "Exploiting Addiction (Infinite Scroll)": "Art. 25 DSA",
    "Verständnis-Barriere (Sprachkomplexität)": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Visuelle Tarnung (Kontrast)": "Art. 25 DSA",
    "Fehlende Reject-Option (Cookie-Banner)": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "Cookie Wall": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
}


def map_to_norm(pattern_type: str) -> str:
    return NORM_MAP.get(pattern_type, "Unbekannt")


def aggregate_risk_score(findings: list[dict]) -> dict:
    """Simple, explainable risk metric — mean confidence across findings,
    nudged up by finding volume. Not empirically calibrated; the level
    cutoffs (0.34 / 0.67) are a deliberate simplification for the demo.
    ponytail: revisit cutoffs/weighting if real scans show a level that
    reads as clearly wrong to a reviewer."""
    if not findings:
        return {"score": 0.0, "level": "niedrig", "by_category": {}}

    mean_confidence = sum(f["confidence_score"] for f in findings) / len(findings)
    volume_factor = min(len(findings) / 20, 0.15)
    score = min(mean_confidence + volume_factor, 1.0)

    if score < 0.34:
        level = "niedrig"
    elif score < 0.67:
        level = "mittel"
    else:
        level = "hoch"

    by_category = dict(Counter(f["pattern_type"] for f in findings))
    return {"score": score, "level": level, "by_category": by_category}


# Quelle: Recherche/Dark Patterns.md (internes Rechts-Sheet). Lokaler
# Fallback, wenn legal-text-mcp-de keinen Treffer liefert (offline, Norm
# nicht indexiert) — deckt nur die Normen ab, für die das Sheet Volltext
# hat (operative Absätze, Boilerplate-Aufzählungen weggelassen); alles
# andere bleibt auf den Live-Service angewiesen.
STATUTE_TEXTS: dict[str, str] = {
    "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3": (
        "§ 5 UWG (Irreführende geschäftliche Handlungen): "
        "(1) Unlauter handelt, wer eine irreführende geschäftliche Handlung "
        "vornimmt, die geeignet ist, den Verbraucher zu einer geschäftlichen "
        "Entscheidung zu veranlassen, die er andernfalls nicht getroffen "
        "hätte. (5) Es wird vermutet, dass es irreführend ist, mit der "
        "Herabsetzung eines Preises zu werben, sofern der Preis nur für eine "
        "unangemessen kurze Zeit gefordert worden ist.\n"
        "§ 5a UWG (Irreführung durch Unterlassen): (1) Unlauter handelt "
        "auch, wer einen Verbraucher irreführt, indem er ihm eine "
        "wesentliche Information vorenthält, die der Verbraucher benötigt, "
        "um eine informierte geschäftliche Entscheidung zu treffen. "
        "(2) Als Vorenthalten gilt auch das Verheimlichen wesentlicher "
        "Informationen sowie deren unklare, unverständliche oder "
        "zweideutige Bereitstellung."
    ),
    "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB": (
        "§ 312j BGB (Besondere Pflichten im elektronischen Geschäftsverkehr "
        "gegenüber Verbrauchern): (3) Der Unternehmer hat die "
        "Bestellsituation so zu gestalten, dass der Verbraucher mit seiner "
        "Bestellung ausdrücklich bestätigt, dass er sich zu einer Zahlung "
        "verpflichtet. Erfolgt die Bestellung über eine Schaltfläche, ist "
        "die Pflicht nur erfüllt, wenn diese gut lesbar mit nichts anderem "
        "als den Wörtern „zahlungspflichtig bestellen“ oder einer "
        "entsprechend eindeutigen Formulierung beschriftet ist. (4) Ein "
        "Vertrag nach Absatz 2 kommt nur zustande, wenn der Unternehmer "
        "seine Pflicht aus Absatz 3 erfüllt. (Art. 246a EGBGB selbst ist im "
        "Recherche-Sheet nicht im Volltext erfasst.)"
    ),
    "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO": (
        "Art. 4 Nr. 11 DSGVO: „Einwilligung“ der betroffenen Person jede "
        "freiwillig für den bestimmten Fall, in informierter Weise und "
        "unmissverständlich abgegebene Willensbekundung in Form einer "
        "Erklärung oder einer sonstigen eindeutigen bestätigenden Handlung, "
        "mit der die betroffene Person zu verstehen gibt, dass sie mit der "
        "Verarbeitung der sie betreffenden personenbezogenen Daten "
        "einverstanden ist.\n"
        "Art. 7 DSGVO (Bedingungen für die Einwilligung): Die betroffene "
        "Person hat das Recht, ihre Einwilligung jederzeit zu widerrufen; "
        "der Widerruf muss so einfach wie die Erteilung sein. Bei der "
        "Beurteilung, ob die Einwilligung freiwillig erteilt wurde, muss "
        "berücksichtigt werden, ob die Erfüllung eines Vertrags von einer "
        "Einwilligung abhängig gemacht wird, die für die Vertragserfüllung "
        "nicht erforderlich ist (Kopplungsverbot)."
    ),
}


# Kurzhinweise, wie ein Fund gerichtsfest nachbelegt werden kann — ein Satz
# pro Pattern-Typ, aus `noch ergämnzen/.../Legal framework sheet ...md`
# verdichtet. Deckt alle NORM_MAP-Typen ab.
EVIDENCE_HINTS: dict[str, str] = {
    "Fake Urgency": "Screenshot vor/nach Reload + Zeitstempel prüfen, ob Countdown neu startet.",
    "Fake Scarcity": "Seite zu mehreren Zeitpunkten besuchen und Bestandshinweis vergleichen.",
    "Fake Social Proof": "Seite mehrfach/in neuer Session laden und angezeigte Nutzerzahlen vergleichen.",
    "Sneaking / Hidden Costs": "Checkout Schritt für Schritt durchlaufen, Gesamtpreis je Schritt dokumentieren, prüfen wann Zusatzkosten erstmals erscheinen.",
    "Confirm Shaming": "Exakten Wortlaut der Ablehnungsoption per Screenshot sichern.",
    "Visuelle Asymmetrie (Button)": "Screenshot beider Buttons nebeneinander, Kontrast/Größe/Position vergleichen.",
    "Pre-ticked Box": "Screenshot vor jeder Nutzerinteraktion — zeigt Standardzustand der Checkbox.",
    "Trick Questions": "Dialogtext per Screenshot sichern, Formulierung und Ergebnis jeder Auswahlmöglichkeit dokumentieren.",
    "Forced Continuity": "Abschluss- und Kündigungsprozess vollständig durchlaufen, verfügbare Kündigungskanäle dokumentieren.",
    "Decoy Pricing": "Screenshot der Preistabelle mit allen Optionen, Preis-/Leistungsverhältnis dokumentieren.",
    "Nagging": "Häufigkeit und Zeitpunkte wiederholter Aufforderungen über eine Sitzung protokollieren.",
    "Roach Motel": "Kündigungspfad vollständig durchklicken und Schrittzahl/-kanäle dokumentieren.",
    "Forced Path": "Klickpfad Schritt für Schritt dokumentieren, prüfen ob ein direkter Weg zum Ziel fehlt.",
    "Exploiting Addiction (Autoplay)": "Screen-Recording, das automatisches Abspielen ohne Nutzerinteraktion zeigt.",
    "Exploiting Addiction (Infinite Scroll)": "Screen-Recording des endlosen Nachladens ohne erkennbares Seitenende dokumentieren.",
    "Verständnis-Barriere (Sprachkomplexität)": "Textstelle per Screenshot sichern, Lesbarkeit/Fachjargon im Kontext dokumentieren.",
    "Visuelle Tarnung (Kontrast)": "Berechneten Kontrastwert und Screenshot des betroffenen Elements dokumentieren.",
    "Fehlende Reject-Option (Cookie-Banner)": "Screenshot des Banners vor Interaktion — zeigt, ob eine gleichwertige Ablehnen-Option fehlt.",
    "Cookie Wall": "Ablehnen versuchen und dokumentieren, ob Zugang zur Seite ohne Einwilligung verweigert wird.",
}


# Endpoint verified via OpenAPI schema: legal-text-mcp-de HTTP API
# (uvx legal-text-mcp-de http on http://0.0.0.0:8080)
# Endpoint: /search (query param, not q; SearchResponse with results array)
NORM_LOOKUP_PATH = "/search"


async def fetch_citation(
    norm: str, base_url: str, client: "httpx.AsyncClient | None" = None
) -> str | None:
    """Fetches the cite-grade statute text for a norm from legal-text-mcp-de.
    Falls back to STATUTE_TEXTS (local, only covers a few norms) if the live
    service is unreachable or has no result — never raises, and only
    returns None if neither source has anything, so report generation is
    never blocked."""
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(base_url=base_url, timeout=5.0)
    try:
        response = await client.get(NORM_LOOKUP_PATH, params={"query": norm})
        response.raise_for_status()
        # SearchResponse has { query, results: [...], count, codes }
        # Each result has norm object with text field
        results = response.json().get("results") or []
        live_text = results[0].get("norm", {}).get("text") if results else None
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, network call
        logger.warning("legal-text-mcp-de lookup failed for %r: %s", norm, exc)
        live_text = None
    finally:
        if owns_client:
            await client.aclose()
    return live_text if live_text is not None else STATUTE_TEXTS.get(norm)
