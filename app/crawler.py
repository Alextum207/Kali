import asyncio
import difflib
import json
import logging
import os
import pathlib
import re
import tempfile
import uuid

import httpx

from app.analysis.heuristics import find_countdown_elements
from app.analysis.visual import contrast_ratio
from app.robots import USER_AGENT, RobotsDisallowedError, fetch_robots_parser

logger = logging.getLogger(__name__)

DEFAULT_CONSENT_RULES_DIR = str(
    pathlib.Path(__file__).resolve().parent.parent / "data" / "consent_rules"
)

# All three timeouts below are fractions of SCAN_SECONDS_PER_PAGE_BUDGET
# (site_crawler.py:106, same env var name read independently here — crawler.py
# can't import it directly without a circular import, since site_crawler.py
# already imports from crawler.py) instead of independent hardcoded values.
# Deriving them keeps nav/snapshot/consent budgets in sync with the overall
# per-page budget automatically: raising SCAN_SECONDS_PER_PAGE_BUDGET alone
# (e.g. for a slower host like Render's free tier) scales all three, instead
# of requiring 4 separate env vars kept in sync by hand — a real bug we hit
# live (Render stayed on old absolute defaults after the per-page budget was
# raised, and the crawl kept bailing out after the first page). Fractions
# chosen to reproduce the original hardcoded defaults exactly at the 25s
# default budget (12000ms / 20s / 20s) — no behavior change until the budget
# is tuned away from 25.
_PAGE_BUDGET_SECONDS = float(os.environ.get("SCAN_SECONDS_PER_PAGE_BUDGET", "25"))

# Playwright's own default navigation timeout is 30000ms — too long relative
# to a page's share of the scan time budget: one dead/slow page could burn
# more wall-clock than its whole nominal per-page budget. Leaves headroom
# under that for routing/flow-walk work on the same page while still
# tolerating legitimately slow-but-real sites.
NAV_TIMEOUT_MS = int(_PAGE_BUDGET_SECONDS * 0.48 * 1000)

# NAV_TIMEOUT_MS only bounds the initial page.goto() — none of
# _snapshot_page's own Playwright calls (page.content(), screenshot(), the
# reload inside verify_countdown_reset, ...) have a timeout of their own. A
# real site can leave the page mid-navigation after a flow-walk click (e.g.
# into a login/bot wall) where page.content() never resolves, hanging the
# whole crawl forever — confirmed against a live site (a "cancel
# subscription"-shaped click on a real e-commerce site's footer link).
# _snapshot_page is the one function every "read the page now" call in the
# crawl pipeline routes through, so bounding it there covers all callers.
SNAPSHOT_TIMEOUT_SECONDS = int(_PAGE_BUDGET_SECONDS * 0.8)

# apply_consent_rules iterates up to 206 vendored rule files (fast, pure
# selector matching) — confirmed live to get stuck at 0 pages crawled on
# amazon.de/verbraucherzentrale.de instead via _detect_cookie_wall's single
# page.evaluate() call, which has no timeout of its own (see that function's
# own asyncio.wait_for wrapper for the real fix to that specific hang).
# Bounded here like SNAPSHOT_TIMEOUT_SECONDS above so a stalled page still
# leaves room for the rest of the page's processing.
CONSENT_TIMEOUT_SECONDS = int(_PAGE_BUDGET_SECONDS * 0.8)

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

# Mirrors _REJECT_KEYWORDS for "accept all" click targets, used only to read
# the accept button's style for button-asymmetry detection — never to click
# it (clicking would grant consent, a policy line this tool must not cross
# just to capture a screenshot).
# ponytail: keyword matching only resolves a concrete accept/reject
# selector on a small minority of the 204 vendored rules (reject: 2/204,
# accept: an estimated ~10/204) — most sites model consent via per-category
# checkbox toggles + a "save" click (`"type": "consent"` nodes) rather than
# a single accept/reject button. Upgrade path: drive that toggle+save flow
# instead of only matching a single click target, if recall on real scans
# turns out to matter more than the speed/simplicity of this pass.
_ACCEPT_KEYWORDS = (
    "accept all",
    "agree",
    "akzeptieren",
    "zustimmen",
    "alle akzeptieren",
    "allow all",
    "einverstanden",
)

_COOKIE_CONTEXT_KEYWORDS = (
    "cookie",
    "cookies",
    "consent",
    "privacy",
    "datenschutz",
    "einwilligung",
    "zustimmung",
    "akzeptieren",
    "ablehnen",
    "accept all",
    "reject all",
)

_COOKIE_CONTROL_SELECTOR = "button, a, [role=button], input[type=button], input[type=submit]"

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

_LOW_CONTRAST_STRONG_LEGAL_PATTERN = re.compile(
    r"\b(?:"
    r"k.ndigung|kundigung|kuendigung|widerruf\w*|geb.hr\w*|gebuehr\w*|"
    r"vertragslaufzeit|agb|schiedsgericht|laufzeit|datenschutz|r.cktritt|ruecktritt|"
    r"haftung|widerspruch|einwilligung|zustimmung|privacy|terms|cancellation|withdrawal|liability"
    r")\b",
    re.IGNORECASE,
)
_LOW_CONTRAST_PRICE_OR_COST_PATTERN = re.compile(
    r"\b(?:"
    r"gesamtpreis|endpreis|zusatzkosten|versandkosten|servicegeb.hr\w*|servicegebuehr\w*|"
    r"bearbeitungsgeb.hr\w*|bearbeitungsgebuehr\w*|kostenpflichtig|zahlungspflichtig|"
    r"fees?|total price|shipping costs|service charge"
    r")\b",
    re.IGNORECASE,
)


def _looks_like_low_contrast_legal_text(text: str) -> bool:
    text_lower = text.lower()
    has_price_or_cost_context = bool(_LOW_CONTRAST_PRICE_OR_COST_PATTERN.search(text_lower))
    if has_price_or_cost_context:
        return True
    if not _LOW_CONTRAST_STRONG_LEGAL_PATTERN.search(text_lower):
        return False
    word_count = len(re.findall(r"[A-Za-zÀ-ÿ]+", text))
    return word_count >= 3


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
                    const m = s.match(/[\\d.]+/g);
                    if (m && m.length >= 4 && Number(m[3]) === 0) {
                        return [255, 255, 255];
                    }
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


def _looks_like_accept(hint) -> bool:
    if not hint:
        return False
    texts = hint if isinstance(hint, list) else [hint]
    joined = " ".join(str(t) for t in texts).lower()
    return any(kw in joined for kw in _ACCEPT_KEYWORDS)


async def _banner_has_cookie_context(page, selector: str) -> bool:
    try:
        text = await page.locator(selector).first.inner_text(timeout=750)
    except Exception as exc:  # noqa: BLE001 - unexpected selector/page state
        logger.debug("_banner_has_cookie_context: failed for %r: %s", selector, exc)
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in _COOKIE_CONTEXT_KEYWORDS)


async def _has_visible_keyword_control(page, container_selector: str, keywords: tuple[str, ...]) -> bool:
    try:
        controls = await page.locator(container_selector).first.locator(_COOKIE_CONTROL_SELECTOR).all()
    except Exception as exc:  # noqa: BLE001 - unexpected selector/page state
        logger.debug("_has_visible_keyword_control: failed for %r: %s", container_selector, exc)
        return False
    for control in controls:
        try:
            text = ((await control.inner_text(timeout=500)) or (await control.get_attribute("value") or "")).lower()
            if any(kw in text for kw in keywords) and await control.is_visible():
                return True
        except Exception:
            continue
    return False


def _has_consent_toggle(node) -> bool:
    """Structural signal that a rule models consent via per-category
    checkbox toggles + a save action (the dominant pattern across the
    vendored rules, see the ponytail note on _ACCEPT_KEYWORDS) rather than
    a single reject click. Used to avoid flagging "no reject option" on a
    site that does offer one, just not as a single click target."""
    if isinstance(node, dict):
        if node.get("type") == "consent":
            return True
        return any(_has_consent_toggle(value) for value in node.values())
    elif isinstance(node, list):
        return any(_has_consent_toggle(item) for item in node)
    return False


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


async def _matches_present_detector(page, data: dict) -> tuple[str, str] | None:
    """Returns (vendor_key, matched_selector) for the first of this rule's
    `presentMatcher` selectors that currently matches an element on the
    page, or None if the rule's banner isn't actually present here."""
    for key, value in data.items():
        if key == "$schema" or not isinstance(value, dict):
            continue
        for detector in value.get("detectors", []):
            # ~19/205 vendored rules store presentMatcher as a single object
            # instead of a list (e.g. chandago, cookieLab, EvidonIFrame) —
            # normalize so both shapes iterate as matcher dicts.
            present_matcher = detector.get("presentMatcher", [])
            matchers = present_matcher if isinstance(present_matcher, list) else [present_matcher]
            for matcher in matchers:
                selector = matcher.get("target", {}).get("selector")
                if not selector:
                    continue
                try:
                    el = await page.query_selector(selector)
                except Exception as exc:
                    logger.debug("_matches_present_detector: selector %r failed: %s", selector, exc)
                    continue
                if el:
                    return key, selector
    return None


async def _detect_cookie_wall(page) -> bool:
    """Passive-only check — never accepts or rejects anything, just reads
    computed style. Called by apply_consent_rules only once a rule's banner
    is already confirmed present on the page (that's the caller's job, not
    this function's): a cookie wall is the *combination* of "a consent
    banner is showing" AND "the main content is blocked from scrolling/
    interaction" (`overflow: hidden` on <body>/<html>, the classic way a
    banner-behind-a-modal locks the page) — deliberately a much stronger,
    separate signal than `reject_option_missing` (which only means the
    banner itself has no reject button, regardless of whether the rest of
    the page is still usable underneath it)."""
    try:
        # page.evaluate() takes no timeout of its own (see the module-level
        # CONSENT_TIMEOUT_SECONDS comment above) — a stalled page can hang
        # this one call forever and burn the whole per-page consent budget
        # on it alone. 5s is comfortably under CONSENT_TIMEOUT_SECONDS so a
        # timeout here still leaves headroom for the rest of consent
        # handling on the same page.
        return await asyncio.wait_for(
            page.evaluate(
                "() => getComputedStyle(document.body).overflow === 'hidden' "
                "|| getComputedStyle(document.documentElement).overflow === 'hidden'"
            ),
            timeout=5,
        )
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary (incl. asyncio.TimeoutError)
        logger.debug("_detect_cookie_wall: check failed: %s", exc)
        return False


async def apply_consent_rules(page, rules_dir: str = DEFAULT_CONSENT_RULES_DIR) -> dict:
    """Thin timeout wrapper around `_apply_consent_rules_impl` — see
    CONSENT_TIMEOUT_SECONDS above for why. Falls back to the same default
    "nothing found" result the impl itself returns on any other failure."""
    try:
        return await asyncio.wait_for(
            _apply_consent_rules_impl(page, rules_dir), timeout=CONSENT_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        logger.warning("apply_consent_rules: timed out after %ss", CONSENT_TIMEOUT_SECONDS)
        return {
            "accept_style": None, "reject_style": None,
            "reject_option_missing": False, "cookie_wall_detected": False,
            "banner_screenshot": None,
        }


async def _apply_consent_rules_impl(page, rules_dir: str = DEFAULT_CONSENT_RULES_DIR) -> dict:
    """Best-effort cookie-banner rejection using vendored Consent-O-Matic rules,
    plus (for whichever rule's banner is actually detected present on the
    page) capturing real accept/reject button styles for button-asymmetry
    detection and flagging a structurally-missing reject option.

    Loads every JSON rule file in `rules_dir`, skips any whose `presentMatcher`
    doesn't match this page, and for the remainder extracts click targets that
    look like a "reject/decline" action, clicking the first visible one found.
    Accept-shaped targets are located and their style read, but never clicked
    (clicking would grant consent). Never raises: a non-matching site or
    malformed rule file is logged and skipped so it can never break a crawl.

    Returns a dict with `accept_style`/`reject_style` (each a style dict from
    `_read_style`, or None if not found), `reject_option_missing` (True
    only when a rule's banner was confirmed present but neither a reject
    click target nor a consent-toggle structure was found for it), and
    `cookie_wall_detected` (True when a banner was confirmed present AND
    the page additionally blocks scrolling/interacting with the main
    content — a distinct, stronger signal than a merely-missing reject
    option, see `_detect_cookie_wall`).
    """
    result = {
        "accept_style": None, "reject_style": None,
        "reject_option_missing": False, "cookie_wall_detected": False,
        "banner_screenshot": None,
    }
    try:
        rules_path = pathlib.Path(rules_dir)
        if not rules_path.is_dir():
            logger.warning("apply_consent_rules: rules dir not found: %s", rules_dir)
            return result

        clicked_reject = False
        for rule_file in sorted(rules_path.glob("*.json")):
            try:
                data = json.loads(rule_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("apply_consent_rules: skipping unparseable %s: %s", rule_file, exc)
                continue

            present = await _matches_present_detector(page, data)
            if present is None:
                continue
            _, present_selector = present
            if not await _banner_has_cookie_context(page, present_selector):
                logger.debug("apply_consent_rules: skipping non-consent-looking banner %r", present_selector)
                continue

            if result["banner_screenshot"] is None:
                # Evidence of what the banner actually looked like, taken
                # before any reject click below removes it from the page —
                # the click only fires later in this same loop iteration.
                try:
                    result["banner_screenshot"] = await page.screenshot()
                except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
                    logger.debug("apply_consent_rules: banner screenshot failed: %s", exc)

            if not result["cookie_wall_detected"]:
                result["cookie_wall_detected"] = await _detect_cookie_wall(page)

            found_reject_candidate = False
            for action in _iter_click_candidates(data):
                hint = action.get("target", {}).get("textFilter") or action.get("type")
                selector = _scoped_selector(action)
                if not selector:
                    continue

                if _looks_like_reject(hint):
                    found_reject_candidate = True
                    if clicked_reject:
                        continue
                    try:
                        el = await page.query_selector(selector)
                        if el and await el.is_visible():
                            result["reject_style"] = await _read_style(page, selector)
                            await el.click(timeout=1000)
                            logger.info(
                                "apply_consent_rules: clicked %r from %s", selector, rule_file.name
                            )
                            clicked_reject = True
                    except Exception as exc:
                        logger.debug("apply_consent_rules: selector %r failed: %s", selector, exc)
                elif result["accept_style"] is None and _looks_like_accept(hint):
                    try:
                        el = await page.query_selector(selector)
                        if el and await el.is_visible():
                            result["accept_style"] = await _read_style(page, selector)
                    except Exception as exc:
                        logger.debug("apply_consent_rules: selector %r failed: %s", selector, exc)

            if not found_reject_candidate:
                found_reject_candidate = await _has_visible_keyword_control(
                    page, present_selector, _REJECT_KEYWORDS
                )

            if not found_reject_candidate and not _has_consent_toggle(data):
                result["reject_option_missing"] = True

        if not clicked_reject:
            # No vendored rule matched this site's banner at all (or matched
            # but had no reject target) — the common case for custom/self-
            # hosted CMPs not in the 206-file vendor set, and previously
            # meant the banner silently stayed on the page (and in every
            # evidence screenshot) with no error. Generic fallback: click
            # the first visible element whose text looks like a reject
            # action, page-wide. ponytail: text-matching only, misses
            # icon-only reject buttons with no text — add a rule file for a
            # specific site if this still doesn't catch it.
            try:
                for el in await page.locator("button, a, [role=button], input[type=button], input[type=submit]").all():
                    try:
                        text = ((await el.inner_text(timeout=500)) or (await el.get_attribute("value") or "")).lower()
                    except Exception:
                        continue
                    if not any(kw in text for kw in _REJECT_KEYWORDS):
                        continue
                    if not await el.is_visible():
                        continue
                    await el.click(timeout=1000)
                    clicked_reject = True
                    result["reject_option_missing"] = False
                    logger.info("apply_consent_rules: clicked generic fallback reject %r", text.strip()[:50])
                    break
            except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
                logger.debug("apply_consent_rules: generic fallback click failed: %s", exc)

        return result
    except Exception as exc:  # pragma: no cover - defensive catch-all
        logger.warning("apply_consent_rules: best-effort pass failed: %s", exc)
        return result


async def _snapshot_page(page, skip_diff_sleep: bool = False, consent_result: dict | None = None, browser=None) -> dict:
    return await asyncio.wait_for(
        _snapshot_page_impl(page, skip_diff_sleep, consent_result, browser),
        timeout=SNAPSHOT_TIMEOUT_SECONDS,
    )


async def _snapshot_page_impl(page, skip_diff_sleep: bool, consent_result: dict | None, browser=None) -> dict:
    dom_before = await page.content()
    if not skip_diff_sleep:
        await asyncio.sleep(1.5)  # Dapde principle: catch script-driven DOM changes
    dom_after = await page.content()

    # full_page=True: without it, page.screenshot() only captures the
    # viewport (Playwright's default 1280x720) — but
    # _capture_text_element_boxes below reports getBoundingClientRect()
    # positions for every leaf text element on the WHOLE page, including
    # ones below the fold. A viewport-only screenshot made every
    # highlight_quote_in_screenshot marker for a below-fold quote land
    # outside the captured image: silently invisible, no error, no crash.
    screenshot = await page.screenshot(full_page=True)

    consent_result = consent_result or {}
    accept_style = consent_result.get("accept_style")
    reject_style = consent_result.get("reject_style")
    button_styles = None
    if accept_style and reject_style:
        button_styles = {"accept": accept_style, "reject": reject_style}
    else:
        # Fallback for sites apply_consent_rules found no rule-resolved pair
        # for (including the local test fixture, which genuinely uses these
        # literal IDs).
        accept_style = await _read_style(page, "#accept")
        reject_style = await _read_style(page, "#reject")
        if accept_style and reject_style:
            button_styles = {"accept": accept_style, "reject": reject_style}

    try:
        contrast_findings = await find_low_contrast_legal_text(page)
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
        logger.debug("_snapshot_page: find_low_contrast_legal_text failed: %s", exc)
        contrast_findings = []

    # Structural countdown candidates need the live page to verify (clock
    # fast-forward + reload) — done here, not in the DOM-string-only
    # analysis pipeline, same reason contrast_findings is computed here
    # instead of there (page.content()/screenshot() are already captured
    # above, so the reload verify_countdown_reset does internally can't
    # invalidate anything this function still needs).
    countdown_findings = find_countdown_elements(dom_after)
    try:
        countdown_findings = await verify_countdown_reset(page, countdown_findings, browser=browser)
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
        logger.debug("_snapshot_page: verify_countdown_reset failed: %s", exc)

    text_boxes = await _capture_text_element_boxes(page)

    return {
        "dom_before": dom_before,
        "dom_after": dom_after,
        "screenshot": screenshot,
        "button_styles": button_styles,
        "contrast_findings": contrast_findings,
        "countdown_findings": countdown_findings,
        "reject_option_missing": consent_result.get("reject_option_missing", False),
        "cookie_wall_detected": consent_result.get("cookie_wall_detected", False),
        "banner_screenshot": consent_result.get("banner_screenshot"),
        "text_boxes": text_boxes,
    }


# Words that indicate a countdown correctly expired rather than restarting.
_EXPIRY_WORDS = ("abgelaufen", "beendet", "expired", "vorbei")


def _looks_reset(text_before: str, text_after: str) -> bool:
    """Heuristic for 'did this countdown silently restart instead of
    expiring': after fast-forwarding, does the text still contain a
    two-digit-or-more number (a fresh mm:ss/hh:mm-ish value) without any
    expiry wording? ponytail: digit-magnitude + keyword check, not a full
    countdown-format parser — covers common "X Min/Std" phrasings, not
    every one. Revisit if real scans show it missing/false-flagging often.
    """
    after_lower = text_after.lower()
    if any(word in after_lower for word in _EXPIRY_WORDS):
        return False
    numbers_after = re.findall(r"\d{2,}", text_after)
    return bool(numbers_after)


_TIMER_VALUE_RE = re.compile(r'(?:(\d{1,2}):)?(\d{1,2}):(\d{2})')


def _parse_timer_seconds(text: str) -> int | None:
    """Extracts MM:SS or HH:MM:SS from a countdown's text into seconds, for
    numeric before/after comparison. None if no timer-shaped substring is found."""
    match = _TIMER_VALUE_RE.search(text)
    if not match:
        return None
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


async def _verify_cross_session_countdown(page, browser, selector: str, text_a: str, finding: dict) -> None:
    """Opens a second, completely isolated browser context (fresh cookies/
    storage, no shared clock) and re-visits the same URL — a countdown
    genuinely tied to a fixed global deadline shows the same remaining time
    to any visitor at the same real moment regardless of when their session
    started; a countdown computed relative to *this visitor's own page load*
    shows that same starting value to every fresh visitor, forever — the
    classic Fake-Urgency tell ("nur noch 10 Minuten", jedes Mal). Best-effort,
    never raises. ponytail: ±2s tolerance for render/network jitter between
    the two loads, and only compares the raw parsed seconds value, not a
    general fuzzy-text comparison."""
    seconds_a = _parse_timer_seconds(text_a)
    if seconds_a is None:
        return
    try:
        context_b = await browser.new_context()
        page_b = await context_b.new_page()
        await page_b.goto(page.url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        text_b = await page_b.locator(selector).first.inner_text(timeout=2000)
        await context_b.close()
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
        logger.debug("verify_countdown_reset: cross-session check failed: %s", exc)
        return

    seconds_b = _parse_timer_seconds(text_b)
    if seconds_b is not None and abs(seconds_a - seconds_b) <= 2:
        finding["confidence_score"] = round(min(finding["confidence_score"] + 0.25, 1.0), 2)
        finding["evidence_data"]["cross_session_match"] = (
            "Neuer, isolierter Besucher (frischer Browser-Kontext) sieht denselben "
            f"Countdown-Startwert ({text_b.strip()}) — Timer wirkt nicht an eine echte, "
            "globale Deadline gekoppelt."
        )


async def verify_countdown_reset(page, findings: list[dict], browser=None) -> list[dict]:
    """Behavioral verification for Fake-Urgency countdown findings: jump
    the page's virtual clock forward and check whether the countdown text
    still shows a fresh value instead of expiring — the "Countdown startet
    nach Ablauf neu" test from the legal research sheet, via Playwright's
    Clock API instead of really waiting. Also documents the resulting page
    change as a text diff, and (if `browser` is given) checks whether a
    brand-new, isolated session sees the same countdown value (see
    _verify_cross_session_countdown).

    Only a candidate confirmed to actually reset is a real finding — merely
    matching a countdown-ish CSS class/id (find_countdown_elements) isn't
    evidence of manipulation on its own (e.g. a real, correctly-expiring
    sale timer, or a static "nur noch 2 auf Lager" element that happens to
    carry a "countdown-timer" class). Returns a NEW list containing only
    the confirmed-reset findings (plus any findings that weren't countdown
    candidates in the first place, passed through unchanged) — the caller
    must use the returned list, not the one passed in. best-effort, never
    raises (an unverifiable candidate is dropped, same as a confirmed-legit
    one — no reset proven, no finding reported).
    ponytail: only catches client-computed countdowns (JS Date/timers) —
    a countdown whose remaining value is re-fetched from the server on
    each load isn't fooled by a client-side clock mock. Real limitation,
    not a bug.
    """
    countdown_findings = [
        f
        for f in findings
        if f.get("pattern_type") == "Fake Urgency" and f.get("evidence_data", {}).get("selector")
    ]
    other_findings = [f for f in findings if f not in countdown_findings]
    if not countdown_findings:
        return findings

    confirmed: list[dict] = []
    for finding in countdown_findings:
        selector = finding["evidence_data"]["selector"]
        try:
            # Install the clock, then reload: a setInterval already running
            # from the original page load was created against the real
            # clock and won't be affected by fast_forward — only timers
            # created *after* install are clock-owned. Reloading makes the
            # countdown script re-register its timer under the mock.
            await page.clock.install()
            await page.reload()
            locator = page.locator(selector).first
            text_before = await locator.inner_text(timeout=2000)
            body_before = await page.inner_text("body")
            await page.clock.fast_forward("06:00:00")
            text_after = await locator.inner_text(timeout=2000)
            body_after = await page.inner_text("body")
        except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
            logger.debug("verify_countdown_reset: unverifiable, dropping %s: %s", selector, exc)
            continue

        if not _looks_reset(text_before, text_after):
            logger.debug("verify_countdown_reset: %s correctly expires, dropping", selector)
            continue

        finding["confidence_score"] = round(min(finding["confidence_score"] + 0.25, 1.0), 2)
        finding["evidence_data"]["clock_verified"] = (
            "Zeit künstlich vorgespult (+6h) — Countdown zeigt weiterhin einen "
            "frischen Restwert statt abgelaufen zu sein."
        )
        # Cross-session corroboration only makes sense once the
        # fast-forward check already flagged a reset — two sessions
        # started milliseconds apart (no way to wait real hours during a
        # live scan) would show near-identical remaining time for a
        # genuine deadline too, so on its own this comparison can't
        # discriminate real vs. fake; it only adds evidence once the
        # timer is already suspected of resetting per-visitor.
        if browser is not None:
            await _verify_cross_session_countdown(page, browser, selector, text_before, finding)

        diff_lines = [
            line for line in difflib.unified_diff(
                body_before.splitlines(), body_after.splitlines(), lineterm=""
            )
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ]
        if diff_lines:
            finding["evidence_data"]["time_diff_sample"] = "\n".join(diff_lines[:10])

        confirmed.append(finding)

    return other_findings + confirmed


_CAPTCHA_MARKERS = (
    # Widget markup / actual challenge endpoints only — NOT a bare "recaptcha"/
    # "hcaptcha" substring, which also matches the loader script platforms like
    # Weebly/Wix preload on every page for a dormant contact-form widget (see
    # be-gipsy.de false positive: `_W.recaptchaUrl = ".../recaptcha/api.js"`
    # present with no visible captcha anywhere on the page).
    "g-recaptcha", "recaptcha/api2/anchor", "h-captcha", "cf-turnstile",
    "challenges.cloudflare.com",
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

    async with httpx.AsyncClient() as robots_client:
        robots_parser = await fetch_robots_parser(url, robots_client)
    if not robots_parser.can_fetch(USER_AGENT, url):
        await context.close()
        raise RobotsDisallowedError(url)

    page = await context.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)

    consent_result = await apply_consent_rules(page, consent_rules_dir)

    snapshot = await _snapshot_page(page, consent_result=consent_result, browser=browser)

    await page.close()
    await context.close()  # flushes the HAR file to disk

    return {**snapshot, "har_path": har_path}


async def _capture_text_element_boxes(page) -> list[dict]:
    """Leaf-Text-Elemente mit Position — Rohmaterial, um ein Fund-Zitat
    später (nach Schluss des Browsers) im Screenshot einzukreisen, siehe
    app/analysis/screenshot_annotate.py. Reine Datensammlung, keine
    Klassifikation — die passiert weiterhin erst in app/analysis/* nach
    dem Crawl, die Trennung Crawler/Analyse bleibt gewahrt."""
    try:
        return await page.eval_on_selector_all(
            "body *",
            """els => els
                .filter(el => el.children.length === 0 && el.textContent.trim().length > 0)
                .map(el => {
                    const r = el.getBoundingClientRect();
                    return {
                        text: el.textContent.trim().slice(0, 300),
                        x: r.x, y: r.y, width: r.width, height: r.height,
                    };
                })
                .filter(b => b.width > 0 && b.height > 0)""",
        )
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
        logger.debug("_capture_text_element_boxes failed: %s", exc)
        return []


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
                    const rect = el.getBoundingClientRect();
                    const parseRgb = (s) => {
                        const m = s.match(/[\\d.]+/g);
                        if (m && m.length >= 4 && Number(m[3]) === 0) {
                            return [255, 255, 255];
                        }
                        return m ? [parseInt(m[0]), parseInt(m[1]), parseInt(m[2])] : [255, 255, 255];
                    };
                    return {
                        text: el.textContent.trim().slice(0, 200),
                        selector: el.tagName.toLowerCase() + (el.id ? '#' + el.id : ''),
                        font_size: parseFloat(style.fontSize),
                        color: parseRgb(style.color),
                        bg_color: parseRgb(style.backgroundColor),
                        visible: (
                            rect.width > 0 &&
                            rect.height > 0 &&
                            style.display !== 'none' &&
                            style.visibility !== 'hidden' &&
                            Number(style.opacity) !== 0
                        ),
                    };
                })
                .filter(el => el.visible)""",
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
        if not _looks_like_low_contrast_legal_text(e["text"]):
            continue
        font_small = bool(e["font_size"] and e["font_size"] < median_font * 0.75)
        low_relative_contrast = c < median_contrast * 0.6
        low_absolute_contrast = c < 3.0
        camouflaged = (
            low_relative_contrast and c < 4.5
        ) or (
            font_small and low_absolute_contrast and c < median_contrast * 0.9
        )
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
