import pathlib
import subprocess


EXTENSION_SCRIPTS = (
    pathlib.Path(__file__).parent.parent
    / "vendor"
    / "pattern-highlighter"
    / "chrome"
    / "scripts"
)

CONSENT_JS = EXTENSION_SCRIPTS / "consent.js"
SNEAK_BASKET_JS = EXTENSION_SCRIPTS / "sneak_basket.js"


def _run_node(script: str, *module_paths: pathlib.Path) -> None:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, *[str(p) for p in module_paths]],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_consent_reject_keywords_and_asymmetry_fixes():
    script = r"""
        import assert from "node:assert/strict";
        import { pathToFileURL } from "node:url";

        globalThis.chrome = { runtime: { getURL: (p) => p } };
        const consent = await import(pathToFileURL(process.argv[1]).href);

        // --- expanded reject/accept keywords (real bug reports:
        // mistakes/fehlenden reject button nicht erkannt[ 2].png) ---
        assert.equal(consent.looksLikeReject("Nicht akzeptieren"), true);
        assert.equal(consent.looksLikeReject("Nur notwendige Cookies"), true);
        assert.equal(consent.looksLikeReject("Deny all"), true);
        assert.equal(consent.looksLikeReject("Alle ablehnen"), true);
        assert.equal(consent.looksLikeAccept("Alle akzeptieren"), true);
        assert.equal(consent.looksLikeAccept("Alle zulassen"), true);

        // --- visibility check must accept position:fixed elements ---
        // (offsetParent is always null for them — the root cause of the
        // missing-reject false negatives on fixed cookie banners)
        const fakeEl = {
            getClientRects: () => [{}],
            getBoundingClientRect: () => ({ width: 120, height: 40 }),
        };
        globalThis.getComputedStyle = () => ({
            display: "block",
            visibility: "visible",
            opacity: "1",
        });
        assert.equal(consent.elementIsVisible(fakeEl), true);

        globalThis.getComputedStyle = () => ({
            display: "none",
            visibility: "visible",
            opacity: "1",
        });
        assert.equal(consent.elementIsVisible(fakeEl), false);
    """
    _run_node(script, CONSENT_JS)


def test_consent_opacity_and_alpha_aware_asymmetry():
    script = r"""
        import assert from "node:assert/strict";
        import { pathToFileURL } from "node:url";

        globalThis.chrome = { runtime: { getURL: (p) => p } };

        function fakeElement({ rect, style, parent = null }) {
            return {
                nodeType: 1,
                getBoundingClientRect: () => rect,
                parentElement: parent,
                __style: style,
            };
        }

        // getComputedStyle mock reading per-fake-element styles.
        globalThis.getComputedStyle = (el) => el.__style;

        const { readStyle, computeButtonAsymmetry, effectiveBackgroundColor, effectiveTextColor } =
            await import(pathToFileURL(process.argv[1]).href);

        const rect = { width: 200, height: 50 };

        // Case 1 (mistakes/verdunklung von auswahl speicher nicht erkannt.png):
        // a secondary action dimmed via opacity. Raw colors are IDENTICAL to
        // an undimmed button — only the effective (opacity-composited) colors
        // reveal the dimming.
        const acceptEl = fakeElement({
            rect,
            style: { backgroundColor: "rgb(0, 0, 0)", color: "rgb(255, 255, 255)", opacity: "1" },
        });
        const dimmedRejectEl = fakeElement({
            rect,
            style: { backgroundColor: "rgb(255, 255, 255)", color: "rgb(0, 0, 0)", opacity: "0.4" },
        });
        const dimmed = computeButtonAsymmetry(readStyle(acceptEl), readStyle(dimmedRejectEl));
        assert.equal(dimmed.flagged, true);

        // The same button WITHOUT dimming must NOT be flagged.
        const normalRejectEl = fakeElement({
            rect,
            style: { backgroundColor: "rgb(255, 255, 255)", color: "rgb(0, 0, 0)", opacity: "1" },
        });
        const normal = computeButtonAsymmetry(readStyle(acceptEl), readStyle(normalRejectEl));
        assert.equal(normal.flagged, false);
        assert.equal(normal.contrastDelta < 1, true);

        // Case 2: fully transparent background must composite over the page
        // background (white), NOT collapse to opaque black like the old
        // parseRgb did — that produced arbitrary contrast deltas and false
        // asymmetry flags.
        const transparentRejectEl = fakeElement({
            rect,
            style: { backgroundColor: "rgba(0, 0, 0, 0)", color: "rgb(0, 0, 0)", opacity: "1" },
        });
        const transparentResult = computeButtonAsymmetry(readStyle(acceptEl), readStyle(transparentRejectEl));
        assert.equal(transparentResult.flagged, false);

        // Effective colors are directly sanity-checkable.
        assert.deepEqual(effectiveBackgroundColor(transparentRejectEl), [255, 255, 255]);
        assert.deepEqual(effectiveTextColor(dimmedRejectEl), [153, 153, 153]);

        // Ancestor opacity dims descendants too.
        const dimmedParent = fakeElement({ rect, style: { backgroundColor: "rgba(0,0,0,0)", color: "rgb(0,0,0)", opacity: "0.5" } });
        const childInDimmedParent = fakeElement({
            rect,
            style: { backgroundColor: "rgba(0,0,0,0)", color: "rgb(0,0,0)", opacity: "1" },
            parent: dimmedParent,
        });
        assert.deepEqual(effectiveTextColor(childInDimmedParent), [128, 128, 128]);
    """
    _run_node(script, CONSENT_JS)


def test_consent_generic_fallback_for_unmatched_cmp():
    script = r"""
        import assert from "node:assert/strict";
        import { pathToFileURL } from "node:url";

        // Empty rules → none of the ~206 vendored CMPs match, exercising ONLY
        // the generic fallback path (real bug: businessinsider.de/bild.de's
        // bespoke banner has no vendored rule at all, mistakes/fehlenden
        // reject button nicht erkannt[ 2].png — the fallback is the fix).
        globalThis.chrome = { runtime: { getURL: (p) => p } };
        globalThis.fetch = async () => ({ json: async () => [] });
        globalThis.getComputedStyle = () => ({ display: "block", visibility: "visible", opacity: "1" });

        function fakeControl(text, parent) {
            return {
                tagName: "BUTTON",
                textContent: text,
                parentElement: parent,
                getClientRects: () => [{}],
                getBoundingClientRect: () => ({ width: 100, height: 30 }),
            };
        }

        const bannerContainer = {
            textContent: "Datenschutz und Nutzungserlebnis: Mit Tracking und Cookies nutzen",
        };
        const acceptBtn = fakeControl("Alle Akzeptieren", bannerContainer);
        const settingsBtn = fakeControl("Einstellungen", bannerContainer);
        const controls = [acceptBtn, settingsBtn];
        bannerContainer.querySelectorAll = () => controls;

        const documentBody = { querySelectorAll: () => controls };
        bannerContainer.parentElement = documentBody;

        globalThis.document = {
            body: documentBody,
            querySelectorAll: () => controls,
            querySelector: () => null,
        };

        const consent = await import(pathToFileURL(process.argv[1]).href);

        // No reject control anywhere in the banner → must be flagged.
        const missing = await consent.checkCookieBanner();
        assert.equal(missing.rejectOptionMissing, true);
        assert.equal(missing.genericBannerEl, bannerContainer);

        // Add a real reject control inside the banner → must NOT be flagged.
        controls.push(fakeControl("Nur notwendige Cookies", bannerContainer));
        const ok = await consent.checkCookieBanner();
        assert.equal(ok.rejectOptionMissing, false);
    """
    _run_node(script, CONSENT_JS)


def test_consent_ignores_reject_keyword_buried_in_fine_print_link():
    script = r"""
        import assert from "node:assert/strict";
        import { pathToFileURL } from "node:url";

        // Real bug (bild.de/Sourcepoint, live-verified): a per-vendor
        // fine-print opt-out link ("für Utiq jetzt ablehnen") contains the
        // bare substring "ablehnen" and was wrongly treated as a general
        // reject-all control, hiding a real missing-reject-button banner.
        globalThis.chrome = { runtime: { getURL: (p) => p } };
        globalThis.fetch = async () => ({ json: async () => [] });
        globalThis.getComputedStyle = () => ({ display: "block", visibility: "visible", opacity: "1" });

        function fakeControl(text, parent) {
            return {
                tagName: "A",
                textContent: text,
                parentElement: parent,
                getClientRects: () => [{}],
                getBoundingClientRect: () => ({ width: 100, height: 30 }),
            };
        }

        const bannerContainer = {
            textContent: "Datenschutz und Nutzungserlebnis: Mit Tracking und Cookies nutzen",
        };
        const acceptBtn = fakeControl("Alle Akzeptieren", bannerContainer);
        const finePrintOptOut = fakeControl("für Utiq jetzt ablehnen", bannerContainer);
        const controls = [acceptBtn, finePrintOptOut];
        bannerContainer.querySelectorAll = () => controls;

        const documentBody = { querySelectorAll: () => controls };
        bannerContainer.parentElement = documentBody;

        globalThis.document = {
            body: documentBody,
            querySelectorAll: () => controls,
            querySelector: () => null,
        };

        const consent = await import(pathToFileURL(process.argv[1]).href);

        const result = await consent.checkCookieBanner();
        assert.equal(result.rejectOptionMissing, true);
        assert.equal(result.genericBannerEl, bannerContainer);
    """
    _run_node(script, CONSENT_JS)


def test_sneak_basket_pure_helpers():
    script = r"""
        import assert from "node:assert/strict";
        import { pathToFileURL } from "node:url";

        globalThis.chrome = {};
        const sneak = await import(pathToFileURL(process.argv[1]).href);

        // parseCartCount
        assert.equal(sneak.parseCartCount("Warenkorb, 3 Artikel"), 3);
        assert.equal(sneak.parseCartCount("12"), 12);
        assert.equal(sneak.parseCartCount("150"), null);   // implausible → noise
        assert.equal(sneak.parseCartCount("keine zahl"), null);

        // sumQuantityValues
        assert.equal(sneak.sumQuantityValues(["2", "3"]), 5);
        assert.equal(sneak.sumQuantityValues(["0"]), 1);   // clamped to >= 1
        assert.equal(sneak.sumQuantityValues([]), null);

        // looksLikeCheckoutUrl
        assert.equal(sneak.looksLikeCheckoutUrl("https://shop.example/checkout"), true);
        assert.equal(sneak.looksLikeCheckoutUrl("https://shop.example/kasse"), true);
        assert.equal(sneak.looksLikeCheckoutUrl("https://shop.example/produkt/123"), false);

        // isAddToCartControl
        const btn = (text) => ({
            tagName: "BUTTON",
            nodeType: 1,
            textContent: text,
            getAttribute: () => null,
            parentElement: null,
        });
        assert.equal(sneak.isAddToCartControl(btn("In den Warenkorb")), true);
        assert.equal(sneak.isAddToCartControl(btn("Add to cart")), true);
        assert.equal(sneak.isAddToCartControl(btn("Günstiger kaufen")), false);

        // cartCountFromBadgeEl: bare numeric badge inside a cart context.
        const badge = {
            attributes: [
                { name: "class", value: "cart-count" },
            ],
            id: "",
            className: "cart-count",
            textContent: "3",
            parentElement: {
                attributes: [{ name: "id", value: "cart" }],
                id: "cart",
                className: "",
            },
        };
        assert.equal(sneak.cartCountFromBadgeEl(badge), 3);
    """
    _run_node(script, SNEAK_BASKET_JS)


def test_sneak_basket_checkout_comparison():
    script = r"""
        import assert from "node:assert/strict";
        import { pathToFileURL } from "node:url";

        // Minimal chrome.storage.local mock backing the per-origin baseline.
        const backingStore = {};
        globalThis.chrome = {
            storage: {
                local: {
                    async get(key) {
                        return key in backingStore ? { [key]: backingStore[key] } : {};
                    },
                    async set(obj) {
                        Object.assign(backingStore, obj);
                    },
                },
            },
        };
        globalThis.location = {
            href: "https://shop.example/checkout",
            origin: "https://shop.example",
        };

        const sneak = await import(pathToFileURL(process.argv[1]).href);

        // DOM mock: checkout page with two qty inputs (2 + 3 = 5 items).
        const qtyInput = (value) => ({ value, closest: () => null });
        const doc = {
            location: { href: "https://shop.example/checkout" },
            addEventListener() {},
            querySelectorAll(selector) {
                if (selector.includes('input[type="number"]')) {
                    return [qtyInput("2"), qtyInput("3")];
                }
                if (selector.includes("[id], [class],")) {
                    return []; // no cart badge on this page
                }
                if (selector.includes("h1, h2,")) {
                    return [{ textContent: "Ihre Bestellung" }];
                }
                return [];
            },
            querySelector() { return null; },
            body: {},
        };

        // No baseline yet → null (nothing snuck can be proven).
        assert.equal(await sneak.checkSneakingIntoBasket(doc), null);

        // User tracked ONE item into the basket; checkout shows FIVE.
        await sneak.installAddToCartTracking(doc);
        await sneak.syncBasketFromBadge(doc); // no badge → keeps baseline absent
        const key = "kali_basket_" + globalThis.location.origin;
        backingStore[key] = { count: 1, ts: Date.now(), url: globalThis.location.href };

        const result = await sneak.checkSneakingIntoBasket(doc);
        assert.notEqual(result, null);
        assert.equal(result.detected, true);
        assert.equal(result.expectedCount, 1);
        assert.equal(result.actualCount, 5);
        assert.notEqual(result.tagEl, undefined);

        // Consistent counts → not flagged.
        backingStore[key] = { count: 5, ts: Date.now(), url: globalThis.location.href };
        const ok = await sneak.checkSneakingIntoBasket(doc);
        assert.equal(ok.detected, false);
    """
    _run_node(script, SNEAK_BASKET_JS)


def test_sneak_basket_badge_sync_must_be_skipped_on_checkout_page():
    script = r"""
        import assert from "node:assert/strict";
        import { pathToFileURL } from "node:url";

        const backingStore = {};
        globalThis.chrome = {
            storage: {
                local: {
                    async get(key) {
                        return key in backingStore ? { [key]: backingStore[key] } : {};
                    },
                    async set(obj) {
                        Object.assign(backingStore, obj);
                    },
                },
            },
        };
        globalThis.location = {
            href: "https://shop.example/checkout",
            origin: "https://shop.example",
        };

        const sneak = await import(pathToFileURL(process.argv[1]).href);

        // Checkout page: 2+3=5 actual items, AND its own header cart badge
        // already shows "5" (the already-manipulated count) — this is the
        // real-world shape that defeated detection (see mistakes/ writeup):
        // a checkout page almost always carries its own cart badge.
        const qtyInput = (value) => ({ value, closest: () => null });
        const badge = {
            attributes: [{ name: "class", value: "cart-badge" }],
            id: "",
            className: "cart-badge",
            textContent: "5",
            getAttribute: () => null,
            parentElement: {
                attributes: [{ name: "id", value: "cart" }],
                id: "cart",
                className: "",
            },
        };
        const doc = {
            location: { href: "https://shop.example/checkout" },
            addEventListener() {},
            querySelectorAll(selector) {
                if (selector.includes('input[type="number"]')) {
                    return [qtyInput("2"), qtyInput("3")];
                }
                if (selector.includes("[id], [class],")) {
                    return [badge];
                }
                return [];
            },
            querySelector() { return null; },
            body: {},
        };

        const key = "kali_basket_" + globalThis.location.origin;

        // Honest pre-checkout baseline: the user only ever clicked ONE
        // add-to-cart control before reaching checkout.
        backingStore[key] = { count: 1, ts: Date.now(), url: "https://shop.example/product/1" };

        // Fixed call order (content.js): skip the badge sync on checkout
        // pages, so the comparison reads the honest pre-checkout baseline.
        if (!sneak.looksLikeCheckoutPage(doc)) {
            await sneak.syncBasketFromBadge(doc);
        }
        const fixed = await sneak.checkSneakingIntoBasket(doc);
        assert.equal(fixed.detected, true);
        assert.equal(fixed.expectedCount, 1);
        assert.equal(fixed.actualCount, 5);

        // Old (buggy) call order: badge sync always runs, even on checkout —
        // stomps the honest baseline with the checkout page's own
        // already-manipulated badge count right before the comparison,
        // silently defeating detection. Documents the regression this fix closes.
        backingStore[key] = { count: 1, ts: Date.now(), url: "https://shop.example/product/1" };
        await sneak.syncBasketFromBadge(doc);
        const buggy = await sneak.checkSneakingIntoBasket(doc);
        assert.equal(buggy.detected, false);
    """
    _run_node(script, SNEAK_BASKET_JS)
