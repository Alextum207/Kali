/**
 * The object to access the API functions of the browser.
 * @constant
 * @type {{runtime: object, i18n: object}} BrowserAPI
 */
const brw = chrome;

/**
 * This variable will be dynamically populated with the constants from the other module.
 * Since the import must be dynamic, the variable cannot be declared as a constant.
 * @type {object} A module namespace object
 */
let constants;

/**
 * Same dynamic-import story as `constants` — the cookie-banner detection
 * module (scripts/consent.js).
 * @type {object} A module namespace object
 */
let consent;

/**
 * Same dynamic-import story as `constants` — the sneaking-into-basket
 * detection module (scripts/sneak_basket.js).
 * @type {object} A module namespace object
 */
let sneakBasket;

const countdownVerificationFramePrefix = "__kali_countdown_verify__";
const countdownVerificationTimeoutMs = 7000;
const countdownVerificationAdvanceMs = 6 * 60 * 60 * 1000;
const countdownVerificationSettleMs = 1300;
const countdownVerificationCache = new Map();
const isCountdownVerificationFrame = typeof window.name === "string" &&
    window.name.startsWith(countdownVerificationFramePrefix);

// Same-origin third-party widget iframes (YouTube, Stripe, PayPal, social
// share buttons) run this content script too (manifest.json's all_frames:
// true) but shouldn't be scanned — a dark pattern there belongs to the
// widget provider, not the site being audited. Cross-origin widget iframes
// are already unreachable regardless (browser same-origin policy).
// ponytail: static denylist, no wildcard pattern matching — extend if a new
// provider shows up.
const WIDGET_IFRAME_HOSTS = new Set([
    "youtube.com", "www.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com",
    "stripe.com", "js.stripe.com", "checkout.stripe.com",
    "paypal.com", "www.paypal.com",
    "facebook.com", "www.facebook.com",
    "twitter.com", "x.com",
    "instagram.com", "www.instagram.com",
]);
const isWidgetIframe = window !== window.top && WIDGET_IFRAME_HOSTS.has(location.hostname);

// Initialize the extension.
if (!isCountdownVerificationFrame && !isWidgetIframe) {
    initPatternHighlighter();
}

/**
 * Initialize the extension in the current tab: check the activation state
 * stored by the background script and start highlighting if it is enabled.
 * The message listener below is registered unconditionally so that a later
 * live toggle (see `setActivation` handling) works even if the tab started
 * out deactivated.
 * @returns {Promise<void>}
 */
async function initPatternHighlighter(){
    /**
     * The object that contains the activation state of the extension in the current tab.
     * @constant
     * @type {{isEnabled: boolean}} ResponseMessage
     */
    const activationState = await brw.runtime.sendMessage({ action: "getActivationState" });

    if (activationState.isEnabled === true) {
        await activateHighlighting();
    } else {
        // Print a message that the pattern highlighter is disabled.
        console.log(brw.i18n.getMessage("infoExtensionDisabled"));
    }
}

/**
 * Loads the pattern configuration (if not already loaded) and runs the
 * initial pattern check and highlighting. Used both on startup (if the tab
 * is activated) and when the extension is toggled on live from the popup.
 * @returns {Promise<void>}
 */
async function activateHighlighting() {
    if (!constants) {
        // Dynamically import the constants from the module.
        constants = await import(await brw.runtime.getURL("scripts/constants.js"));
    }
    if (!consent) {
        consent = await import(await brw.runtime.getURL("scripts/consent.js"));
    }
    if (!sneakBasket) {
        sneakBasket = await import(await brw.runtime.getURL("scripts/sneak_basket.js"));
    }

    // Check if the pattern configuration is valid.
    if (!constants.patternConfigIsValid) {
        // If the configuration is not valid, issue an error message,
        // do not start pattern highlighting, and exit.
        console.error(brw.i18n.getMessage("errorInvalidConfig"));
        return;
    }

    // Print a message that the pattern highlighter has started.
    console.log(brw.i18n.getMessage("infoExtensionStarted"));

    // Run the initial pattern check and highlighting.
    await patternHighlighting();
}

/**
 * Stops watching the page for changes and removes all pattern highlighting
 * that is currently shown. Used when the extension is toggled off live from
 * the popup, so no page reload is needed to apply the change.
 */
function deactivateHighlighting() {
    observer.disconnect();
    if (constants) {
        resetDetectedPatterns();
    }
}

// Listen for messages from the popup and background script.
brw.runtime.onMessage.addListener(
    function (message, sender, sendResponse) {
        // Check which action is requested by the popup.
        if (message.action === "getPatternCount") {
            // Compute the pattern statistics/counts and send the result as response.
            sendResponse(getPatternsResults());
        } else if (message.action === "redoPatternHighlighting") {
            // Run the pattern checking and highlighting again,
            // send in response that the action has been started.
            patternHighlighting();
            sendResponse({ started: true });
        } else if ("showElement" in message) {
            // Highlight/show a single pattern element that was selected in the popup.
            showElement(message.showElement);
            sendResponse({ success: true });
        } else if (message.action === "getReportData") {
            // Compute the current findings for the PDF report and send them
            // as the response (see popup.js's ReportButton).
            sendResponse(getReportData());
        } else if ("setActivation" in message) {
            // Live-toggle the extension for this tab without requiring a page reload.
            if (message.setActivation === true) {
                activateHighlighting().then(() => sendResponse({ success: true }));
                return true; // Keep the message channel open for the async response.
            } else {
                deactivateHighlighting();
                sendResponse({ success: true });
            }
        }
    }
);

/**
 * An observer that performs the pattern checking and highlighting after an observed change.
 * @constant
 * @type {MutationObserver}
 */
const observer = new MutationObserver(async function () {
    await patternHighlighting(true);
});

/**
 * The function to identify for patterns on the page. The function uses the detection methods defined in the `patternConfig`.
 * Some HTML tags are ignored (see `tagBlacklist`).
 * If an element is identified as a pattern, two classes are added to it.
 * This will automatically highlight the element using predefined CSS styles.
 * @param {boolean} [waitForChanges=false] A flag to specify whether to wait briefly before executing the function.
 */
async function patternHighlighting(waitForChanges = false) {
    // Check if the pattern detection is already in progress.
    if (this.lock === true) {
        // If the pattern detection is already in progress, exit the function.
        // The result will follow shortly and will be sent automatically to the other parts of the extension.
        return;
    }
    // Lock the function so that it cannot be executed more than once at the same time.
    this.lock = true;

    // Stop monitoring changes on the page with the observer during the pattern identification process.
    observer.disconnect();

    // Wait briefly for subsequent changes after the observer has detected a change.
    if (waitForChanges === true) {
        await new Promise(resolve => { setTimeout(resolve, 500) });
    }

    // Add pattern highlighter IDs to every element on the page.
    addPhidForEveryElement(document.body);

    // Create one copy of the DOM for mutation-safe traversal. Countdown
    // detection no longer depends on a second delayed copy; it combines this
    // current DOM with script/storage/cookie evidence in constants.js.
    let domCopy = document.body.cloneNode(true);
    removeBlacklistNodes(domCopy);

    // Reset all found patterns on the page before updating them afterwards.
    resetDetectedPatterns();

    // Identify patterns within the DOM copy and highlight matched non-countdown
    // elements immediately. Countdown candidates are only marked after the
    // hidden-frame clock verification below confirms that the offer persists.
    const countdownCandidates = [];
    findPatternDeep(domCopy, null, countdownCandidates);

    // Destroy the DOM copy so that it can be removed from memory.
    domCopy.replaceChildren();
    domCopy = null;

    const confirmedCountdownCandidates = await verifyCountdownCandidatesInHiddenFrame(countdownCandidates);
    for (const candidate of confirmedCountdownCandidates) {
        const elem = getElementByPhid(document, candidate.phid);
        if (elem) {
            markDetectedElement(elem, candidate.pattern);
        }
    }

    // Cookie-banner asymmetry / missing-reject-option detection operates on
    // the LIVE document (not the cloned trees above) and tags its matched
    // elements directly — it doesn't fit the per-node findPatternDeep walk
    // (see scripts/consent.js's module docstring for why).
    // Best-effort, like Python's apply_consent_rules: a broken/unexpected
    // rule shape here must never abort the rest of the pipeline below
    // (sendResults + unlocking + re-arming the observer) — that previously
    // left the popup permanently empty and all future re-scans (e.g. a
    // running countdown's next tick) silently dead for the whole tab.
    try {
        await applyCookieBannerChecks();
    } catch (e) {
        console.error("Cookie-banner check failed:", e);
    }

    // Sneaking-into-basket detection (cross-page cart-baseline vs. checkout
    // item count). Same best-effort contract as the cookie-banner checks
    // above: a failure here must never kill the rest of the pipeline.
    try {
        await applySneakingIntoBasketChecks();
    } catch (e) {
        console.error("Sneaking-into-basket check failed:", e);
    }

    // Send the information about the detected patterns to the other extension scripts.
    sendResults();

    // Watch the entire page for changes in the DOM. All nodes, their attributes and contents are observed.
    // Elements that will be ignored later are also observed.
    // Due to the configuration that contents, i.e. characters, are also observed, it can lead to a situation
    // where the pattern highlighting function is executed at a fixed interval if the page is constantly changing.
    // For this it is enough that there is a dynamic countdown or an active video player with time information on the page.
    // Even changes in the background that are not visible can trigger the callback function of the observer.
    // However, the advantage over a fixed interval is that there are also pages where no changes take place.
    // In this case, no unnecessary operations are performed there.
    observer.observe(document.body, {
        subtree: true,
        childList: true,
        attributes: true,
        characterData: true,
    });

    // Finally, unlock the function so that it can be executed again.
    this.lock = false;
}

/**
 * Runs the sneaking-into-basket checks (scripts/sneak_basket.js): syncs the
 * per-origin cart baseline from any visible cart badge, then — on checkout-
 * looking pages — flags when the actual item count exceeds what the user
 * tracked into their basket. Tags the order-summary element directly, same
 * imperative style as applyCookieBannerChecks() above.
 */
async function applySneakingIntoBasketChecks() {
    await sneakBasket.installAddToCartTracking();
    // Skip the badge sync on checkout-looking pages: the checkout page's own
    // cart badge already reflects whatever the shop put in the basket
    // (including a sneaked-in extra), so syncing here would silently
    // overwrite the honest pre-checkout baseline right before the
    // comparison below reads it — defeating detection entirely.
    if (!sneakBasket.looksLikeCheckoutPage()) {
        await sneakBasket.syncBasketFromBadge();
    }

    const result = await sneakBasket.checkSneakingIntoBasket();
    if (result && result.detected && result.tagEl) {
        result.tagEl.classList.add(
            constants.patternDetectedClassName,
            constants.extensionClassPrefix + "sneaking-into-basket"
        );
        console.log("Sneaking-into-basket:", result.detail);
    }
}

/**
 * Runs the cookie-banner checks (scripts/consent.js) and, on a match,
 * class-tags the real page elements directly — accept+reject for button
 * asymmetry, the banner container for a missing reject option. Never
 * clicks anything (see consent.js's checkCookieBanner docstring).
 */
async function applyCookieBannerChecks() {
    const result = await consent.checkCookieBanner();

    if (result.acceptEl && result.rejectEl) {
        const asymmetry = consent.computeButtonAsymmetry(
            consent.readStyle(result.acceptEl),
            consent.readStyle(result.rejectEl)
        );
        if (asymmetry.flagged) {
            result.acceptEl.classList.add(
                constants.patternDetectedClassName,
                constants.extensionClassPrefix + "cookie-banner-asymmetry"
            );
            result.rejectEl.classList.add(
                constants.patternDetectedClassName,
                constants.extensionClassPrefix + "cookie-banner-asymmetry"
            );
        }
    }

    if (result.rejectOptionMissing) {
        // Tag the banner container itself — there's no single "reject
        // button" element to tag when one is missing. Re-resolve via the
        // presentMatcher selector already confirmed to match, or use the
        // generic-fallback container element directly when no vendored
        // rule matched the banner at all (see consent.js's checkCookieBanner).
        const bannerEl = result.genericBannerEl ||
            (result.presentSelector && document.querySelector(result.presentSelector));
        if (bannerEl) {
            bannerEl.classList.add(
                constants.patternDetectedClassName,
                constants.extensionClassPrefix + "cookie-banner-missing-reject"
            );
        }
    }
}

/**
 * Adds a pattern highlighter ID as a custom HTML attribute to each element of a DOM tree.
 * This ID is unique and makes it possible to find elements even after page changes.
 * If an element already has an ID, it will be kept and no new one will be added.
 * @param {Node} dom The DOM tree to whose elements a unique pattern highlighter ID will be added.
 */
function addPhidForEveryElement(dom) {
    // Create a counter as a static local variable that is initialized once and then reused.
    this.counter = this.counter || 0;
    // Iterate over all the individual DOM nodes.
    for (const node of dom.querySelectorAll("*")) {
        // Add a pattern highlighter ID as a custom attribute if there is none already.
        if (!node.dataset.phid) {
            node.dataset.phid = this.counter;
            // Increment the ID counter.
            this.counter += 1;
        }
    }
}

/**
 * Searches the specified DOM tree for an element with the specified pattern highlighter ID.
 * @param {Node} dom The DOM tree in which to search for the element.
 * @param {number} id The ID of the element to search for.
 * @returns {(Element|null)} The element with the searched ID or `null` if no element with the ID was found.
 */
function getElementByPhid(dom, id) {
    // Return the element on the page with the pattern highlighter ID of `id`.
    return dom.querySelector(`[data-phid="` + id + `"]`)
}

/**
 * Removes all elements on the `tagBlacklist` from the specified DOM tree.
 * @param {Node} dom The DOM tree from which the elements will be removed.
 */
function removeBlacklistNodes(dom) {
    // Iterate over all elements on the page with a tag from the `tagBlacklist`.
    for (const elem of dom.querySelectorAll(constants.tagBlacklist.join(","))) {
        // Remove the element from the DOM.
        elem.remove();
    }
}

function cssEscape(value) {
    if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
        return CSS.escape(value);
    }
    return String(value).replace(/["\\#.;:[\]()>,+~*^$|=\s]/g, "\\$&");
}

function selectorForElement(elem) {
    if (elem.id) {
        return `#${cssEscape(elem.id)}`;
    }

    const parts = [];
    let current = elem;
    while (current && current.nodeType === Node.ELEMENT_NODE && current !== document.body && parts.length < 5) {
        let part = current.tagName.toLowerCase();
        if (typeof current.className === "string") {
            const classes = current.className.trim().split(/\s+/).filter(Boolean).slice(0, 2);
            if (classes.length > 0) {
                part += "." + classes.map(cssEscape).join(".");
            }
        }
        if (current.parentElement) {
            const siblings = Array.from(current.parentElement.children)
                .filter(sibling => sibling.tagName === current.tagName);
            if (siblings.length > 1) {
                part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
            }
        }
        parts.unshift(part);
        current = current.parentElement;
    }

    return parts.length > 0 ? parts.join(" > ") : elem.tagName.toLowerCase();
}

function countdownCandidateFromElement(elem, pattern) {
    return {
        phid: elem.dataset.phid,
        selector: selectorForElement(elem),
        textBefore: elem.innerText || elem.textContent || "",
        offerSignature: constants.countdownOfferSignature(elem),
        signature: constants.countdownCandidateSignature(elem),
        pattern,
    };
}

function wait(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function withTimeout(promise, ms) {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("countdown verification timed out")), ms);
        promise.then(
            value => {
                clearTimeout(timer);
                resolve(value);
            },
            error => {
                clearTimeout(timer);
                reject(error);
            }
        );
    });
}

async function waitForFrameLoad(iframe) {
    if (iframe.contentDocument && iframe.contentDocument.readyState !== "loading") {
        return;
    }
    await new Promise((resolve, reject) => {
        iframe.addEventListener("load", resolve, { once: true });
        iframe.addEventListener("error", () => reject(new Error("verification frame failed to load")), { once: true });
    });
}

function findFrameCandidate(frameDocument, candidate) {
    try {
        const directMatch = frameDocument.querySelector(candidate.selector);
        if (directMatch) {
            return directMatch;
        }
    } catch (e) {
        // Fall through to the broader candidate scan.
    }

    for (const elem of frameDocument.body.querySelectorAll("*")) {
        if (constants.isCountdownCandidateNode(elem, null)) {
            return elem;
        }
    }
    return null;
}

async function verifyCountdownCandidatesInHiddenFrame(candidates) {
    if (candidates.length === 0 || isCountdownVerificationFrame || !/^https?:/i.test(location.href)) {
        return [];
    }

    const cacheKey = `${location.href}|${candidates.map(candidate => candidate.signature).join("|")}`;
    if (countdownVerificationCache.has(cacheKey)) {
        const confirmedPhids = countdownVerificationCache.get(cacheKey);
        return candidates.filter(candidate => confirmedPhids.has(candidate.phid));
    }

    let iframe;
    try {
        iframe = document.createElement("iframe");
        iframe.name = `${countdownVerificationFramePrefix}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
        iframe.setAttribute("aria-hidden", "true");
        iframe.tabIndex = -1;
        iframe.style.cssText = [
            "position:fixed",
            "left:-10000px",
            "top:-10000px",
            "width:1px",
            "height:1px",
            "opacity:0",
            "visibility:hidden",
            "pointer-events:none",
            "border:0",
        ].join(";");
        iframe.src = location.href;
        document.documentElement.appendChild(iframe);

        await withTimeout(waitForFrameLoad(iframe), countdownVerificationTimeoutMs);
        await wait(300);

        const frameWindow = iframe.contentWindow;
        const frameDocument = iframe.contentDocument;
        if (!frameWindow || !frameDocument || !frameDocument.body) {
            throw new Error("verification frame is inaccessible");
        }

        const before = new Map();
        for (const candidate of candidates) {
            const frameNode = findFrameCandidate(frameDocument, candidate);
            if (frameNode) {
                before.set(candidate.phid, {
                    text: frameNode.innerText || frameNode.textContent || "",
                    offerSignature: constants.countdownOfferSignature(frameNode),
                });
            }
        }
        if (before.size === 0) {
            throw new Error("no matching countdown candidate in verification frame");
        }

        const event = new frameWindow.CustomEvent("kali-countdown-clock-advance", {
            detail: { offsetMs: countdownVerificationAdvanceMs },
        });
        frameDocument.dispatchEvent(event);
        frameWindow.dispatchEvent(event);
        await wait(countdownVerificationSettleMs);

        const confirmed = [];
        for (const candidate of candidates) {
            const beforeState = before.get(candidate.phid);
            if (!beforeState) {
                continue;
            }
            const frameNodeAfter = findFrameCandidate(frameDocument, candidate);
            if (!frameNodeAfter) {
                continue;
            }
            const textAfter = frameNodeAfter.innerText || frameNodeAfter.textContent || "";
            if (
                constants.countdownTextLooksReset(beforeState.text, textAfter) &&
                constants.countdownOfferStillPresent(beforeState.offerSignature, frameNodeAfter)
            ) {
                confirmed.push(candidate);
            }
        }

        countdownVerificationCache.set(cacheKey, new Set(confirmed.map(candidate => candidate.phid)));
        return confirmed;
    } catch (e) {
        console.debug("Countdown verification failed:", e);
        countdownVerificationCache.set(cacheKey, new Set());
        return [];
    } finally {
        if (iframe) {
            iframe.remove();
        }
    }
}

/**
 * Checks a DOM node for patterns. This is done using the detection functions defined in the `patternConfig`.
 * @param {Node} node The DOM node to be inspected for patterns.
 * @param {Node} [nodeOld] The previous state of the DOM node to be checked for patterns, if present.
 * @returns {(Object|null)} The matched pattern object from `patternConfig`, if one was detected, otherwise `null`.
 */
function findPatterInNode(node, nodeOld) {
    // Iterate over all patterns in the `patternConfig`.
    for (const pattern of constants.patternConfig.patterns) {
        // Iterate over all detection functions for the pattern. Usually is only a single one.
        for (const func of pattern.detectionFunctions) {
            // Pass the two parameters to the detection function and check if the pattern is detected.
            if (func(node, nodeOld)) {
                // If the detection function returns `true`, the respective pattern was detected.
                // The matched pattern object is returned and the function terminates.
                return pattern;
            }
        }
    }
    return null;
}

function markDetectedElement(elem, pattern) {
    elem.classList.add(
        constants.patternDetectedClassName,
        constants.extensionClassPrefix + pattern.className
    );
    if (constants.SHOW_DEBUG_BOXES) {
        elem.classList.add(constants.debugBoxClassName);
    }
    elem.title = pattern.info;
    addExplainIcon(elem, pattern);
}

// (elem, details) pairs whose icon position needs to follow elem — see
// _repositionExplainIcons. Appended to as icons are created, never pruned
// (matches the rest of this file: detected elements aren't expected to
// disappear from the live page within one analysis pass).
const _phTrackedIcons = [];

/**
 * Adds a clickable "explain" icon near a detected-pattern element. Uses the
 * native <details>/<summary> disclosure widget so click-to-open/close needs
 * no JS state or outside-click handling. Appended to document.body (not as
 * a child of elem) so it isn't clipped by elem's own overflow/positioning;
 * kept aligned with elem on scroll/resize via _repositionExplainIcons.
 * @param {HTMLElement} elem The detected element to anchor the icon near.
 * @param {object} pattern The matched pattern object (needs .info, .infoUrl).
 */
function addExplainIcon(elem, pattern) {
    if (elem.dataset.phInfoIcon) {
        return;
    }
    elem.dataset.phInfoIcon = "1";

    const details = document.createElement("details");
    details.className = constants.extensionClassPrefix + "info-icon";

    const summary = document.createElement("summary");
    summary.textContent = "ⓘ";
    details.appendChild(summary);

    const info = document.createElement("p");
    info.textContent = pattern.info;
    details.appendChild(info);

    if (pattern.infoUrl) {
        const link = document.createElement("a");
        link.href = pattern.infoUrl;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = "Mehr erfahren";
        details.appendChild(link);
    }

    document.body.appendChild(details);
    _phTrackedIcons.push({ elem, details });
    _positionExplainIcon(elem, details);
}

/**
 * Places one icon at elem's current top-right corner, converting elem's
 * viewport-relative rect to document coordinates (works for `position:
 * absolute` regardless of window vs. inner-container scrolling, since
 * getBoundingClientRect() always reflects elem's current on-screen spot).
 */
function _positionExplainIcon(elem, details) {
    const rect = elem.getBoundingClientRect();
    details.style.top = (rect.top + window.scrollY - 10) + "px";
    details.style.left = (rect.right + window.scrollX - 10) + "px";
}

/** Re-reads every tracked icon's anchor element and repositions it — called
 * on scroll/resize so icons stay pinned to their box instead of drifting. */
function _repositionExplainIcons() {
    for (const { elem, details } of _phTrackedIcons) {
        _positionExplainIcon(elem, details);
    }
}

window.addEventListener("scroll", _repositionExplainIcons, { passive: true, capture: true });
window.addEventListener("resize", _repositionExplainIcons, { passive: true });

/**
 * Recursively finds patterns within a DOM tree or node.
 * The recognition functions from the `patternConfig` are used.
 * If elements are identified as patterns, respective classes are added to them.
 * @param {Node} node A DOM node or a complete DOM tree in which to search for patterns.
 * @param {Node} domOld The complete previous state of the DOM tree of the page.
 */
function findPatternDeep(node, domOld, countdownCandidates = []) {
    // Iterate over all child nodes of the provided DOM node.
    for (const child of node.children) {
        // Execute the function recursively on each child node.
        findPatternDeep(child, domOld, countdownCandidates);
    }

    // Extract the previous state of the node from the old DOM if one exists.
    let nodeOld = domOld ? getElementByPhid(domOld, node.dataset.phid) : null;
    // Check if the node represents one of the patterns.
    let foundPattern = findPatterInNode(node, nodeOld);

    // If a pattern is detected, add appropriate classes to the element
    // and remove it from the DOM for the further pattern search.
    if (foundPattern) {
        // Find the element in the original DOM.
        let elem = getElementByPhid(document, node.dataset.phid);
        // Check if the element still exists.
        if (elem) {
            if (foundPattern.className === "countdown") {
                countdownCandidates.push(countdownCandidateFromElement(elem, foundPattern));
            } else {
                markDetectedElement(elem, foundPattern);
            }
        }
        // Remove the previous state of the node, if it exists.
        if (nodeOld) {
            nodeOld.remove();
        }
        // Remove the current state of the node.
        node.remove();
    }
}

/**
 * Removes the classes that are assigned to found patterns from all pattern elements.
 */
function resetDetectedPatterns() {
    // Regular expression to find all classes belonging to the extension.
    let regx = new RegExp("\\b" + constants.extensionClassPrefix + "[^ ]*[ ]?\\b", "g");
    // Iterate over all detected pattern elements.
    document.querySelectorAll("." + constants.patternDetectedClassName).forEach(
        function (node) {
            // Remove all classes belonging to the extension.
            node.className = node.className.replace(regx, "");
        }
    );
}

/**
 * Checks whether an element is visible based on its DOM node.
 * @param {Node} elem DOM node that is checked for visibility.
 * @returns {boolean} `true` if the element is visible, `false` otherwise.
 */
function elementIsVisible(elem) {
    // Get the 'actual' style of the element after applying active stylesheets.
    const computedStyle = getComputedStyle(elem);
    // Check if the element has explicit CSS styles which hide it or make it invisible.
    if (computedStyle.visibility == "hidden" || computedStyle.display == "none" || computedStyle.opacity == "0") {
        // Return `false` if the element is not visible.
        return false;
    }
    // According to the CSS Object Model (CSSOM),
    // all of these three values should return `0`
    // if the element has no layout box and is therefore not visible.
    // Edge cases (false positives) cannot be ruled out, but should be rare.
    return !!(elem.offsetWidth || elem.offsetHeight || elem.getClientRects().length);
};

/**
 * Creates an object with the counts of detected patterns and
 * the pattern highlighter IDs of the corresponding elements on the page.
 * @returns {object} The object with the information and counts about the detected patterns.
 */
function getPatternsResults() {
    // Initialize the result object with all required keys.
    let results = {
        // An array with the pattern highlighter IDs of the detected elements for each pattern.
        // The elements are divided into two arrays according to the property visible or hidden.
        // Each object in the `patterns` array contains the `name` key with the name of the pattern.
        "patterns": [],
        // The total count of detected elements that represent patterns and are visible on the page.
        "countVisible": 0,
        // The total count of detected elements that represent patterns.
        "count": 0,
    }
    // The pattern configuration is only loaded once the extension has been
    // activated at least once in this tab (see `activateHighlighting`).
    // Return the empty result object if that hasn't happened yet.
    if (!constants) {
        return results;
    }
    // Iterate over all patterns in the `patternConfig`.
    for (const pattern of constants.patternConfig.patterns) {
        // Array to collect all visible elements to the pattern.
        let elementsVisible = [];
        // Array to collect all hidden elements to the pattern.
        let elementsHidden = [];

        // Iterate over all elements that represent the current pattern.
        for (const elem of document.getElementsByClassName(constants.extensionClassPrefix + pattern.className)) {
            // Depending on whether the element is visible or hidden,
            // add its pattern highlighter ID to the appropriate array.
            if (elementIsVisible(elem)) {
                elementsVisible.push(elem.dataset.phid);
            } else {
                elementsHidden.push(elem.dataset.phid);
            }
        }

        // Add the name of the pattern and the two arrays with the elements as an object to the result object.
        results.patterns.push({
            name: pattern.name,
            elementsVisible: elementsVisible,
            elementsHidden: elementsHidden,
        });

        // Add the number of visible detected elements of the pattern
        // to the total number of visible detected elements.
        results.countVisible += elementsVisible.length;
        // Add the count of detected elements of the pattern to the total count of detected elements.
        results.count += elementsVisible.length + elementsHidden.length;
    }
    // Return the complete result object.
    return results;
}

/**
 * Builds the data for the PDF report (report/report.js): one entry per
 * pattern type that currently has at least one detected element on the
 * page, with its legal norm (constants.normMap), a plain-English impact
 * description (pattern.info — the same text already shown as a tooltip in
 * the popup's found-patterns list), a short text excerpt from the first
 * matched element as a quote/example, and how many elements matched.
 * popup.js separately captures a screenshot of the visible tab and
 * report.js shows that same full screenshot for every finding (not cropped
 * to the element) — see report.js.
 * @returns {{url: string, generatedAt: string, items: Array<object>}}
 */
function getReportData() {
    let items = [];
    // Same guard as getPatternsResults() — nothing to report before the
    // extension has activated at least once in this tab.
    if (constants) {
        for (const pattern of constants.patternConfig.patterns) {
            const elements = document.getElementsByClassName(constants.extensionClassPrefix + pattern.className);
            if (elements.length === 0) {
                continue;
            }
            const quoteSource = elements[0].innerText;
            items.push({
                pattern_type: pattern.name,
                norm: constants.normMap[pattern.className] || "–",
                impact: pattern.info,
                quote: quoteSource ? quoteSource.trim().slice(0, 200) : "",
                count: elements.length,
            });
        }
    }
    return {
        url: location.href,
        generatedAt: new Date().toISOString(),
        items,
    };
}

/**
 * Send the information and counts about the detected patterns to the other extension scripts.
 */
function sendResults() {
    // Create the result object with all information and counts.
    let results = getPatternsResults();

    // Send the object to all other extension scripts. Do nothing in the event of a reply.
    brw.runtime.sendMessage(
        results,
        function (response) { }
    );

    // Print out the number of visible pattern elements.
    console.log(brw.i18n.getMessage("infoNumberPatternsFound", [results.countVisible.toString()]));
}

/**
 * @typedef {object} Position
 * @property {number} left - The offset from the left
 * @property {number} top - The offset from the top
 */
/**
 * Compute the absolute offset of an element on the page using its DOM node.
 * @param {Node} elem DOM node from which the absolute position is determined.
 * @returns {Position}
 */
function getAbsoluteOffsetFromBody(elem) {
    // Get a DOMRect object with the element's position relative to the viewport.
    const rect = elem.getBoundingClientRect();
    // Return the distance of the element to the left and top edge of the page in pixels.
    return {
        left: rect.left + window.scrollX,
        top: rect.top + window.scrollY
    };
}

// Lazily-created closed Shadow DOM host for the highlight-glow element
// below — keeps its CSS (and any future extension-owned overlay UI) fully
// isolated from the host page's own styles, and vice versa.
let _phShadowRoot = null;
function _getShadowRoot() {
    if (!_phShadowRoot) {
        const host = document.createElement("div");
        document.body.appendChild(host);
        _phShadowRoot = host.attachShadow({ mode: "closed" });
        const style = document.createElement("style");
        style.textContent = `
.__ph__current-pattern {
    position: absolute;
    z-index: 10000;
    box-shadow: 0 0 120px 150px red;
    animation: __ph__highlight 5s;
    opacity: 0;
}
@keyframes __ph__highlight {
    from { opacity: 0.75; }
    to { opacity: 0; }
}
`;
        _phShadowRoot.appendChild(style);
    }
    return _phShadowRoot;
}

/**
 * Shows an element on the page by automatically scrolling so that the element is vertically centered in the viewport.
 * Additionally, a catchy shadow is added for a few seconds, whose appearance is predefined by corresponding CSS styles.
 * @param {number} phid The pattern highlighter ID of the element that will be shown.
 */
function showElement(phid) {
    const shadowRoot = _getShadowRoot();

    // Remove all old shadow elements.
    for (const element of shadowRoot.querySelectorAll("." + constants.currentPatternClassName)) {
        element.remove();
    }

    // Get the element to be shown by its ID.
    let elem = getElementByPhid(document, phid);

    // Check if the element with the `phid` exists or if no element with the ID was found.
    if (elem == null) {
        // If the element does not exist, exit the function to prevent errors.
        // Since all components of the extension are constantly updated and receive the new IDs,
        // this case is not really to be expected.
        return;
    }

    // Scroll to the element so that it is displayed in the center of the viewport.
    elem.scrollIntoView({
        behavior: "smooth",
        block: "center",
        inline: "center"
    });

    // Create an element that will be used as a shadow for the pattern element.
    let highlightShadowElem = document.createElement("div");

    // Align it on the page so that it is in the same place on the page
    // with the same size as the pattern element that is shown.
    highlightShadowElem.style.position = "absolute";
    highlightShadowElem.style.height = elem.offsetHeight + "px";
    highlightShadowElem.style.width = elem.offsetWidth + "px";
    let elemXY = getAbsoluteOffsetFromBody(elem);
    highlightShadowElem.style.top = elemXY.top + "px";
    highlightShadowElem.style.left = elemXY.left + "px";

    // Add a class for which there are predefined styles to represent the shadow.
    highlightShadowElem.classList.add(constants.currentPatternClassName);

    // Add the shadow element to the isolated Shadow DOM.
    shadowRoot.appendChild(highlightShadowElem);
}
