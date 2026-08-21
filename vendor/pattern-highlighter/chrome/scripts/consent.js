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
const REJECT_KEYWORDS = [
    "reject", "decline", "ablehnen", "opt out", "opt-out",
    "only necessary", "nur notwendig", "alle ablehnen",
];
const ACCEPT_KEYWORDS = [
    "accept all", "agree", "akzeptieren", "zustimmen",
    "alle akzeptieren", "allow all", "einverstanden",
];
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
            for (const matcher of detector.presentMatcher || []) {
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
    for (const el of candidates) {
        if (el.textContent.includes(scoped.textFilter)) return el;
    }
    return null;
}

/**
 * Reads an element's box size + resolved background/text color. Synchronous
 * port of app/crawler.py's _read_style (no eval_on_selector round trip
 * needed — this already runs in-page).
 */
export function readStyle(el) {
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const parseRgb = (s) => {
        const m = s.match(/\d+/g);
        return m ? [parseInt(m[0]), parseInt(m[1]), parseInt(m[2])] : [0, 0, 0];
    };
    return {
        width: rect.width,
        height: rect.height,
        bgColor: parseRgb(style.backgroundColor),
        textColor: parseRgb(style.color),
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
    };

    for (const data of rules) {
        const present = matchesPresentDetector(data);
        if (!present) continue;
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

        if (!foundRejectCandidate && !hasConsentToggle(data)) {
            result.rejectOptionMissing = true;
        }
        break;
    }

    return result;
}
