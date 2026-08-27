"""Bild-Nachbearbeitung: zeichnet ein rotes Rechteck um die Textbox eines
Screenshots, die am besten zu einem Fund-Zitat passt, und schneidet danach
auf einen Ausschnitt um die Box (+ Randabstand) zu — der volle
full_page=True-Screenshot (app/crawler.py) kann mehrere Bildschirmhöhen
lang sein, ein Rechteck darauf war ohne Crop kaum zu finden. Crawl und
Analyse laufen bewusst getrennt (app/scan.py bekommt nur DOM-Strings +
Screenshot-Bytes, nicht die lebende Playwright-`page`, die zum
Analyse-Zeitpunkt schon geschlossen ist) — Hervorheben kann daher nur als
Bild-Nachbearbeitung passieren, mit den beim Crawl live erfassten
Bounding-Boxes (app/crawler.py::_capture_text_element_boxes) als
Rohmaterial.
"""
import io
import logging
import re

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

_HIGHLIGHT_COLOR = (220, 20, 20)
_HIGHLIGHT_WIDTH = 4
# Padding (px) around the matched box for the zoomed crop — enough to show
# surrounding context (e.g. which button/section the quote sits in) without
# still being most of a full_page screenshot.
_CROP_PADDING = 200


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _best_matching_box(quote: str, text_boxes: list[dict]) -> dict | None:
    """Die kleinste Box, deren Text das Zitat enthält oder im Zitat
    enthalten ist — deckt beide Richtungen ab: das Zitat ist kürzer als
    der Blocktext (z.B. LLM-Zitat aus einem längeren Absatz), oder das
    Zitat erstreckt sich über mehrere Leaf-Elemente hinweg (dann die
    bestmögliche Einzel-Box, die zumindest einen Teil davon trägt)."""
    normalized_quote = _normalize(quote)
    if not normalized_quote:
        return None

    candidates = []
    for box in text_boxes:
        normalized_box_text = _normalize(box.get("text", ""))
        if not normalized_box_text:
            continue
        if normalized_box_text in normalized_quote or normalized_quote in normalized_box_text:
            candidates.append(box)

    if not candidates:
        return None
    return min(candidates, key=lambda b: b["width"] * b["height"])


def highlight_quote_in_screenshot(screenshot_bytes: bytes, quote: str, text_boxes: list[dict]) -> bytes | None:
    """Zeichnet ein rotes Rechteck um die Box, deren Text am besten zum
    Zitat passt, und schneidet das Bild danach auf diese Box + Randabstand
    zu (siehe _CROP_PADDING) — sonst verschwindet das Rechteck auf einem
    ganzseitigen Screenshot. None (kein Bild) wenn keine Box gut genug
    passt — dann bleibt der generische Screenshot die einzige Evidenz für
    den Fund, wie bisher. Best-effort, nie ein Fehler nach außen."""
    box = _best_matching_box(quote, text_boxes)
    if box is None:
        return None

    try:
        img = Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")
        draw = ImageDraw.Draw(img)
        x0, y0 = box["x"], box["y"]
        x1, y1 = x0 + box["width"], y0 + box["height"]
        draw.rectangle([x0, y0, x1, y1], outline=_HIGHLIGHT_COLOR, width=_HIGHLIGHT_WIDTH)

        img_w, img_h = img.size
        crop_box = (
            max(0, x0 - _CROP_PADDING),
            max(0, y0 - _CROP_PADDING),
            min(img_w, x1 + _CROP_PADDING),
            min(img_h, y1 + _CROP_PADDING),
        )
        cropped = img.crop(crop_box)

        out = io.BytesIO()
        cropped.save(out, format="PNG")
        return out.getvalue()
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, image data can vary
        logger.debug("highlight_quote_in_screenshot failed: %s", exc)
        return None
