import logging

from app.analysis.heuristics import (
    find_preticked_checkboxes,
    find_trick_questions,
    find_default_consent_checkboxes,
    find_autoplay_media,
    find_decoy_pricing,
)
from app.analysis.readability import flag_complex_language
from app.analysis.text_extract import extract_main_text
from app.analysis.llm_classify import classify_text
from app.analysis.regex_classify import find_regex_patterns
from app.analysis.visual import compute_button_asymmetry
from app.compliance import map_to_norm

logger = logging.getLogger(__name__)

# Confidence rises when multiple distinct manipulation mechanisms co-occur
# on the same page (the book's "Double Shot" effect: persuasion + deception
# stacked together signal deliberate intent, not an isolated UX slip).
_COOCCURRENCE_BOOST = 0.05

# Kurzbeschreibung der Verbraucher-Auswirkung je Pattern-Typ, für die
# "Auswirkung"-Spalte in Findings-Tabelle/PDF-Report. Fallback "–" in den
# Templates greift für Findings, die außerhalb dieser Pipeline entstehen
# (z.B. Kontrast-/Infinite-Scroll-/Countdown-Funde in app/scan.py).
IMPACT_MAP = {
    "Fake Urgency": "Verbraucher wird zu überstürzter Kaufentscheidung gedrängt",
    "Fake Scarcity": "Verbraucher wird zu überstürzter Kaufentscheidung gedrängt",
    "Fake Social Proof": "Verbraucher wird durch erfundene Nachfrage getäuscht",
    "Hidden Costs": "Verbraucher zahlt unerwartete Zusatzkosten",
    "Sneaking / Hidden Costs": "Verbraucher zahlt unerwartete Zusatzkosten",
    "Confirm Shaming": "Verbraucher wird emotional zur Zustimmung gedrängt",
    "Visuelle Asymmetrie (Button)": "Verbraucher wird optisch zur gewünschten Wahl gelenkt",
    "Pre-ticked Box": "Verbraucher willigt ungewollt in Zusatzleistung ein",
    "Trick Questions": "Verbraucher verwechselt Zustimmung und Ablehnung",
    "Forced Continuity": "Verbraucher zahlt unbemerkt für Vertragsverlängerung",
    "Decoy Pricing": "Verbraucher wird zu teurerer Option gelenkt",
    "Nagging": "Verbraucher wird wiederholt zu einer Handlung gedrängt",
    "Roach Motel": "Verbraucher findet keinen einfachen Ausstieg (z.B. Kündigung)",
    "Forced Path": "Verbraucher muss unnötige Zwischenschritte durchlaufen",
    "Exploiting Addiction (Autoplay)": "Verbraucher wird unfreiwillig länger gebunden",
    "Exploiting Addiction (Infinite Scroll)": "Verbraucher wird unfreiwillig länger gebunden",
    "Verständnis-Barriere (Sprachkomplexität)": "Verbraucher versteht rechtlich relevante Klauseln nicht",
    "Visuelle Tarnung (Kontrast)": "Verbraucher übersieht rechtlich relevante Informationen",
    "Fehlende Reject-Option (Cookie-Banner)": "Verbraucher kann Einwilligung nicht ablehnen",
    "Cookie Wall": "Verbraucher kann Inhalt nicht ohne Einwilligung nutzen",
}


async def run_analysis(
    dom_html: str, button_styles: dict | None, llm_client=None, page=None
) -> list[dict]:
    findings: list[dict] = []

    findings.extend(find_preticked_checkboxes(dom_html))
    findings.extend(find_trick_questions(dom_html))
    findings.extend(find_default_consent_checkboxes(dom_html))
    findings.extend(find_autoplay_media(dom_html))
    findings.extend(find_decoy_pricing(dom_html))

    main_text = extract_main_text(dom_html)
    findings.extend(find_regex_patterns(main_text))
    try:
        findings.extend(await classify_text(main_text, client=llm_client))
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, LLM call
        logger.warning("classify_text failed, continuing without LLM findings: %s", exc)

    complexity_finding = flag_complex_language(main_text)
    if complexity_finding is not None:
        findings.append(complexity_finding)

    if button_styles is not None:
        findings.extend(
            compute_button_asymmetry(button_styles["accept"], button_styles["reject"])
        )

    if page is not None:
        # imported here to avoid a hard Playwright dependency for callers
        # that only ever pass page=None (e.g. the pre-existing sync tests)
        from app.crawler import find_low_contrast_legal_text

        try:
            findings.extend(await find_low_contrast_legal_text(page))
        except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
            logger.warning("find_low_contrast_legal_text failed: %s", exc)

    distinct_types = {f["pattern_type"] for f in findings}
    if len(distinct_types) > 1:
        # ponytail: co-occurrence boost is flat (same delta for 2 vs. 10 patterns).
        # Per-pattern weighting (e.g., Fake Urgency + Hidden Costs = higher boost than
        # Nagging + Roach Motel) could refine this, but adds complexity without
        # clear evidence it reduces false positives on real sites. Add if recall
        # degrades relative to a weighted version.
        boost = _COOCCURRENCE_BOOST * (len(distinct_types) - 1)
        for f in findings:
            f["confidence_score"] = round(min(f["confidence_score"] + boost, 1.0), 2)

    for f in findings:
        f["target_norm"] = map_to_norm(f["pattern_type"])
        f["evidence_data"]["impact"] = IMPACT_MAP.get(f["pattern_type"], "–")

    return findings
