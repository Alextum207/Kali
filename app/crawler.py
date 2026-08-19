import asyncio
import json
import logging
import pathlib
import tempfile
import uuid

from app.analysis.visual import contrast_ratio

logger = logging.getLogger(__name__)

DEFAULT_CONSENT_RULES_DIR = str(
    pathlib.Path(__file__).resolve().parent.parent / "data" / "consent_rules"
)

# Best-effort keywords for identifying a "reject/decline all" click target when
# a Consent-O-Matic rule doesn't carry an explicit reject hint.
_REJECT_KEYWORDS = (
    "reject",
    "decline",
    "ablehnen",
    "opt out",
    "opt-out",
    "only necessary",
    "nur notwendig",
    "alle ablehnen",
)

_LEGAL_TEXT_KEYWORDS = ("kündigung", "widerruf", "gebühr", "vertragslaufzeit", "agb", "schiedsgericht")


async def _read_style(page, selector: str) -> dict | None:
    # ponytail: eval_on_selector raises (not None-returns) when no element
    # matches — on real sites #accept/#reject essentially never exist, so
    # this must degrade gracefully. Upgrade path: real button discovery via
    # accessible-text matching (see _REJECT_KEYWORDS) instead of hardcoded IDs.
    try:
        box = await page.eval_on_selector(
            selector,
            """el => {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                const parseRgb = (s) => {
                    const m = s.match(/\\d+/g);
                    return m ? [parseInt(m[0]), parseInt(m[1]), parseInt(m[2])] : [0, 0, 0];
                };
                return {
                    width: rect.width,
                    height: rect.height,
                    bg_color: parseRgb(style.backgroundColor),
                    text_color: parseRgb(style.color),
                };
            }""",
        )
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, missing selector
        logger.debug("No element matched %r for style read: %s", selector, exc)
        return None
    if box is None:
        return None
    box["bg_color"] = tuple(box["bg_color"])
    box["text_color"] = tuple(box["text_color"])
    return box


def _iter_click_candidates(node):
    """Walk a Consent-O-Matic rule's action tree, yielding (selector, hint) pairs
    for anything that looks like a clickable target. Handles both the real
    upstream shape (action.type == "click", action.target.selector, optional
    action.target.textFilter) and nested "list"/"foreach" actions."""
    if isinstance(node, dict):
        action = node.get("action", node)
        a_type = action.get("type") if isinstance(action, dict) else None
        if a_type in ("click", "reject"):
            target = action.get("target", {})
            selector = target.get("selector")
            hint = target.get("textFilter") or action.get("type")
            if selector:
                yield selector, hint
        # recurse into nested structures (list/foreach actions, method arrays, etc.)
        for value in node.values():
            yield from _iter_click_candidates(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_click_candidates(item)


def _looks_like_reject(hint) -> bool:
    if not hint:
        return False
    texts = hint if isinstance(hint, list) else [hint]
    joined = " ".join(str(t) for t in texts).lower()
    return any(kw in joined for kw in _REJECT_KEYWORDS)


async def apply_consent_rules(page, rules_dir: str = DEFAULT_CONSENT_RULES_DIR) -> None:
    """Best-effort cookie-banner rejection using vendored Consent-O-Matic rules.

    Loads every JSON rule file in `rules_dir`, extracts click targets that look
    like a "reject/decline" action, and clicks the first one found on the page.
    Never raises: a non-matching site or malformed rule file is logged and
    skipped so it can never break a crawl.
    """
    try:
        rules_path = pathlib.Path(rules_dir)
        if not rules_path.is_dir():
            logger.warning("apply_consent_rules: rules dir not found: %s", rules_dir)
            return

        for rule_file in sorted(rules_path.glob("*.json")):
            try:
                data = json.loads(rule_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("apply_consent_rules: skipping unparseable %s: %s", rule_file, exc)
                continue

            for selector, hint in _iter_click_candidates(data):
                if not _looks_like_reject(hint):
                    continue
                try:
                    el = await page.query_selector(selector)
                    if el and await el.is_visible():
                        await el.click(timeout=1000)
                        logger.info(
                            "apply_consent_rules: clicked %r from %s", selector, rule_file.name
                        )
                        return
                except Exception as exc:
                    logger.debug("apply_consent_rules: selector %r failed: %s", selector, exc)
                    continue
    except Exception as exc:  # pragma: no cover - defensive catch-all
        logger.warning("apply_consent_rules: best-effort pass failed: %s", exc)


async def _snapshot_page(page) -> dict:
    dom_before = await page.content()
    await asyncio.sleep(1.5)  # Dapde principle: catch script-driven DOM changes
    dom_after = await page.content()

    screenshot = await page.screenshot()

    button_styles = None
    accept_style = await _read_style(page, "#accept")
    reject_style = await _read_style(page, "#reject")
    if accept_style and reject_style:
        button_styles = {"accept": accept_style, "reject": reject_style}

    try:
        contrast_findings = await find_low_contrast_legal_text(page)
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
        logger.debug("_snapshot_page: find_low_contrast_legal_text failed: %s", exc)
        contrast_findings = []

    return {
        "dom_before": dom_before,
        "dom_after": dom_after,
        "screenshot": screenshot,
        "button_styles": button_styles,
        "contrast_findings": contrast_findings,
    }


async def crawl_page(
    url: str,
    browser,
    har_dir: str | None = None,
    consent_rules_dir: str = DEFAULT_CONSENT_RULES_DIR,
) -> dict:
    har_dir = har_dir or tempfile.gettempdir()
    pathlib.Path(har_dir).mkdir(parents=True, exist_ok=True)
    har_path = str(pathlib.Path(har_dir) / f"crawl-{uuid.uuid4().hex}.har")

    context = await browser.new_context(record_har_path=har_path)
    page = await context.new_page()
    await page.goto(url)

    await apply_consent_rules(page, consent_rules_dir)

    snapshot = await _snapshot_page(page)

    await page.close()
    await context.close()  # flushes the HAR file to disk

    return {**snapshot, "har_path": har_path}


async def find_low_contrast_legal_text(page) -> list[dict]:
    """Scans every leaf text element on the page for legally-relevant
    keywords and flags any whose contrast ratio or font size is well below
    the page's median — a generalization of the button-pair contrast check
    to the whole page, not just #accept/#reject."""
    try:
        elements = await page.eval_on_selector_all(
            "body *",
            """els => els
                .filter(el => el.children.length === 0 && el.textContent.trim().length > 0)
                .map(el => {
                    const style = getComputedStyle(el);
                    const parseRgb = (s) => {
                        const m = s.match(/\\d+/g);
                        return m ? [parseInt(m[0]), parseInt(m[1]), parseInt(m[2])] : [255, 255, 255];
                    };
                    return {
                        text: el.textContent.trim().slice(0, 200),
                        selector: el.tagName.toLowerCase() + (el.id ? '#' + el.id : ''),
                        font_size: parseFloat(style.fontSize),
                        color: parseRgb(style.color),
                        bg_color: parseRgb(style.backgroundColor),
                    };
                })""",
        )
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
        logger.debug("find_low_contrast_legal_text: eval failed: %s", exc)
        return []

    if not elements:
        return []

    font_sizes = sorted(e["font_size"] for e in elements if e["font_size"])
    median_font = font_sizes[len(font_sizes) // 2] if font_sizes else 16.0

    contrasts = []
    for e in elements:
        try:
            contrasts.append(contrast_ratio(tuple(e["color"]), tuple(e["bg_color"])))
        except Exception:
            contrasts.append(21.0)
    median_contrast = sorted(contrasts)[len(contrasts) // 2] if contrasts else 21.0

    findings = []
    for e, c in zip(elements, contrasts):
        text_lower = e["text"].lower()
        if not any(kw in text_lower for kw in _LEGAL_TEXT_KEYWORDS):
            continue
        camouflaged = c < median_contrast * 0.6 or (e["font_size"] and e["font_size"] < median_font * 0.75)
        if camouflaged:
            findings.append(
                {
                    "pattern_type": "Visuelle Tarnung (Kontrast)",
                    "confidence_score": 0.6,
                    "evidence_data": {
                        "selector": e["selector"],
                        "excerpt": e["text"],
                        "contrast_ratio": round(c, 2),
                        "page_median_contrast": round(median_contrast, 2),
                    },
                }
            )
    return findings
