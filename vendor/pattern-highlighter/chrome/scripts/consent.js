/**
 * Cookie-banner dark-pattern detection: real accept/reject button asymmetry
 * and missing-reject-option, ported from Kali's Python crawler
 * (app/crawler.py's apply_consent_rules + app/analysis/visual.py's
 * compute_button_asymmetry, commit 17e9c80). Unlike that Playwright-driven
 * crawler, this runs on a real user's live page — it NEVER clicks anything,
 * it only resolves elements and reads their computed style.
 */

const brw = chrome;

// ponytail: keyword matching only resolves a concrete accept/reject
// selector on a small minority of the 204 vendored rules (reject: 2/204,
// accept: ~10/204) — most rules model consent via per-category checkbox
// toggles + a "save" click ("type": "consent" nodes) rather than a single
// button. Same recall ceiling as the Python port; upgrade path there
// applies here too (drive the toggle+save flow instead of only matching a
// single click target) if recall on real pages turns out to matter more.
//
// Real bug reports from live pages (mistakes/fehlenden reject button nicht
// erkannt[ 2].png): banners whose reject control says "Nicht akzeptieren"
// or "Nur notwendige Cookies" were missed by both the rule-derived and the
// keyword-fallback path. The lists below now cover the common German
// inflections and negated-accept phrasings; note that
// REJECT is always checked BEFORE ACCEPT in checkCookieBanner(), so a
// control reading "nicht akzeptieren" can never be claimed by the
// "akzeptieren" accept keyword.
const REJECT_KEYWORDS = [
    "reject", "decline", "deny", "ablehnen", "opt out", "opt-out",
    "only necessary", "nur notwendig", "nur notwendige",
    "nur die notwendigen", "nur essenzielle", "nur essentielle",
    "essential only", "necessary only", "nicht akzeptieren",
    "nicht zustimmen", "continue without accepting",
    "fortfahren ohne", "weiter ohne zu", "ohne einwilligung fortfahren",
];
const ACCEPT_KEYWORDS = [
    "accept all", "agree", "akzeptieren", "zustimmen",
    "alle akzeptieren", "allow all", "alle zulassen", "einverstanden",
];
const COOKIE_CONTEXT_KEYWORDS = [
    "cookie", "cookies", "consent", "privacy", "datenschutz",
    "einwilligung", "zustimmung", "akzeptieren", "ablehnen",
    "accept all", "reject all",
];
const COOKIE_CONTROL_SELECTOR = "button, a, [role=button], input[type=button], input[type=submit]";
const GENERIC_TAG_SELECTORS = new Set(["a", "button", "div", "span", "input", "section", "p"]);

function matchesKeyword(hint, keywords) {
    if (!hint) return false;
    const texts = Array.isArray(hint) ? hint : [hint];
    const joined = texts.map(String).join(" ").toLowerCase();
    return keywords.some((kw) => joined.includes(kw));
}

export function looksLikeReject(hint) {
    return matchesKeyword(hint, REJECT_KEYWORDS);
}

export function looksLikeAccept(hint) {
    return matchesKeyword(hint, ACCEPT_KEYWORDS);
}

export function isGenericSelector(selector) {
    return GENERIC_TAG_SELECTORS.has(selector.trim().toLowerCase());
}

function bannerHasCookieContext(selector) {
    let el;
    try {
        el = document.querySelector(selector);
    } catch (e) {
        return false;
    }
    if (!el) return false;
    const text = (el.textContent || "").toLowerCase();
    return COOKIE_CONTEXT_KEYWORDS.some((kw) => text.includes(kw));
}

/**
 * Real visibility check that works for position:fixed elements too.
 * The old `el.offsetParent !== null` test was the root cause of the missing-
 * reject false negatives (mistakes/fehlenden reject button nicht erkannt[ 2].png):
 * offsetParent is ALWAYS null for fixed-position elements, and cookie banners
 * are almost always position:fixed — so visible reject controls inside them
 * were silently skipped as invisible.
 */
export function elementIsVisible(el) {
    if (!el || typeof el.getBoundingClientRect !== "function") return false;
    const rects = el.getClientRects();
    if (!rects || rects.length === 0) {
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 && rect.height <= 0) return false;
    }
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    if (parseFloat(style.opacity) === 0) return false;
    return true;
}

function findVisibleKeywordControl(containerSelector, keywords) {
    let container;
    try {
        container = document.querySelector(containerSelector);
    } catch (e) {
        return null;
    }
    if (container) {
        const found = findVisibleKeywordControlWithin(container, keywords);
        if (found) return found;
    }
    // Fallback beyond the presentMatcher container: some sites render their
    // reject control outside the element matched by the vendored rule (e.g.
    // the rule matches an inner text block, while the buttons live in a
    // sibling of the banner wrapper). Keyword phrases like "Alle ablehnen"/
    // "Nicht akzeptieren" are specific enough that a document-wide sweep
    // among clickable controls is safe in practice.
    return findVisibleKeywordControlWithin(document.body, keywords);
}

// Minimum share of an element's own text a matched keyword must make up.
// Guards against a keyword being buried in a longer sentence/link — e.g. a
// per-vendor fine-print opt-out ("für Utiq jetzt ablehnen", a single
// third-party opt-out link deep in the legal text, not a general "reject
// all" control) matches "ablehnen" as a bare substring but is nowhere near
// as prominent as "Alle akzeptieren" (real bug: mistakes/fehlenden reject
// button nicht erkannt[ 2].png — bild.de's Sourcepoint banner has exactly
// such a link, which made the fallback sweep wrongly conclude a reject
// option exists). Real reject/accept controls are short standalone labels
// where the keyword IS essentially the whole text.
const KEYWORD_STANDALONE_RATIO = 0.5;

function findVisibleKeywordControlWithin(rootEl, keywords) {
    if (!rootEl) return null;
    for (const el of rootEl.querySelectorAll(COOKIE_CONTROL_SELECTOR)) {
        const text = ((el.textContent || el.value || "") + "").toLowerCase().trim();
        if (!text) continue;
        const matched = keywords.some((kw) => text.includes(kw) && kw.length / text.length >= KEYWORD_STANDALONE_RATIO);
        if (matched && elementIsVisible(el)) {
            return el;
        }
    }
    return null;
}

/**
 * Walks a Consent-O-Matic rule's action tree, yielding every action dict
 * that looks like a clickable target (action.type in "click"/"reject" with
 * a target.selector). Port of app/crawler.py's _iter_click_candidates.
 */
export function* iterClickCandidates(node) {
    if (node && typeof node === "object" && !Array.isArray(node)) {
        const action = node.action || node;
        const aType = action && typeof action === "object" ? action.type : null;
        if ((aType === "click" || aType === "reject") && action.target && action.target.selector) {
            yield action;
        }
        for (const value of Object.values(node)) {
            yield* iterClickCandidates(value);
        }
    } else if (Array.isArray(node)) {
        for (const item of node) {
            yield* iterClickCandidates(item);
        }
    }
}

/**
 * Structural signal that a rule models consent via per-category checkbox
 * toggles + a save action, rather than a single reject click. Port of
 * app/crawler.py's _has_consent_toggle.
 */
export function hasConsentToggle(node) {
    if (node && typeof node === "object" && !Array.isArray(node)) {
        if (node.type === "consent") return true;
        return Object.values(node).some(hasConsentToggle);
    } else if (Array.isArray(node)) {
        return node.some(hasConsentToggle);
    }
    return false;
}

/**
 * Returns {key, selector} for the first of this rule's presentMatcher
 * selectors that currently matches an element on the page, or null.
 * Port of app/crawler.py's _matches_present_detector.
 */
export function matchesPresentDetector(data) {
    for (const [key, value] of Object.entries(data)) {
        if (key === "$schema" || typeof value !== "object" || value === null) continue;
        for (const detector of value.detectors || []) {
            // ~19/205 vendored rules store presentMatcher as a single object
            // instead of an array (e.g. chandago, cookieLab, EvidonIFrame) —
            // normalize so both shapes iterate as matcher objects. Mirrors
            // the same fix in app/crawler.py's _matches_present_detector.
            const presentMatcher = detector.presentMatcher;
            const matchers = Array.isArray(presentMatcher) ? presentMatcher : (presentMatcher ? [presentMatcher] : []);
            for (const matcher of matchers) {
                const selector = matcher.target && matcher.target.selector;
                if (!selector) continue;
                try {
                    if (document.querySelector(selector)) {
                        return { key, selector };
                    }
                } catch (e) {
                    // Invalid selector for this DOM — skip, mirrors Python's try/except.
                }
            }
        }
    }
    return null;
}

/**
 * Builds a {base, textFilter} descriptor for an action's click target,
 * narrowed by the rule's parent/childFilter when present (native CSS
 * :has(), no polyfill needed). Port of app/crawler.py's _scoped_selector —
 * EXCEPT its textFilter handling: Python appends Playwright-only
 * :has-text("..."), which document.querySelectorAll doesn't understand.
 * Here textFilter is returned separately and applied manually by
 * resolveSelector() below — this is a real reimplementation, not a syntax
 * port.
 */
export function scopedSelector(action) {
    const target = action.target || {};
    const selector = target.selector;
    if (!selector) return null;

    const parent = action.parent || {};
    const parentSelector = parent.selector;
    let base;
    if (!parentSelector) {
        base = isGenericSelector(selector) ? null : selector;
    } else {
        const childSelector = parent.childFilter && parent.childFilter.target
            ? parent.childFilter.target.selector
            : null;
        const scopedParent = childSelector ? `${parentSelector}:has(${childSelector})` : parentSelector;
        base = `${scopedParent} ${selector}`;
    }
    if (base === null) return null;

    const textFilterRaw = target.textFilter;
    const textFilter = Array.isArray(textFilterRaw) ? textFilterRaw[0] : (textFilterRaw || null);
    return { base, textFilter };
}

/**
 * Resolves a scopedSelector() descriptor to a single Element or null.
 * Manual reimplementation of Playwright's :has-text() (case-sensitive
 * substring match, first match wins — matches Playwright's default
 * behavior).
 */
export function resolveSelector(scoped) {
    let candidates;
    try {
        candidates = document.querySelectorAll(scoped.base);
    } catch (e) {
        return null;
    }
    if (!scoped.textFilter) return candidates[0] || null;
    // Case-insensitive substring, mirroring Playwright's :has-text() which the
    // Python crawler relies on — resolveSelector() previously used a case-
    // sensitive includes() and silently diverged from it (a rule textFilter
    // "Ablehnen" no longer resolved against an "ablehnen" button).
    const needle = scoped.textFilter.toLowerCase();
    for (const el of candidates) {
        if (el.textContent.toLowerCase().includes(needle)) return el;
    }
    return null;
}

/**
 * Parses any CSS color string into [r, g, b, a]. Unlike the previous regex
 * this keeps the ALPHA channel: rgba(0, 0, 0, 0) (fully transparent — the
 * default background of most buttons) must NOT collapse to opaque black,
 * which previously produced arbitrary contrast numbers and masked real
 * dimming asymmetries (mistakes/verdunklung von auswahl speicher nicht
 * erkannt.png).
 */
function parseRgba(s) {
    const m = String(s || "").match(/[\d.]+/g);
    if (!m || m.length < 3) return [0, 0, 0, 1];
    const a = m.length > 3 ? parseFloat(m[3]) : 1;
    return [parseInt(m[0]), parseInt(m[1]), parseInt(m[2]), Number.isFinite(a) ? a : 1];
}

function clamp01(v) {
    const n = parseFloat(v);
    return Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : 1;
}

/**
 * Effective on-screen background color: composites each ancestor's
 * backgroundColor (+ its own opacity) over white, bottom-up. A button dimmed
 * via `opacity: 0.6` or a translucent overlay therefore yields a genuinely
 * washed-out color instead of the raw, undimmed one.
 */
export function effectiveBackgroundColor(el, maxDepth = 12) {
    let bg = [255, 255, 255];
    let node = el;
    for (let depth = 0; node && node.nodeType === 1 && depth < maxDepth; depth++, node = node.parentElement) {
        const style = getComputedStyle(node);
        const c = parseRgba(style.backgroundColor);
        const a = clamp01(c[3]) * clamp01(style.opacity);
        if (a > 0) {
            bg = [c[0] * a + bg[0] * (1 - a), c[1] * a + bg[1] * (1 - a), c[2] * a + bg[2] * (1 - a)];
        }
        if (a >= 0.995) break;
    }
    return bg.map(Math.round);
}

/**
 * Effective on-screen text color: the element's resolved color composited
 * over the effective background, with every ancestor's opacity applied
 * (ancestor opacity dims descendants too). This is what makes "Verdunklung"
 * (dimmed secondary actions like "Auswahl speichern") measurable at all:
 * raw getComputedStyle().color is unchanged by opacity.
 */
export function effectiveTextColor(el, maxDepth = 12) {
    const fg = parseRgba(getComputedStyle(el).color);
    let opacityProduct = 1;
    let node = el;
    for (let depth = 0; node && node.nodeType === 1 && depth < maxDepth; depth++, node = node.parentElement) {
        opacityProduct *= clamp01(getComputedStyle(node).opacity);
    }
    const a = clamp01(fg[3]) * opacityProduct;
    const bg = effectiveBackgroundColor(el, maxDepth);
    return [
        Math.round(fg[0] * a + bg[0] * (1 - a)),
        Math.round(fg[1] * a + bg[1] * (1 - a)),
        Math.round(fg[2] * a + bg[2] * (1 - a)),
    ];
}

/**
 * Reads an element's box size + EFFECTIVE (opacity/alpha-composited)
 * background/text colors. Port of app/crawler.py's _read_style, upgraded so
 * visually dimmed secondary actions compare against the accept button the
 * way they actually render.
 */
export function readStyle(el) {
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    return {
        width: rect.width,
        height: rect.height,
        bgColor: effectiveBackgroundColor(el),
        textColor: effectiveTextColor(el),
    };
}

// Port of app/analysis/visual.py's thresholds/formula.
const SIZE_RATIO_THRESHOLD = 1.8;
const CONTRAST_DELTA_THRESHOLD = 4.0;

function relativeLuminance(rgb) {
    const channel = (c) => {
        c = c / 255;
        return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
}

export function contrastRatio(rgbA, rgbB) {
    const l1 = relativeLuminance(rgbA) + 0.05;
    const l2 = relativeLuminance(rgbB) + 0.05;
    return Math.max(l1, l2) / Math.min(l1, l2);
}

// ponytail: no numeric confidence score (unlike the Python version) — the
// popup UI has no field to display one; add one only if a future evidence
// view needs a ranked/graded display.
export function computeButtonAsymmetry(acceptStyle, rejectStyle) {
    const acceptArea = acceptStyle.width * acceptStyle.height;
    const rejectArea = rejectStyle.width * rejectStyle.height;
    const sizeRatio = rejectArea ? acceptArea / rejectArea : Infinity;
    const contrastDelta = Math.abs(
        contrastRatio(acceptStyle.bgColor, acceptStyle.textColor)
        - contrastRatio(rejectStyle.bgColor, rejectStyle.textColor)
    );
    const flagged = sizeRatio >= SIZE_RATIO_THRESHOLD || contrastDelta >= CONTRAST_DELTA_THRESHOLD;
    return { flagged, sizeRatio, contrastDelta };
}

let cachedRules = null;

async function loadRules() {
    if (cachedRules === null) {
        const url = brw.runtime.getURL("data/consent-rules.json");
        cachedRules = await (await fetch(url)).json();
    }
    return cachedRules;
}

/**
 * Orchestrator, port of app/crawler.py's apply_consent_rules — minus the
 * click. Resolves the accept/reject elements (if any) for whichever rule's
 * banner is confirmed present on the page, and flags a structurally-missing
 * reject option. NEVER clicks anything: this runs on a real user's live
 * page, unlike the Playwright crawler which owns a disposable one.
 *
 * Deliberate deviation from the Python version: stops after the first
 * present-confirmed rule instead of scanning all 204 files regardless —
 * a page normally shows only one banner at a time, and this avoids
 * rescanning everything on every MutationObserver re-fire.
 */
export async function checkCookieBanner() {
    const rules = await loadRules();
    const result = {
        acceptEl: null,
        rejectEl: null,
        rejectOptionMissing: false,
        presentVendorKey: null,
        presentSelector: null,
        genericBannerEl: null,
    };

    for (const data of rules) {
        const present = matchesPresentDetector(data);
        if (!present) continue;
        if (!bannerHasCookieContext(present.selector)) continue;
        result.presentVendorKey = present.key;
        result.presentSelector = present.selector;

        let foundRejectCandidate = false;
        for (const action of iterClickCandidates(data)) {
            const hint = (action.target && action.target.textFilter) || action.type;
            const scoped = scopedSelector(action);
            if (!scoped) continue;
            const el = resolveSelector(scoped);
            if (!el) continue;

            if (looksLikeReject(hint)) {
                foundRejectCandidate = true;
                if (!result.rejectEl) result.rejectEl = el;
            } else if (!result.acceptEl && looksLikeAccept(hint)) {
                result.acceptEl = el;
            }
        }

        if (!foundRejectCandidate) {
            const visibleReject = findVisibleKeywordControl(present.selector, REJECT_KEYWORDS);
            if (visibleReject) {
                foundRejectCandidate = true;
                if (!result.rejectEl) result.rejectEl = visibleReject;
            }
        }

        // No one-click reject-equivalent found → flag it, regardless of
        // whether the rule models consent via per-category toggles behind a
        // visible "Einstellungen"/settings affordance. A previous version
        // suppressed the flag whenever such a settings link was reachable,
        // reasoning "the user can still reject via there" — but needing to
        // open a settings panel and toggle things off, versus one click to
        // accept, IS the asymmetry this check exists to catch (real bug,
        // live-verified on bild.de's Sourcepoint banner: `hasConsentToggle`
        // is true and "Einstellungen" is visible, so the old logic silently
        // cleared the flag on exactly the banner from mistakes/fehlenden
        // reject button nicht erkannt[ 2].png). `hasConsentToggle` is no
        // longer consulted here.
        if (!foundRejectCandidate) {
            result.rejectOptionMissing = true;
        }
        break;
    }

    // No vendored rule's presentMatcher matched anything on this page — the
    // banner belongs to a CMP outside the ~206 vendored rules (real example:
    // businessinsider.de/bild.de's bespoke "Mit/Ohne Tracking und Cookies
    // nutzen" banner, mistakes/fehlenden reject button nicht erkannt[ 2].png).
    // Without this fallback such banners are silently treated as "fine" —
    // rejectOptionMissing stays false regardless of whether a reject option
    // truly exists, independent of every keyword/visibility fix above.
    if (!result.presentSelector) {
        const acceptEl = findVisibleKeywordControlWithin(document.body, ACCEPT_KEYWORDS);
        if (acceptEl) {
            const container = findGenericBannerContainer(acceptEl);
            if (container) {
                const rejectEl = findVisibleKeywordControlWithin(container, REJECT_KEYWORDS);
                if (!rejectEl) {
                    result.rejectOptionMissing = true;
                    result.genericBannerEl = container;
                }
            }
        }
    }

    return result;
}

function elementHasCookieContext(el) {
    const text = ((el && el.textContent) || "").toLowerCase();
    return COOKIE_CONTEXT_KEYWORDS.some((kw) => text.includes(kw));
}

/**
 * Structural signal that a container actually IS a banner/modal, not just
 * some ancestor that happens to contain cookie-related text somewhere (e.g.
 * a footer with a "Privacy Policy" link sitting a few levels above an
 * unrelated button). Checked in addition to elementHasCookieContext() in
 * findGenericBannerContainer() below — false-positive guard for the
 * render.com "New" button class of bug (a keyword match alone, without this,
 * accepted any ancestor whose text happened to mention "privacy").
 */
function looksLikeBannerContainer(el) {
    if (!el) return false;
    const style = getComputedStyle(el);
    if (style && (style.position === "fixed" || style.position === "sticky")) return true;
    if (typeof el.getAttribute === "function") {
        const role = (el.getAttribute("role") || "").toLowerCase();
        if (role === "dialog" || el.getAttribute("aria-modal") === "true") return true;
    }
    const idClass = `${el.id || ""} ${el.className || ""}`.toLowerCase();
    return /\b(cookie|consent|gdpr|banner|notice)\b/.test(idClass);
}

/**
 * Bounded ancestor walk from a found accept button up to a container whose
 * text mentions cookies/consent/privacy — the generic-fallback equivalent of
 * a rule's presentMatcher-confirmed banner element. The keyword requirement
 * is the first false-positive guard: a stray "akzeptieren" button elsewhere
 * on the page (e.g. a newsletter form) won't have cookie-context text within
 * a few ancestor levels, so it never produces a container and never flags.
 * Among keyword-matching ancestors, one that also looksLikeBannerContainer()
 * is preferred (closer to a real banner structurally); if none qualifies,
 * falls back to the closest keyword match so recall on real-but-unstyled
 * banners doesn't regress.
 */
function findGenericBannerContainer(startEl, maxLevels = 6) {
    let node = startEl.parentElement;
    let fallback = null;
    for (let i = 0; i < maxLevels && node && node !== document.body; i++, node = node.parentElement) {
        if (elementHasCookieContext(node)) {
            if (looksLikeBannerContainer(node)) return node;
            if (!fallback) fallback = node;
        }
    }
    return fallback;
}
