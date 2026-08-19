import logging

from app.analysis.heuristics import find_preticked_checkboxes, find_countdown_elements
from app.analysis.text_extract import extract_main_text
from app.analysis.llm_classify import classify_text
from app.analysis.visual import compute_button_asymmetry
from app.compliance import map_to_norm

logger = logging.getLogger(__name__)


def run_analysis(dom_html: str, button_styles: dict | None, llm_client=None) -> list[dict]:
    findings: list[dict] = []

    findings.extend(find_preticked_checkboxes(dom_html))
    findings.extend(find_countdown_elements(dom_html))

    main_text = extract_main_text(dom_html)
    try:
        findings.extend(classify_text(main_text, client=llm_client))
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, LLM call
        logger.warning("classify_text failed, continuing without LLM findings: %s", exc)

    if button_styles is not None:
        findings.extend(
            compute_button_asymmetry(button_styles["accept"], button_styles["reject"])
        )

    for f in findings:
        f["target_norm"] = map_to_norm(f["pattern_type"])

    return findings
