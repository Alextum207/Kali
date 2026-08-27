/**
 * Sneaking-into-Basket detection (UWG §§ 5, 5a; Anhang zu § 3 Abs. 3 Nr. 2):
 * items are added to the cart that the user never explicitly chose.
 *
 * Detection idea (user-specified): everything the user has put into the cart
 * so far reduces to ONE number — the item count shown in the cart badge
 * (and incremented by every add-to-cart click this extension observes). If,
 * later on, the CHECKOUT page shows MORE items than that tracked baseline,
 * something was snuck into the basket → dark pattern flagged.
 *
 * Like scripts/consent.js, this module never clicks anything and operates on
 * the LIVE document; it runs imperatively from content.js's
 * patternHighlighting() loop rather than via per-node detection functions
 * (cross-page state can't be expressed as a single-node predicate).
 *
 * State lives in chrome.storage.local under one key per origin, so the
 * baseline survives navigation between product page and checkout within the
 * same shop while never leaking across shops.
 */

const brw = chrome;

/**
 * Matches an "add to cart" control label. Deliberately requires the explicit
 * basket noun (or an unambiguous buy-now phrasing): a bare "kaufen" would
 * also hit price-comparison buttons like "Günstiger kaufen" and inflate the
 * baseline.
 */
const ADD_TO_CART_RE = /\b(in den warenkorb|in den korb|in den einkaufswagen|add to (?:cart|basket|bag)|jetzt kaufen|buy now)\b/i;
/** Cart badge containers/badges usually carry one of these tokens. */
const CART_CONTEXT_RE = /(?:^|[^a-z])(warenkorb|einkaufswagen|cart|basket|minicart|mini-cart|shopping-?bag)(?:[^a-z]|$)/i;
const QTY_HINT_RE = /(qty|quantity|menge|anzahl|stück|stk)/i;
const PRICE_RE = /\d+[.,]\d{2}\s*(?:€|eur)|(?:€|eur)\s*\d+[.,]\d{2}/i;
const BASKET_STORAGE_PREFIX = "kali_basket_";
const MAX_PLAUSIBLE_COUNT = 99;
/** Debounce for add-to-cart increments: one click may fire several events. */
const INCREMENT_DEBOUNCE_MS = 1500;

let lastIncrementAt = 0;
let trackingInstalled = false;

/**
 * Parses a plausible cart item count out of free text ("Warenkorb, 3 Artikel",
 * "3", "Cart · 12 items"). Returns null when the text holds no integer in
 * [0, MAX_PLAUSIBLE_COUNT] — anything larger is treated as noise, not a count.
 */
export function parseCartCount(text) {
    if (typeof text !== "string") return null;
    const m = text.match(/\d+/);
    if (!m) return null;
    const n = parseInt(m[0], 10);
    if (!Number.isFinite(n) || n < 0 || n > MAX_PLAUSIBLE_COUNT) return null;
    return n;
}

function elementContextText(el) {
    const parts = [];
    for (const attr of el.attributes || []) {
        if (/^(id|class|data-testid|aria-label|title)$/i.test(attr.name)) {
            parts.push(attr.value);
        }
    }
    parts.push(el.id || "");
    if (typeof el.className === "string") parts.push(el.className);
    return parts.join(" ");
}

/**
 * Reads the item count from a cart badge element: prefers an aria-label of
 * the form "Warenkorb, 3 Artikel", falls back to short numeric-only badge
 * text (a bare "3"). Elements whose combined context text doesn't mention a
 * cart at all are ignored — a random "3" anywhere else is not a cart count.
 */
export function cartCountFromBadgeEl(el) {
    if (!el) return null;
    const context = `${elementContextText(el)} ${elementContextText(el.parentElement || {})}`;
    const ariaLabel = el.getAttribute ? el.getAttribute("aria-label") : null;
    const ownText = ((el.textContent || "") + "").trim();
    if (ariaLabel && parseCartCount(ariaLabel) !== null && /\d/.test(ownText)) {
        // aria-label carries the authoritative count next to numeric text.
        return parseCartCount(ariaLabel);
    }
    if (!CART_CONTEXT_RE.test(context)) return null;
    if (!/^\d{1,3}$/.test(ownText)) return null;
    return parseCartCount(ownText);
}

/**
 * Scans the page for the shop's cart-count badge and returns the highest
 * plausible count found (badges exist in header, mini-cart flyout, ...).
 */
export function scanCartBadgeCount(doc = document) {
    let best = null;
    for (const el of doc.querySelectorAll("[id], [class], [data-testid], [aria-label]")) {
        const count = cartCountFromBadgeEl(el);
        if (count !== null && (best === null || count > best)) best = count;
    }
    return best;
}

/** Pure helper: sums quantity input values, clamping each to [1, 99]. */
export function sumQuantityValues(values) {
    let total = null;
    for (const raw of values) {
        const n = parseInt(raw, 10);
        if (!Number.isFinite(n)) continue;
        const clamped = Math.min(MAX_PLAUSIBLE_COUNT, Math.max(1, n));
        total = (total === null ? 0 : total) + clamped;
    }
    return total === null || total > 9999 ? null : total;
}

/**
 * Total item count on the current checkout/cart page. Primary signal:
 * quantity inputs/selects (qty spinners, <select class="qty">). Fallback:
 * distinct line-item rows that contain both a price and a quantity hint.
 * Returns null when nothing on the page yields a count.
 */
export function countCheckoutItems(doc = document) {
    const qtyInputs = [];
    for (const el of doc.querySelectorAll(
        'input[type="number"], select[class*="qty" i], select[name*="quantity" i]'
    )) {
        if (!el.closest("nav, header")) {
            qtyInputs.push(el.value);
        }
    }
    const qtySum = sumQuantityValues(qtyInputs);
    if (qtySum !== null && qtySum > 0) return qtySum;

    // Fallback: count line-item-like rows with a price inside them.
    const rows = new Set();
    for (const el of doc.querySelectorAll(
        '[class*="line-item" i], [class*="cart-item" i], [class*="basket-item" i], [class*="order-item" i], li, tr'
    )) {
        if (rows.has(el)) continue;
        const text = el.textContent || "";
        if (PRICE_RE.test(text) && (QTY_HINT_RE.test(text) || el.querySelector("input, select, img"))) {
            rows.add(el);
        }
    }
    // Only direct matches count — drop any row that contains another counted
    // row (container vs. inner row double counting).
    const distinct = [...rows].filter((row) => ![...rows].some((other) => other !== row && row.contains(other)));
    return distinct.length > 0 ? distinct.length : null;
}

/** True when the URL looks like a checkout/order page. */
export function looksLikeCheckoutUrl(url) {
    return /(?:\/|^)(?:checkout(?:s)?(?:\/|$)|kasse(?:\/|$)?|bestellung|bestellabschluss|zahlung|bezahl|payment|placeorder|order-confirm)/i.test(String(url || ""));
}

/** True when the visible page reads like a checkout step even if the URL doesn't. */
export function looksLikeCheckoutPage(doc = document) {
    if (looksLikeCheckoutUrl(doc.location ? doc.location.href : "")) return true;
    const headings = [...doc.querySelectorAll("h1, h2, [class*='checkout' i]")]
        .map((h) => h.textContent || "")
        .join(" ");
    return /(?:zur kasse|ihre bestellung|deine bestellung|bestellübersicht|order summary|zahlungspflichtig bestellen|kostenpflichtig bestellen|kauf abschließen|complete your order)/i.test(headings);
}

/** True when the clicked element is (inside of) an add-to-cart control. */
export function isAddToCartControl(el) {
    let node = el;
    for (let depth = 0; node && node.nodeType === 1 && depth < 5; depth++, node = node.parentElement) {
        const tag = node.tagName;
        if (!(tag === "BUTTON" || tag === "A" || tag === "INPUT" ||
              (node.getAttribute && node.getAttribute("role") === "button"))) {
            continue;
        }
        const label = [
            node.textContent || "",
            node.getAttribute ? node.getAttribute("aria-label") || "" : "",
            node.getAttribute ? node.getAttribute("value") || "" : "",
            node.getAttribute ? node.getAttribute("title") || "" : "",
        ].join(" ");
        if (ADD_TO_CART_RE.test(label)) return true;
    }
    return false;
}

// ---- per-origin baseline state ------------------------------------------------

async function loadBaseline(origin) {
    try {
        const key = BASKET_STORAGE_PREFIX + origin;
        const stored = await brw.storage.local.get(key);
        return stored[key] || null;
    } catch (e) {
        return null;
    }
}

async function saveBaseline(origin, count) {
    try {
        await brw.storage.local.set({
            [BASKET_STORAGE_PREFIX + origin]: { count, ts: Date.now(), url: location.href },
        });
    } catch (e) {
        // Storage unavailable (e.g. tests) — detection degrades gracefully.
    }
}

function currentOrigin() {
    try {
        return location.origin || "unknown";
    } catch (e) {
        return "unknown";
    }
}

/**
 * Overwrites the per-origin baseline with whatever the cart badge currently
 * shows. The badge is the user's mental model of their basket, so it wins
 * over our click-increment estimate whenever both exist.
 */
export async function syncBasketFromBadge(doc = document) {
    const count = scanCartBadgeCount(doc);
    if (count === null) return null;
    await saveBaseline(currentOrigin(), count);
    return count;
}

/**
 * Registers (once per tab) a capture-phase click listener that increments
 * the per-origin baseline on every observed add-to-cart click.
 */
export async function installAddToCartTracking(doc = document) {
    if (trackingInstalled) return;
    trackingInstalled = true;
    doc.addEventListener("click", async (event) => {
        const target = event.target;
        if (!target || !isAddToCartControl(target)) return;
        const now = Date.now();
        if (now - lastIncrementAt < INCREMENT_DEBOUNCE_MS) return;
        lastIncrementAt = now;

        const origin = currentOrigin();
        const baseline = await loadBaseline(origin);
        const badgeNow = scanCartBadgeCount(doc);
        if (badgeNow !== null) {
            // Badge already reflects the click — trust it outright.
            await saveBaseline(origin, Math.max(badgeNow, (baseline ? baseline.count : 0)));
            return;
        }
        const previous = baseline ? baseline.count : 0;
        await saveBaseline(origin, Math.min(MAX_PLAUSIBLE_COUNT, previous + 1));
    }, true);
}

export function resetTrackingForTest() {
    trackingInstalled = false;
    lastIncrementAt = 0;
}

/**
 * Runs the comparison: on a checkout-looking page, compares the actual item
 * count against the tracked baseline. Returns
 * {detected, expectedCount, actualCount, tagEl} or null (no baseline / not a
 * checkout page / no countable items).
 */
export async function checkSneakingIntoBasket(doc = document) {
    if (!looksLikeCheckoutPage(doc)) return null;

    const baseline = await loadBaseline(currentOrigin());
    if (!baseline || typeof baseline.count !== "number") return null;

    const actualCount = countCheckoutItems(doc);
    if (actualCount === null) return null;

    const detected = actualCount > baseline.count;
    let tagEl = null;
    if (detected) {
        // Tag the order-summary/total block if present, otherwise the widest
        // sensible container: the checkout form itself.
        tagEl =
            doc.querySelector("[class*='summary' i], [class*='total' i], [class*='totals' i], [id*='summary' i]") ||
            doc.querySelector("form") ||
            doc.body;
    }

    return {
        detected,
        expectedCount: baseline.count,
        actualCount,
        tagEl,
        detail: `Warenkorb-Basis: ${baseline.count}, Checkout: ${actualCount}`,
    };
}
