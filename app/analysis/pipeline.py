import logging
import re

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

_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^\w]+", re.UNICODE)


def _normalize_for_quote_match(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip().lower()


def _quote_in_text(quote: str, source_text: str) -> bool:
    """True if `quote` plausibly appears verbatim in `source_text` — the text
    the LLM was actually given. Strict check is whitespace-normalized
    containment; a looser alphanumeric-only comparison follows, tolerating
    punctuation/typography drift (typographic quotes, dashes) between the
    model's quote and the extracted page text. Deliberately NOT fuzzy beyond
    that: a quote that survives neither check is treated as hallucinated.
    """
    normalized_quote = _normalize_for_quote_match(quote)
    normalized_source = _normalize_for_quote_match(source_text)
    if normalized_quote in normalized_source:
        return True
    bare_quote = _NON_ALNUM_RE.sub("", normalized_quote)
    bare_source = _NON_ALNUM_RE.sub("", normalized_source)
    return bool(bare_quote) and bare_quote in bare_source


def filter_unverified_llm_findings(findings: list[dict], source_text: str) -> list[dict]:
    """Drops LLM findings whose `evidence_data["quote"]` cannot be located in
    `source_text` (the exact text classify_text was given). The LLM is only
    prompted to quote verbatim, never verified — without this gate a single
    paraphrased or hallucinated quote goes straight into the DB, the report,
    AND breaks screenshot annotation downstream (screenshot_annotate matches
    on the same verbatim assumption). No quote field at all is also dropped:
    every finding this function filters carries one by construction of
    llm_classify._extract_findings. Best-effort audit trail: each drop is
    logged with pattern_type + quote excerpt so systematic model failures
    stay visible in the scan logs.
    """
    verified: list[dict] = []
    for finding in findings:
        quote = finding.get("evidence_data", {}).get("quote") or ""
        if quote and _quote_in_text(quote, source_text):
            verified.append(finding)
        else:
            logger.warning(
                "classify_text finding dropped: quote not found in page text "
                "(pattern_type=%r, quote=%r)",
                finding.get("pattern_type"),
                str(quote)[:120],
            )
    return verified


# Confidence rises when multiple distinct manipulation mechanisms co-occur
# on the same page (the book's "Double Shot" effect: persuasion + deception
# stacked together signal deliberate intent, not an isolated UX slip).
_COOCCURRENCE_BOOST = 0.05

# Findings below this confidence are dropped before they're ever stored or
# reported — generic/ambiguous single-signal detectors (autoplay attribute,
# decoy pricing, low-contrast legal text) were deliberately tuned to sit just
# under this cutoff (see their confidence_score comments), so they only
# survive when _COOCCURRENCE_BOOST pushes them over via a second, independent
# signal on the same page. Applied AFTER that boost for exactly this reason.
# ponytail: single global cutoff, not empirically calibrated per pattern
# type — revisit if real scans show a specific type needs its own threshold.
MIN_CONFIDENCE = 0.6

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

# Welche Pattern-Typen auf einer Seite dieser Kategorie überhaupt plausibel
# vorkommen können — reduziert False Positives, die entstehen, wenn z.B. ein
# Checkout-Text zufällig wie Fake Social Proof klingt. Dokumentiert (mit
# Begründung je Kategorie) in CLAUDE.md, Abschnitt "Kategorie-Scoping der
# Fund-Erkennung"; dort ist dieser Dict die Quelle der Wahrheit, die Doku
# verweist nur darauf. Kategorie ohne Eintrag hier (z.B. "other") bleibt
# ungefiltert. Nur beim Site-Crawl anwendbar (dort ist die Kategorie
# bekannt) — der Single-Page-Scan hat kein Kategorie-Signal und bleibt
# ungefiltert.
CATEGORY_ALLOWED_PATTERNS: dict[str, set[str]] = {
    "cookie_consent": {
        "Pre-ticked Box", "Trick Questions",
        "Fehlende Reject-Option (Cookie-Banner)", "Cookie Wall",
        "Visuelle Asymmetrie (Button)",
    },
    "checkout_payment": {
        "Decoy Pricing", "Hidden Costs", "Sneaking / Hidden Costs",
        "Fake Urgency", "Fake Scarcity", "Confirm Shaming", "Trick Questions",
        "Visuelle Asymmetrie (Button)",
        "Verständnis-Barriere (Sprachkomplexität)", "Visuelle Tarnung (Kontrast)",
    },
    "account_subscription": {
        "Roach Motel", "Forced Continuity", "Nagging", "Confirm Shaming",
        "Forced Path", "Verständnis-Barriere (Sprachkomplexität)",
        "Visuelle Tarnung (Kontrast)",
    },
    "product_category": {
        "Fake Scarcity", "Fake Social Proof", "Fake Urgency", "Decoy Pricing",
        "Exploiting Addiction (Autoplay)", "Exploiting Addiction (Infinite Scroll)",
    },
    "popup_leadform": {
        "Nagging", "Trick Questions", "Pre-ticked Box", "Confirm Shaming",
        "Forced Path",
    },
}


def filter_by_category(findings: list[dict], category: str | None) -> list[dict]:
    """Drops findings whose pattern_type isn't plausible for `category`
    (see CATEGORY_ALLOWED_PATTERNS). No entry for `category` (e.g. "other",
    or None) means unfiltered — safest default for pages that couldn't be
    classified."""
    allowed = CATEGORY_ALLOWED_PATTERNS.get(category or "")
    if allowed is None:
        return findings
    return [f for f in findings if f["pattern_type"] in allowed]


async def run_analysis(
    dom_html: str, button_styles: dict | None, llm_client=None, page=None,
    category: str | None = None,
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
        llm_findings = await classify_text(main_text, client=llm_client)
        findings.extend(filter_unverified_llm_findings(llm_findings, main_text))
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

    findings = [f for f in findings if f["confidence_score"] >= MIN_CONFIDENCE]

    for f in findings:
        f["target_norm"] = map_to_norm(f["pattern_type"])
        f["evidence_data"]["impact"] = IMPACT_MAP.get(f["pattern_type"], "–")

    return filter_by_category(findings, category)
