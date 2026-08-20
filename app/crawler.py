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

LEGAL_TEXT_KEYWORDS = (
    "kündigung",
    "widerruf",
    "gebühr",
    "vertragslaufzeit",
    "agb",
    "schiedsgericht",
    "laufzeit",
    "kosten",
    "preis",
    "datenschutz",
    "rücktritt",
    "haftung",
    "widerspruch",
)


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
    """Walk a Consent-O-Matic rule's action tree, yielding the full action dict
    for anything that looks like a clickable target (action.type in ("click",
    "reject")). Handles both the real upstream shape (action.target.selector,
    optional action.target.textFilter, optional action.parent scoping) and
    nested "list"/"foreach" actions. Yielding the whole action (not just a
    stripped (selector, hint) pair) preserves the `parent`/`childFilter`
    scoping info so a bare tag-name target isn't clicked page-wide."""
    if isinstance(node, dict):
        action = node.get("action", node)
        a_type = action.get("type") if isinstance(action, dict) else None
        if a_type in ("click", "reject") and action.get("target", {}).get("selector"):
            yield action
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


# A bare tag-name selector like "button" is only safe to click when the
# rule's own `parent` scoping narrows it to a specific container (e.g.
# Reddit's rule scopes "button" to the <section> that also contains the
# cookie-notice link) — clicking it page-wide would hit the first visible
# <button>/<a>/... anywhere on the page, which on an ordinary site (e.g. a
# product page's own "add to cart" button) has nothing to do with cookie
# consent. _scoped_selector reconstructs that `parent`/`childFilter` scoping
# via Playwright's `:has()` (supported regardless of browser CSS support);
# only a target with no scoping info at all falls back to being skipped.
_GENERIC_TAG_SELECTORS = {"a", "button", "div", "span", "input", "section", "p"}


def _is_generic_selector(selector: str) -> bool:
    return selector.strip().lower() in _GENERIC_TAG_SELECTORS


def _scoped_selector(action: dict) -> str | None:
    """Returns a CSS selector for an action's click target, narrowed by the
    rule's `parent`/`childFilter` when present, and by `textFilter` when
    given (e.g. distinguishing an "Accept all" button from a "Reject
    non-essential" button that share the same tag/parent — Playwright's
    `:has-text()` extension does the text match). Returns None if the target
    is a bare tag name with no parent scoping to narrow it safely."""
    target = action.get("target", {})
    selector = target.get("selector")
    if not selector:
        return None

    parent = action.get("parent") or {}
    parent_selector = parent.get("selector")
    if not parent_selector:
        base = None if _is_generic_selector(selector) else selector
    else:
        child_selector = parent.get("childFilter", {}).get("target", {}).get("selector")
        scoped_parent = f"{parent_selector}:has({child_selector})" if child_selector else parent_selector
        base = f"{scoped_parent} {selector}"

    if base is None:
        return None

    text_filter = target.get("textFilter")
    if text_filter:
        text = text_filter[0] if isinstance(text_filter, list) else text_filter
        base = f'{base}:has-text("{text}")'
    return base


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

            for action in _iter_click_candidates(data):
                hint = action.get("target", {}).get("textFilter") or action.get("type")
                if not _looks_like_reject(hint):
                    continue
                selector = _scoped_selector(action)
                if not selector:
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


async def _snapshot_page(page, skip_diff_sleep: bool = False) -> dict:
    dom_before = await page.content()
    if not skip_diff_sleep:
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


_CAPTCHA_MARKERS = (
    "recaptcha", "hcaptcha", "h-captcha", "turnstile", "challenges.cloudflare.com",
    "verify you are human", "bestätigen sie, dass sie kein roboter",
    "i'm not a robot", "ich bin kein roboter", "checking your browser",
)


def _looks_like_captcha(dom_html: str) -> bool:
    """Cheap keyword heuristic — good enough to catch the big 3 (reCAPTCHA,
    hCaptcha, Cloudflare Turnstile) without a DOM-structure parser. Only
    ever called on the crawl's start page (see crawl_site) — false
    positives just mean an unnecessary retry-prompt, not a broken crawl."""
    haystack = dom_html.lower()
    return any(marker in haystack for marker in _CAPTCHA_MARKERS)


class CaptchaRequiredError(Exception):
    """Raised by crawl_site when the start page itself looks captcha-gated
    — only a human looking at the real (non-headless) tab can resolve this,
    so the crawl aborts immediately instead of wasting the scan budget."""

    def __init__(self, url: str):
        super().__init__(f"Captcha detected on start page: {url}")
        self.url = url


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
    await page.goto(url, wait_until="domcontentloaded")

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
        if not any(kw in text_lower for kw in LEGAL_TEXT_KEYWORDS):
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
