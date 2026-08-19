import logging

from app.analysis.heuristics import (
    find_preticked_checkboxes,
    find_countdown_elements,
    find_trick_questions,
    find_autoplay_media,
)
from app.analysis.readability import flag_complex_language
from app.analysis.text_extract import extract_main_text
from app.analysis.llm_classify import classify_text
from app.analysis.visual import compute_button_asymmetry
from app.compliance import map_to_norm

logger = logging.getLogger(__name__)

# Confidence rises when multiple distinct manipulation mechanisms co-occur
# on the same page (the book's "Double Shot" effect: persuasion + deception
# stacked together signal deliberate intent, not an isolated UX slip).
_COOCCURRENCE_BOOST = 0.05


async def run_analysis(
    dom_html: str, button_styles: dict | None, llm_client=None, page=None
) -> list[dict]:
    findings: list[dict] = []

    findings.extend(find_preticked_checkboxes(dom_html))
    findings.extend(find_countdown_elements(dom_html))
    findings.extend(find_trick_questions(dom_html))
    findings.extend(find_autoplay_media(dom_html))

    main_text = extract_main_text(dom_html)
    try:
        findings.extend(classify_text(main_text, client=llm_client))
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
        boost = _COOCCURRENCE_BOOST * (len(distinct_types) - 1)
        for f in findings:
            f["confidence_score"] = round(min(f["confidence_score"] + boost, 1.0), 2)

    for f in findings:
        f["target_norm"] = map_to_norm(f["pattern_type"])

    return findings
