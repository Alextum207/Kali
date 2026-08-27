/**
 * The object to access the API functions of the browser.
 * @constant
 * @type {{runtime: object, i18n: object}} BrowserAPI
 */
const brw = chrome;

const metaContextRe = /\b(?:z\.\s*b\.|zum\s+beispiel|beispiel|example|e\.g\.|regex|detektor|detector|dark\s+patterns?|patterns?|dokumentation|documentation|dom(?:\s+tree)?|render-tree|report|funde?|scannt|erkennung|erkennen|klassifizier(?:t|ung)?)\b/i;

function isMetaContext(text, start, end) {
    const prefix = text.slice(Math.max(0, start - 140), start);
    if (metaContextRe.test(prefix)) {
        return true;
    }
    const lineStart = text.lastIndexOf("\n", start) + 1;
    const nextLineBreak = text.indexOf("\n", end);
    const lineEnd = nextLineBreak === -1 ? text.length : nextLineBreak;
    const line = text.slice(lineStart, lineEnd);
    return /\b(?:const|let|var|function|regex|example|beispiel)\b|[<>{};=]/i.test(line);
}

function isSellerAttribution(text, match) {
    const matched = match[0].toLowerCase();
    const suffix = text.slice(match.index + match[0].length, match.index + match[0].length + 16).toLowerCase();
    return /\b(?:sold|verkauft)\b/i.test(matched) && /^[ \t]*(?:by|von)\b/i.test(suffix);
}

// A node whose combined text is longer than this is a large content block
// (an article, a whole chat answer, ...), not a short dark-pattern badge or
// phrase. findPatternDeep tests nodes bottom-up and only reaches a large
// container's own text when none of its individual children matched (see
// content.js) — so if some small, unrelated substring buried anywhere in
// that huge combined text happens to match, highlighting kicks in on the
// ENTIRE container, not just the substring: misleading and useless UX even
// when the regex match itself is real. isMetaContext only guards the local
// ~140 chars around the match, not the size of the container being tagged.
// Real bug report: an entire Perplexity chat answer about building this
// same extension (full of words like "Report"/"Funde"/"DOM" — the sort of
// thing isMetaContext's keyword list is meant to catch, but too far from
// the actual match point to be in its 140-char window) got labeled Scarcity
// wholesale (mistakes/false scarcity 2.png). ponytail: fixed length cap,
// not real container-size-awareness — upgrade to matching against
// individual text nodes instead of aggregated innerText if a legitimate
// long badge/phrase ever gets caught by this.
const MAX_PATTERN_MATCH_TEXT_LENGTH = 300;

function textPatternMatches(node, regex, patternType) {
    if (typeof node.innerText !== "string" || node.innerText.length > MAX_PATTERN_MATCH_TEXT_LENGTH) {
        return false;
    }
    const flags = regex.flags.includes("g") ? regex.flags : regex.flags + "g";
    const globalRegex = new RegExp(regex.source, flags);
    for (const match of node.innerText.matchAll(globalRegex)) {
        if (isMetaContext(node.innerText, match.index, match.index + match[0].length)) {
            continue;
        }
        if (patternType === "scarcity" && isSellerAttribution(node.innerText, match)) {
            continue;
        }
        return true;
    }
    return false;
}

const countdownTimeRe = /(?:\d{1,2}\s*:\s*){1,3}\d{1,2}|(?:\d{1,3}\s*(?:days?|d|hours?|hrs?|h|minutes?|mins?|min|seconds?|secs?|s|tage?|stunden?|std\.?|minuten?|sekunden?)(?:\s*und)?\s*){2,4}/i;
const countdownSingleUnitRe = /\b\d{1,3}\s*(?:days?|d|hours?|hrs?|h|minutes?|mins?|min|seconds?|secs?|s|tage?|stunden?|std\.?|minuten?|sekunden?)\b/i;
const countdownBadRe = /(?:\d{1,2}\s*:\s*){4,}\d{1,2}|(?:\d{1,3}\s*(?:days?|d|hours?|hrs?|h|minutes?|mins?|min|seconds?|secs?|s|tage?|stunden?|std\.?|minuten?|sekunden?)(?:\s*und)?\s*){5,}/i;
const countdownMarkerRe = /\b(?:count\s*down|countdown|timer|deadline|expires?|expiry|ending?|sale\s*ends?|offer\s*ends?|deal\s*ends?|time\s*left|remaining|restzeit|ablauf|ablaufzeit|laeuft\s*ab|läuft\s*ab|angebot\s*endet|frist)\b/i;
const countdownStorageKeyRe = /\b(?:count\s*down|countdown|timer|deadline|expires?|expiry|end(?:s|time|at)?|deal|offer|sale|ttl|remaining|restzeit|ablauf)\b/i;
const urgencyRe = /\b(?:hurry|rush|last\s*chance|final\s*hours?|limited\s*time|act\s*now|expires?\s*(?:soon|today)|ends?\s*(?:soon|today|tonight)|only\s+\d+\s+left|beeil|nur\s+noch|letzte\s*chance|endet\s*(?:bald|heute)|zeitlich\s*begrenzt)\b/i;
const commerceRe = /\b(?:cart|checkout|basket|buy|order|price|sale|discount|coupon|deal|offer|shipping|subscribe|pricing|product|warenkorb|kasse|kaufen|bestellen|preis|rabatt|angebot|versand|produkt)\b/i;
const benignCountdownContextRe = /\b(?:webinar|conference|event|match|game|exam|livestream|stream\s*starts|maintenance|scheduled|appointment|christmas|birthday|konferenz|veranstaltung|wartung|termin)\b/i;
const scriptLoopRe = /\b(?:setInterval|setTimeout|requestAnimationFrame)\b/;
const scriptClockRe = /\b(?:Date\.now|new\s+Date\s*\(|getTime\s*\(|performance\.now)\b/;
const scriptDomWriteRe = /\b(?:textContent|innerText|innerHTML|value)\b/;
const scriptStorageRe = /\b(?:localStorage|sessionStorage|document\.cookie|cookieStore)\b/;
const scriptRelativeDeadlineRe = /(?:Date\.now\s*\(\s*\)|new\s+Date\s*\(\s*\)\.getTime\s*\(\s*\))\s*\+\s*(?:\d{4,}|[A-Z_][A-Z0-9_]*|[a-z_$][\w$]*)|set(?:Minutes|Seconds|Hours|Date)\s*\(/i;
const scriptStorageSetterRe = /\.(?:setItem)\s*\(|document\.cookie\s*=/i;
const countdownExpiryRe = /\b(?:abgelaufen|beendet|expired|ended|vorbei|nicht\s+mehr\s+verfügbar|nicht\s+mehr\s+verfuegbar|sold\s+out|ausverkauft)\b/i;
const priceRe = /(?:€|eur|\$|usd|£|gbp)\s*\d+|\d+(?:[.,]\d{2})?\s*(?:€|eur|euro|dollar|usd|£|gbp|pounds?)/i;

function nodeText(node) {
    if (typeof node.innerText === "string") {
        return node.innerText;
    }
    if (typeof node.textContent === "string") {
        return node.textContent;
    }
    return "";
}

function nodeAttributeText(node) {
    const parts = [];
    if (node.id) {
        parts.push(node.id);
    }
    if (typeof node.className === "string") {
        parts.push(node.className);
    }
    if (node.dataset) {
        for (const [key, value] of Object.entries(node.dataset)) {
            parts.push(key, value);
        }
    }
    if (node.attributes && typeof node.attributes[Symbol.iterator] === "function") {
        for (const attr of node.attributes) {
            if (/^(id|class|name|value|aria-label|role|data-|datetime)/i.test(attr.name)) {
                parts.push(attr.name, attr.value);
            }
        }
    }
    return parts.join(" ");
}

function hasCleanCountdownToken(text) {
    return countdownTimeRe.test(String(text || "").replace(countdownBadRe, ""));
}

function hasCountdownValue(text) {
    const cleanText = String(text || "").replace(countdownBadRe, "");
    return countdownTimeRe.test(cleanText) || countdownSingleUnitRe.test(cleanText) || /\b\d{2,}\b/.test(cleanText);
}

function parsePossibleDeadline(value, nowMs = Date.now()) {
    const raw = String(value || "").trim();
    if (!raw) {
        return null;
    }

    let timestamp = Number(raw);
    if (Number.isFinite(timestamp) && timestamp > 1000000000 && timestamp < 10000000000) {
        timestamp *= 1000;
    }
    if (!Number.isFinite(timestamp)) {
        timestamp = Date.parse(raw);
    }
    if (!Number.isFinite(timestamp)) {
        const embedded = raw.match(/\b(?:1[7-9]\d{8,12}|2\d{9,12})\b/);
        if (embedded) {
            timestamp = Number(embedded[0]);
            if (timestamp < 10000000000) {
                timestamp *= 1000;
            }
        }
    }
    if (!Number.isFinite(timestamp)) {
        return null;
    }

    const deltaMs = timestamp - nowMs;
    return {
        timestamp,
        isNearFuture: deltaMs > 0 && deltaMs <= 14 * 24 * 60 * 60 * 1000,
        isRecentlyExpired: deltaMs <= 0 && deltaMs >= -60 * 60 * 1000,
    };
}

function storageEntries(storage) {
    const entries = [];
    if (!storage) {
        return entries;
    }
    try {
        for (let i = 0; i < storage.length && entries.length < 200; i++) {
            const key = storage.key(i);
            entries.push({ key, value: storage.getItem(key) });
        }
    } catch (e) {
        return entries;
    }
    return entries;
}

function cookieEntries() {
    if (typeof document === "undefined") {
        return [];
    }
    try {
        return String(document.cookie || "")
            .split(";")
            .map(part => part.trim())
            .filter(Boolean)
            .slice(0, 200)
            .map(part => {
                const index = part.indexOf("=");
                return index === -1
                    ? { key: part, value: "" }
                    : { key: part.slice(0, index).trim(), value: part.slice(index + 1).trim() };
            });
    } catch (e) {
        return [];
    }
}

function collectCountdownPageEvidence() {
    const now = Date.now();
    const cache = globalThis.__phCountdownPageEvidence;
    if (cache && now - cache.createdAt < 500) {
        return cache.value;
    }

    const bodyText = typeof document !== "undefined" && document.body ? nodeText(document.body) : "";
    const scripts = typeof document !== "undefined" && document.scripts
        ? Array.from(document.scripts).slice(0, 80).map(script => `${script.src || ""}\n${script.textContent || ""}`).join("\n")
        : "";

    const storageLikeEntries = []
        .concat(storageEntries(globalThis.localStorage))
        .concat(storageEntries(globalThis.sessionStorage))
        .concat(cookieEntries());

    let storageDeadline = false;
    for (const entry of storageLikeEntries) {
        if (!countdownStorageKeyRe.test(String(entry.key || ""))) {
            continue;
        }
        const parsed = parsePossibleDeadline(entry.value, now);
        if (!parsed || parsed.isNearFuture || parsed.isRecentlyExpired) {
            storageDeadline = true;
            break;
        }
    }

    const value = {
        pageHasCommerce: commerceRe.test(bodyText),
        pageHasBenignCountdownContext: benignCountdownContextRe.test(bodyText) && !commerceRe.test(bodyText),
        scriptHasClientLoop: scriptLoopRe.test(scripts) && scriptDomWriteRe.test(scripts) &&
            (scriptClockRe.test(scripts) || countdownMarkerRe.test(scripts) || countdownStorageKeyRe.test(scripts)),
        scriptCreatesRelativeDeadline: countdownStorageKeyRe.test(scripts) && scriptRelativeDeadlineRe.test(scripts),
        scriptPersistsDeadline: scriptStorageRe.test(scripts) && scriptStorageSetterRe.test(scripts) && countdownStorageKeyRe.test(scripts),
        scriptClearsDeadline: /\b(?:removeItem|clear)\s*\(|expires\s*=\s*Thu,\s*01\s*Jan\s*1970/i.test(scripts) && countdownStorageKeyRe.test(scripts),
        storageDeadline,
    };

    globalThis.__phCountdownPageEvidence = { createdAt: now, value };
    return value;
}

function hasNearFutureDeadlineAttribute(node) {
    if (!node || !node.attributes || typeof node.attributes[Symbol.iterator] !== "function") {
        return false;
    }
    for (const attr of node.attributes) {
        const packed = `${attr.name} ${attr.value}`;
        if (!countdownStorageKeyRe.test(packed)) {
            continue;
        }
        const parsed = parsePossibleDeadline(attr.value);
        if (parsed && (parsed.isNearFuture || parsed.isRecentlyExpired)) {
            return true;
        }
    }
    return false;
}

function countdownChangedBetweenSnapshots(node, nodeOld) {
    if (!nodeOld || nodeText(node) === nodeText(nodeOld)) {
        return false;
    }

    const reg = /(?:\d{1,2}\s*:\s*){1,3}\d{1,2}|(?:\d{1,2}\s*(?:days?|d|hours?|hrs?|h|minutes?|mins?|min|seconds?|secs?|s|tage?|stunden?|std\.?|minuten?|sekunden?)(?:\s*und)?\s*){2,4}/gi;
    const regBad = /(?:\d{1,2}\s*:\s*){4,}\d{1,2}|(?:\d{1,2}\s*(?:days?|d|hours?|hrs?|h|minutes?|mins?|min|seconds?|secs?|s|tage?|stunden?|std\.?|minuten?|sekunden?)(?:\s*und)?\s*){5,}/gi;
    let matchesOld = nodeText(nodeOld).replace(regBad, "").match(reg);
    let matchesNew = nodeText(node).replace(regBad, "").match(reg);

    if (matchesNew == null || matchesOld == null || matchesNew.length != matchesOld.length) {
        return false;
    }

    for (let i = 0; i < matchesNew.length; i++) {
        let numbersNew = matchesNew[i].match(/\d+/gi);
        let numbersOld = matchesOld[i].match(/\d+/gi);
        if (numbersNew.length != numbersOld.length) {
            continue;
        }

        for (let x = 0; x < numbersNew.length; x++) {
            if (parseInt(numbersNew[x]) > parseInt(numbersOld[x])) {
                break;
            }
            if (parseInt(numbersNew[x]) < parseInt(numbersOld[x])) {
                return true;
            }
        }
    }
    return false;
}

export function countdownSingleScanMatch(node) {
    const text = nodeText(node);
    if (!text || typeof text !== "string") {
        return false;
    }
    const attrText = nodeAttributeText(node);
    const combined = `${attrText} ${text}`;
    const firstMatch = text.match(countdownTimeRe);
    if (firstMatch && isMetaContext(text, firstMatch.index, firstMatch.index + firstMatch[0].length)) {
        return false;
    }

    const hasTimeToken = hasCleanCountdownToken(text) ||
        (countdownSingleUnitRe.test(text) && countdownMarkerRe.test(combined));
    const hasCountdownMarker = countdownMarkerRe.test(combined) || countdownStorageKeyRe.test(attrText);
    const hasUrgency = urgencyRe.test(combined);
    const hasCommerce = commerceRe.test(combined);
    const hasBenignContext = benignCountdownContextRe.test(combined);
    const evidence = collectCountdownPageEvidence();
    const hasScriptOrStorageReset = evidence.scriptCreatesRelativeDeadline ||
        evidence.scriptPersistsDeadline ||
        evidence.scriptClearsDeadline ||
        evidence.storageDeadline;

    if (!hasTimeToken && !hasNearFutureDeadlineAttribute(node)) {
        return false;
    }
    if (hasBenignContext && !hasCommerce && !evidence.pageHasCommerce && !hasScriptOrStorageReset) {
        return false;
    }
    if (hasNearFutureDeadlineAttribute(node) && (hasCountdownMarker || hasUrgency || hasCommerce || evidence.pageHasCommerce)) {
        return true;
    }
    if (hasTimeToken && hasCountdownMarker && (hasUrgency || hasCommerce || evidence.pageHasCommerce || evidence.scriptHasClientLoop)) {
        return true;
    }
    if (hasTimeToken && hasUrgency && (hasCommerce || evidence.pageHasCommerce)) {
        return true;
    }
    if (hasTimeToken && (hasUrgency || hasCommerce || hasCountdownMarker) &&
        (evidence.scriptHasClientLoop || hasScriptOrStorageReset)) {
        return true;
    }
    return false;
}

export function isCountdownCandidateNode(node, nodeOld = null) {
    return countdownChangedBetweenSnapshots(node, nodeOld) || countdownSingleScanMatch(node);
}

export function countdownTextLooksReset(textBefore, textAfter) {
    const afterText = String(textAfter || "");
    if (!afterText || countdownExpiryRe.test(afterText)) {
        return false;
    }
    if (!hasCountdownValue(afterText)) {
        return false;
    }
    const beforeText = String(textBefore || "");
    const beforeExpired = countdownExpiryRe.test(beforeText);
    return beforeExpired || beforeText.trim() !== afterText.trim() || hasCountdownValue(afterText);
}

export function countdownOfferSignature(node) {
    if (!node) {
        return { text: "", hasCommerce: false };
    }

    let current = node;
    let best = node;
    for (let depth = 0; current && depth < 5; depth++) {
        const text = nodeText(current);
        const attrs = nodeAttributeText(current);
        if (commerceRe.test(`${attrs} ${text}`) || priceRe.test(text)) {
            best = current;
            break;
        }
        if (/^(ARTICLE|SECTION|MAIN|FORM|LI|DIV)$/i.test(current.tagName || "")) {
            best = current;
        }
        current = current.parentElement;
    }

    const text = nodeText(best).replace(/\s+/g, " ").trim().slice(0, 600);
    const attrs = nodeAttributeText(best);
    return {
        text,
        hasCommerce: !countdownExpiryRe.test(text) && (commerceRe.test(`${attrs} ${text}`) || priceRe.test(text)),
    };
}

export function countdownOfferStillPresent(beforeSignature, afterNode) {
    const afterSignature = countdownOfferSignature(afterNode);
    if (!afterSignature.hasCommerce) {
        return false;
    }
    if (!beforeSignature || !beforeSignature.text) {
        return true;
    }
    const beforeWords = new Set(beforeSignature.text.toLowerCase().match(/[a-zäöüß0-9]{4,}/gi) || []);
    const afterWords = new Set(afterSignature.text.toLowerCase().match(/[a-zäöüß0-9]{4,}/gi) || []);
    let overlap = 0;
    for (const word of beforeWords) {
        if (afterWords.has(word)) {
            overlap++;
        }
    }
    return overlap >= 1 || (beforeSignature.hasCommerce && afterSignature.hasCommerce);
}

export function countdownCandidateSignature(node) {
    const text = nodeText(node).replace(/\s+/g, " ").trim();
    const attrs = nodeAttributeText(node).replace(/\s+/g, " ").trim();
    return `${node.tagName || ""}|${attrs}|${text}`.slice(0, 800);
}

/**
 * Configuration of the pattern detection functions.
 * The following attributes must be specified for each pattern.
 *  - `name`: The name of the pattern that will be displayed on the UI.
 *  - `className`: A valid CSS class name for the pattern (used only internally and not displayed).
 *  - `detectionFunctions`: An array of functions `f(node, nodeOld)` to detect the pattern.
 *      Parameters of the functions are the HTML node to be examined in current and previous state (in this order).
 *      The functions must return `true` if the pattern was detected and `false` if not.
 *  - `infoUrl`: The URL to the explanation of the pattern (Verbraucherzentrale).
 *  - `info`: A brief explanation of the pattern.
 *  - `languages`: An array of ISO 639-1 codes of the languages supported by the detection functions..
 * @constant
 * @type {{
 *  patterns: Array.<{
 *      name: string,
 *      className: string,
 *      detectionFunctions: Array.<Function>,
 *      infoUrl: string,
 *      info: string,
 *      languages: Array.<string>
 *  }>
 * }}
 */
export const patternConfig = {
    patterns: [
        {
            /**
             * Autoplay Pattern (Exploiting Addiction).
             * Video/audio elements that start playing automatically, binding
             * the user's attention without an active choice.
             * Ported from Kali's app/analysis/heuristics.py:find_autoplay_media.
             *
             * Checked FIRST, ahead of the text-based patterns below:
             * findPatterInNode() below assigns each element to only the
             * first pattern that matches and then removes it from further
             * search, so if a <video>/<audio> element's own text content
             * (e.g. fallback content) happened to also match a later
             * text-based pattern like Scarcity, this attribute check would
             * never run for that element. A plain attribute check can never
             * false-positive, so checking it first costs nothing and closes
             * that gap.
             */
            name: brw.i18n.getMessage("patternAutoplay_name"),
            className: "autoplay",
            detectionFunctions: [
                function (node, nodeOld) {
                    if ((node.tagName !== "VIDEO" && node.tagName !== "AUDIO") || !node.hasAttribute("autoplay")) {
                        return false;
                    }
                    const className = typeof node.className === "string" ? node.className : "";
                    const mutedBackgroundVideo = node.tagName === "VIDEO" &&
                        node.hasAttribute("muted") &&
                        !node.hasAttribute("controls") &&
                        /background/i.test(className);
                    return !mutedBackgroundVideo;
                }
            ],
            infoUrl: brw.i18n.getMessage("patternAutoplay_infoUrl"),
            info: brw.i18n.getMessage("patternAutoplay_info"),
            languages: [
                "en",
                "de"
            ]
        },
        {
            /**
             * Countdown Pattern.
             * Countdown patterns induce (truthfully or falsely) the impression that a product or service is only available for a certain period of time.
             * This is illustrated through a running clock or a lapsing bar.
             * You can watch as the desired good slips away.
             */
            name: brw.i18n.getMessage("patternCountdown_name"),
            className: "countdown",
            detectionFunctions: [
                function (node, nodeOld) {
                    return isCountdownCandidateNode(node, nodeOld);
                }
            ],
            infoUrl: brw.i18n.getMessage("patternCountdown_infoUrl"),
            info: brw.i18n.getMessage("patternCountdown_info"),
            languages: [
                "en",
                "de"
            ]
        },
        {
            /**
             * Scarcity Pattern.
             * The Scarcity Pattern induces (truthfully or falsely) the impression that goods or services are only available in limited numbers.
             * The pattern suggests: Buy quickly, otherwise the beautiful product will be gone!
             * Scarcity Patterns are also used in versions where the alleged scarcity is simply invented or
             * where it is not made clear whether the limited availability relates to the product as a whole or only to the contingent of the portal visited.
             */
            name: brw.i18n.getMessage("patternScarcity_name"),
            className: "scarcity",
            detectionFunctions: [
                function (node, nodeOld) {
                    // Return true if a match is found in the current text of the element,
                    // using a regular expression for the scarcity pattern with English words.
                    // The regular expression checks whether a number is followed by one of several keywords
                    // or alternatively if the word group 'last/final article/item' is present.
                    // The previous state of the element is not used.
                    // Example: "10 pieces available"
                    //          "99% claimed"
                    // [ \t]* instead of \s*: node.innerText inserts a real
                    // newline at every block-level boundary, so \s* would
                    // glue an unrelated number from one element (e.g. a
                    // rating count) to a scarcity verb from the next,
                    // completely unrelated one (e.g. "...39\nSold by X" ->
                    // false "39 Sold"). [ \t]* only matches same-line/same-
                    // phrase adjacency. \d+(?:[.,]\d+)?[ \t]*[Kk]?\+? handles
                    // thousands-shorthand badges like "1.2K sold" that a
                    // plain \d+ missed. Mirrors the same fix in Kali's
                    // server-side app/analysis/regex_classify.py.
                    return textPatternMatches(node, /\d+(?:[.,]\d+)?[ \t]*[Kk]?\+?[ \t]*(?:\%|pieces?|pcs\.?|pc\.?|ct\.?|items?)?[ \t]*(?:available|sold|claimed|redeemed)|(?:last|final)[ \t]*(?:article|item)/i, "scarcity");
                },
                function (node, nodeOld) {
                    // Return true if a match is found in the current text of the element,
                    // using a regular expression for the scarcity pattern with German words.
                    // The regular expression checks whether a number is followed by one of several keywords
                    // or alternatively if the word group 'last article' (`letzter\s*Artikel`) is present.
                    // The previous state of the element is not used.
                    // Example: "10 Stück verfügbar"
                    //          "99% eingelöst"
                    //          "14 Tsd. verkauft" (real bug report from a
                    //          live Amazon listing page, mistakes/scarcity
                    //          nicht alles erkannt.png — the old regex had
                    //          no room for "Tsd." between the number and
                    //          the verb, so this common German thousands
                    //          shorthand went undetected)
                    // Same [ \t]* fix as the English variant above.
                    return textPatternMatches(node, /\d+(?:[.,]\d+)?[ \t]*(?:Tsd\.?|Mio\.?)?[ \t]*(?:\%|stücke?|stk\.?)?[ \t]*(?:verfügbar|verkauft|eingelöst)|letzter[ \t]*Artikel/i, "scarcity");
                }
            ],
            infoUrl: brw.i18n.getMessage("patternScarcity_infoUrl"),
            info: brw.i18n.getMessage("patternScarcity_info"),
            languages: [
                "en",
                "de"
            ]
        },
        {
            /**
             * Social Proof Pattern.
             * Social Proof is another Dark Pattern of this category.
             * Positive product reviews or activity reports from other users are displayed directly.
             * Often, these reviews or reports are simply made up.
             * But authentic reviews or reports also influence the purchase decision through smart selection and placement.
             */
            name: brw.i18n.getMessage("patternSocialProof_name"),
            className: "social-proof",
            detectionFunctions: [
                function (node, nodeOld) {
                    // Return true if a match is found in the current text of the element,
                    // using a regular expression for the social proof pattern with English words.
                    // The regular expression checks whether a number is followed by a combination of different keywords.
                    // The previous state of the element is not used.
                    // Example: "5 other customers also bought this article"
                    //          "6 buyers have rated the following products [with 5 stars]"
                    //          "128 customers have also bought this item" (no trailing object at all)
                    // [ \t]* instead of \s* — same block-boundary-gluing fix as
                    // the Scarcity pattern above (see its comment).
                    // The trailing "this/the following product(s)" object phrase is
                    // optional (code review 2026-08-25): requiring it dropped
                    // real social-proof phrasing that never names an object
                    // ("6 buyers have rated it 5 stars") and drifted out of sync
                    // with the simpler, tested pattern in
                    // app/analysis/regex_classify.py.
                    return textPatternMatches(node, /\d+[ \t]*(?:other)?[ \t]*(?:customers?|clients?|buyers?|users?|shoppers?|purchasers?|people)[ \t]*(?:have[ \t]+)?[ \t]*(?:(?:also[ \t]*)?(?:bought|purchased|ordered)|(?:rated|reviewed))(?:[ \t]*(?:this|the[ \t]*following)[ \t]*(?:product|article|item)s?)?/i, "social-proof");
                },
                function (node, nodeOld) {
                    // Return true if a match is found in the current text of the element,
                    // using a regular expression for the social proof pattern with German words.
                    // The regular expression checks whether a number is followed by a combination of different keywords.
                    // The previous state of the element is not used.
                    // Example: "5 andere Kunden kauften auch diesen Artikel"
                    //          "6 Käufer*innen haben folgende Produkte [mit 5 Sternen bewertet]"
                    //          "128 Kunden haben auch gekauft" (no trailing object at all)
                    // Same [ \t]* fix as the English variant above.
                    // Trailing "diese(n)/folgende(n) Produkte/Artikel" object
                    // phrase made optional (code review 2026-08-25), same reason
                    // as the English variant — real German phrasing like "haben
                    // auch gekauft" doesn't always name an object, and requiring
                    // one drifted out of sync with app/analysis/regex_classify.py.
                    return textPatternMatches(node, /\d+[ \t]*(?:andere)?[ \t]*(?:Kunden?|Käufer|Besteller|Nutzer|Leute|Person(?:en)?)(?:(?:[ \t]*\/[ \t]*)?[_\-\*]?innen)?[ \t]*(?:(?:kauften|bestellten|haben)[ \t]*(?:auch|ebenfalls)?|(?:bewerteten|rezensierten))(?:[ \t]*(?:diese[ns]?|(?:den|die|das)?[ \t]*folgenden?)[ \t]*(?:Produkte?|Artikel))?/i, "social-proof");
                }
            ],
            infoUrl: brw.i18n.getMessage("patternSocialProof_infoUrl"),
            info: brw.i18n.getMessage("patternSocialProof_info"),
            languages: [
                "en",
                "de"
            ]
        },
        {
            /**
             * Forced Continuity Pattern (adapted to German web pages).
             * The Forced Continuity pattern automatically renews free or low-cost trial subscriptions - but for a fee or at a higher price.
             * The design trick is that the order form visually suggests that there is no charge and conceals the (automatic) follow-up costs.
             */
            name: brw.i18n.getMessage("patternForcedContinuity_name"),
            className: "forced-continuity",
            detectionFunctions: [
                function (node, nodeOld) {
                    // Return true if a match is found in the current text of the element,
                    // using multiple regular expressions for the forced proof continuity with English words.
                    // The regular expressions check if one of three combinations of a price specification
                    // in Euro, Dollar or Pound and the specification of a month is present.
                    // The previous state of the element is not used.
                    if (textPatternMatches(node, /(?:(?:€|EUR|GBP|£|\$|USD)\s*\d+(?:\.\d{2})?|\d+(?:\.\d{2})?\s*(?:euros?|€|EUR|GBP|£|pounds?(?:\s*sterling)?|\$|USD|dollars?))\s*(?:(?:(?:per|\/|a)\s*month)|(?:p|\/)m)\s*(?:after|from\s*(?:month|day)\s*\d+)/i, "forced-continuity")) {
                        // Example: "$10.99/month after"
                        //          "11 GBP a month from month 4"
                        return true;
                    }
                    if (textPatternMatches(node, /(?:(?:€|EUR|GBP|£|\$|USD)\s*\d+(?:\.\d{2})?|\d+(?:\.\d{2})?\s*(?:euros?|€|EUR|GBP|£|pounds?(?:\s*sterling)?|\$|USD|dollars?))\s*(?:after\s*(?:the)?\s*\d+(?:th|nd|rd|th)?\s*(?:months?|days?)|from\s*(?:month|day)\s*\d+)/i, "forced-continuity")) {
                        // Example: "$10.99 after 12 months"
                        //          "11 GBP from month 4"
                        return true;
                    }
                    if (textPatternMatches(node, /(?:after\s*that|then|afterwards|subsequently)\s*(?:(?:€|EUR|GBP|£|\$|USD)\s*\d+(?:\.\d{2})?|\d+(?:\.\d{2})?\s*(?:euros?|€|EUR|GBP|£|pounds?(?:\s*sterling)?|\$|USD|dollars?))\s*(?:(?:(?:per|\/|a)\s*month)|(?:p|\/)m)/i, "forced-continuity")) {
                        // Example: "after that $23.99 per month"
                        //          "then GBP 10pm"
                        return true;
                    }
                    if (textPatternMatches(node, /after\s*(?:the)?\s*\d+(?:th|nd|rd|th)?\s*months?\s*(?:only|just)?\s*(?:(?:€|EUR|GBP|£|\$|USD)\s*\d+(?:\.\d{2})?|\d+(?:\.\d{2})?\s*(?:euros?|€|EUR|GBP|£|pounds?(?:\s*sterling)?|\$|USD|dollars?))/i, "forced-continuity")) {
                        // Example: "after the 24th months only €23.99"
                        //          "after 6 months $10"
                        return true;
                    }
                    // Return `false` if no regular expression matches.
                    return false;
                },
                function (node, nodeOld) {
                    // Return true if a match is found in the current text of the element,
                    // using multiple regular expressions for the forced proof continuity with German words.
                    // The regular expressions check if one of three combinations of a price specification
                    // in Euro and the specification of a month is present.
                    // The previous state of the element is not used.
                    if (textPatternMatches(node, /\d+(?:,\d{2})?\s*(?:Euro|€)\s*(?:(?:pro|im|\/)\s*Monat)?\s*(?:ab\s*(?:dem)?\s*\d+\.\s*Monat|nach\s*\d+\s*(?:Monaten|Tagen)|nach\s*(?:einem|1)\s*Monat)/i, "forced-continuity")) {
                        // Example: "10,99 Euro pro Monat ab dem 12. Monat"
                        //          "11€ nach 30 Tagen"
                        return true;
                    }
                    if (textPatternMatches(node, /(?:anschließend|danach)\s*\d+(?:,\d{2})?\s*(?:Euro|€)\s*(?:pro|im|\/)\s*Monat/i, "forced-continuity")) {
                        // Example: "anschließend 23,99€ pro Monat"
                        //          "danach 10 Euro/Monat"
                        return true;
                    }
                    if (textPatternMatches(node, /\d+(?:,\d{2})?\s*(?:Euro|€)\s*(?:pro|im|\/)\s*Monat\s*(?:anschließend|danach)/i, "forced-continuity")) {
                        // Example: "23,99€ pro Monat anschließend"
                        //          "10 Euro/Monat danach"
                        return true;
                    }
                    if (textPatternMatches(node, /ab(?:\s*dem)?\s*\d+\.\s*Monat(?:\s*nur)?\s*\d+(?:,\d{2})?\s*(?:Euro|€)/i, "forced-continuity")) {
                        // Example: "ab dem 24. Monat nur 23,99 Euro"
                        //          "ab 6. Monat 9,99€"
                        return true;
                    }
                    // Return `false` if no regular expression matches.
                    return false;
                }
            ],
            infoUrl: brw.i18n.getMessage("patternForcedContinuity_infoUrl"),
            info: brw.i18n.getMessage("patternForcedContinuity_info"),
            languages: [
                "en",
                "de"
            ]
        },
        {
            /**
             * Pre-ticked Box Pattern.
             * A checkbox that is checked by default, tricking the user into
             * consenting to something (e.g. a newsletter) without an active choice.
             * Ported from Kali's app/analysis/heuristics.py:find_preticked_checkboxes.
             */
            name: brw.i18n.getMessage("patternPreTickedBox_name"),
            className: "pre-ticked-box",
            detectionFunctions: [
                function (node, nodeOld) {
                    if (node.tagName !== "INPUT" || node.type !== "checkbox" || !node.checked) {
                        return false;
                    }
                    if (node.disabled) {
                        return false;
                    }

                    function labelTextFor(checkbox) {
                        if (checkbox.id) {
                            const label = checkbox.getRootNode().querySelector(`label[for="${checkbox.id}"]`);
                            if (label) {
                                return label.innerText;
                            }
                        }
                        const parentLabel = checkbox.closest("label");
                        return parentLabel ? parentLabel.innerText : "";
                    }

                    const haystack = [
                        labelTextFor(node),
                        node.id || "",
                        node.name || "",
                        node.className || "",
                        node.getAttribute("aria-label") || "",
                    ].join(" ");
                    const parents = [];
                    let parent = node.parentElement;
                    while (parent && parents.length < 3) {
                        if (["FORM", "FIELDSET", "SECTION", "DIV"].includes(parent.tagName)) {
                            parents.push([
                                parent.id || "",
                                parent.className || "",
                                parent.getAttribute("aria-label") || "",
                                parent.tagName === "FORM" ? "" : (parent.innerText || "").slice(0, 300),
                            ].join(" "));
                        }
                        parent = parent.parentElement;
                    }
                    const fullHaystack = [haystack, ...parents].join(" ");
                    const cookieFieldRe = /\b(cookie\w*|cookies|consent\w*|privacy|datenschutz)\b/i;
                    const requiredCookieRe = /\b(technisch notwendig|notwendig|necessary|essential|obligatory|erforderlich|nicht abwählbar|nicht abwaehlbar|always active|immer aktiv)\b/i;
                    if (cookieFieldRe.test(fullHaystack) && requiredCookieRe.test(fullHaystack)) {
                        return false;
                    }
                    const pretickedContextRe = /\b(newsletter|marketing|werbung|angebote|promotion|promotions|email|e-mail|sms|tracking|cookie\w*|cookies|consent\w*|einwilligung|zustimmung|datenschutz|privacy|agb|terms|zusatz|addon|add-on|extra|versicherung|warranty|garantie|schutzbrief|abo|subscription|subscribe|kostenpflichtig|gebühr|gebuehr|charge|fee|checkout|kasse|bestellung)\b/i;
                    if (!pretickedContextRe.test(fullHaystack)) {
                        return false;
                    }
                    const passiveControlRe = /\b(toggle|switch|filter|sort|calculator|rechner|roi|billing[-_\s]?cycle)\b/i;
                    const explicitConsentOrAddonRe = /\b(newsletter|marketing|werbung|tracking|cookie\w*|consent\w*|einwilligung|zustimmung|datenschutz|privacy|agb|terms|zusatz|addon|add-on|extra|versicherung|warranty|garantie|schutzbrief|kostenpflichtig|gebühr|gebuehr|charge|fee)\b/i;
                    return !(passiveControlRe.test(fullHaystack) && !explicitConsentOrAddonRe.test(fullHaystack));
                }
            ],
            infoUrl: brw.i18n.getMessage("patternPreTickedBox_infoUrl"),
            info: brw.i18n.getMessage("patternPreTickedBox_info"),
            languages: [
                "en",
                "de"
            ]
        },
        {
            /**
             * Trick Questions Pattern.
             * Adjacent checkboxes whose labels switch negation polarity (one
             * phrased as opt-in, the next as opt-out), so a consistent-looking
             * checkbox list actually means the opposite of what a quick scan suggests.
             * Ported from Kali's app/analysis/heuristics.py:find_trick_questions.
             */
            name: brw.i18n.getMessage("patternTrickQuestions_name"),
            className: "trick-questions",
            detectionFunctions: [
                function (node, nodeOld) {
                    if (node.tagName !== "INPUT" || node.type !== "checkbox") {
                        return false;
                    }
                    /**
                     * Regular expression for negation keywords, mirroring
                     * app/analysis/heuristics.py's _NEGATION_KEYWORDS.
                     * @constant
                     */
                    const negationRe = /\b(nicht|kein|keine|ohne|niemals|verzicht\w*)|\b(not|don't|do not)\b/i;
                    const trickContextRe = /\b(newsletter|marketing|promo(?:tion)?s?|angebote?|werbung|werbe|tracking|kontakt(?:ieren)?|contact|sms|e-?mail|emails?|abonnieren|subscribe|einwilligung|consent)\b/i;
                    const cookieFieldRe = /\b(cookie\w*|cookies|consent\w*|privacy|datenschutz)\b/i;
                    const requiredCookieRe = /\b(technisch notwendig|notwendig|necessary|essential|obligatory|erforderlich|nicht abwählbar|nicht abwaehlbar|always active|immer aktiv)\b/i;

                    function labelTextFor(checkbox) {
                        if (checkbox.id) {
                            const label = checkbox.getRootNode().querySelector(`label[for="${checkbox.id}"]`);
                            if (label) {
                                return label.innerText;
                            }
                        }
                        const parentLabel = checkbox.closest("label");
                        return parentLabel ? parentLabel.innerText : "";
                    }

                    // Find the next adjacent checkbox sibling to compare against.
                    let sibling = node.nextElementSibling;
                    while (sibling && !(sibling.tagName === "INPUT" && sibling.type === "checkbox")) {
                        sibling = sibling.nextElementSibling;
                    }
                    if (!sibling) {
                        return false;
                    }

                    const textA = labelTextFor(node);
                    const textB = labelTextFor(sibling);
                    if (!textA || !textB) {
                        return false;
                    }
                    const haystackA = [textA, node.id || "", node.name || "", node.className || ""].join(" ");
                    const haystackB = [textB, sibling.id || "", sibling.name || "", sibling.className || ""].join(" ");
                    if ((cookieFieldRe.test(haystackA) && requiredCookieRe.test(haystackA)) ||
                        (cookieFieldRe.test(haystackB) && requiredCookieRe.test(haystackB))) {
                        return false;
                    }
                    return (negationRe.test(textA) !== negationRe.test(textB)) && trickContextRe.test(`${textA} ${textB}`);
                },
                function (node, nodeOld) {
                    // Single checkbox whose own label explicitly states that
                    // NOT checking it results in default consent — e.g.
                    // Mailchimp's sign-up checkbox: "I don't want to receive
                    // emails... By not checking the box, I agree to be
                    // opted in by default." Structurally different from the
                    // adjacent-pair check above (this is one checkbox,
                    // alone, unchecked) and from pre-ticked-box (this one
                    // is never checked() — the trick is purely in the
                    // wording). Deliberately narrow (both hint groups must
                    // co-occur): a plain opt-out checkbox never needs to
                    // spell out its own default consequence — doing so is
                    // itself the tell. Port of Kali's
                    // app/analysis/heuristics.py:find_default_consent_checkboxes.
                    if (node.tagName !== "INPUT" || node.type !== "checkbox") {
                        return false;
                    }
                    const notCheckingRe = /not checking|don't check|do not check|not check the box|nicht ankreuzt|nicht anklickst|nicht aktivierst|nicht markierst/i;
                    const defaultConsentRe = /by default|automatically opted in|automatically subscribed|opted in by default|automatisch angemeldet|automatisch abonniert|standardmäßig|per voreinstellung|voreingestellt/i;

                    function labelTextFor(checkbox) {
                        if (checkbox.id) {
                            const label = checkbox.getRootNode().querySelector(`label[for="${checkbox.id}"]`);
                            if (label) {
                                return label.innerText;
                            }
                        }
                        const parentLabel = checkbox.closest("label");
                        return parentLabel ? parentLabel.innerText : "";
                    }

                    const text = labelTextFor(node);
                    return !!text && notCheckingRe.test(text) && defaultConsentRe.test(text);
                }
            ],
            infoUrl: brw.i18n.getMessage("patternTrickQuestions_infoUrl"),
            info: brw.i18n.getMessage("patternTrickQuestions_info"),
            languages: [
                "en",
                "de"
            ]
        },
        {
            /**
             * Decoy Pricing Pattern.
             * A pricing tier priced only slightly more than a neighboring
             * tier but offering disproportionately more value, nudging the
             * user toward the pricier option (asymmetric dominance).
             * Ported from Kali's app/analysis/heuristics.py:find_decoy_pricing.
             * Only German price formats are supported (see the Python
             * counterpart for the reasoning).
             */
            name: brw.i18n.getMessage("patternDecoyPricing_name"),
            className: "decoy-pricing",
            detectionFunctions: [
                function (node, nodeOld) {
                    /**
                     * Regular expression for German price formats
                     * (9,99€ / € 9,99 / EUR 9,99 / 9,99 EUR).
                     * @constant
                     */
                    const priceRe = /(?:€\s?(\d{1,3}(?:\.\d{3})*,\d{2})|(\d{1,3}(?:\.\d{3})*,\d{2})\s?€|EUR\s?(\d{1,3}(?:\.\d{3})*,\d{2})|(\d{1,3}(?:\.\d{3})*,\d{2})\s?EUR)/i;

                    function tierInfo(container) {
                        // Only HTMLElement has `innerText` (e.g. SVGElement does not),
                        // and findPatternDeep visits every element node in the tree.
                        if (typeof container.innerText !== "string") {
                            return null;
                        }
                        const priceMatch = container.innerText.match(priceRe);
                        const list = container.querySelector("ul, ol");
                        if (!priceMatch || !list) {
                            return null;
                        }
                        const price = parseFloat(priceMatch[0].replace(/[^\d,]/g, "").replace(",", "."));
                        return { price: price, valueCount: list.querySelectorAll("li").length };
                    }

                    const info = tierInfo(node);
                    if (!info) {
                        return false;
                    }
                    let sibling = node.nextElementSibling;
                    while (sibling) {
                        const siblingInfo = tierInfo(sibling);
                        if (siblingInfo) {
                            const cheaper = info.price < siblingInfo.price ? info : siblingInfo;
                            const pricier = info.price < siblingInfo.price ? siblingInfo : info;
                            const priceDeltaPct = (pricier.price - cheaper.price) / cheaper.price;
                            const valueRatio = pricier.valueCount / Math.max(cheaper.valueCount, 1);
                            return priceDeltaPct <= 0.15 && valueRatio >= 3.0;
                        }
                        sibling = sibling.nextElementSibling;
                    }
                    return false;
                }
            ],
            infoUrl: brw.i18n.getMessage("patternDecoyPricing_infoUrl"),
            info: brw.i18n.getMessage("patternDecoyPricing_info"),
            languages: [
                "de"
            ]
        },
        {
            /**
             * Cookie-Banner Button Asymmetry Pattern.
             * The banner's "accept all" button is visibly larger and/or
             * higher-contrast than its "reject" button, nudging the user
             * toward consenting. Ported from Kali's
             * app/analysis/visual.py:compute_button_asymmetry, fed by
             * scripts/consent.js:checkCookieBanner (real per-site accept/
             * reject selectors resolved from the vendored Consent-O-Matic
             * rules, scripts/data/consent-rules.json).
             *
             * This pattern is never detected via the per-node findPatternDeep
             * walk below — detection happens once per patternHighlighting()
             * run in applyCookieBannerChecks() (scripts/content.js), which
             * resolves the real accept/reject elements directly and
             * class-tags them. The no-op detection function below exists only
             * to keep validatePatternConfig() satisfied (non-empty
             * detectionFunctions, 2-param function) so this pattern still
             * shows up in getPatternsResults()'s popup counts once
             * applyCookieBannerChecks() has tagged elements.
             */
            name: brw.i18n.getMessage("patternCookieBannerAsymmetry_name"),
            className: "cookie-banner-asymmetry",
            detectionFunctions: [
                function (node, nodeOld) {
                    return false;
                }
            ],
            infoUrl: brw.i18n.getMessage("patternCookieBannerAsymmetry_infoUrl"),
            info: brw.i18n.getMessage("patternCookieBannerAsymmetry_info"),
            languages: [
                "en",
                "de"
            ]
        },
        {
            /**
             * Missing Reject Option Pattern.
             * A detected cookie banner offers no equivalent one-click way to
             * reject non-essential cookies. Ported from Kali's
             * app/crawler.py:apply_consent_rules's reject_option_missing
             * logic. Same no-op-detectionFunctions rationale as the
             * cookie-banner-asymmetry pattern above — see that comment.
             */
            name: brw.i18n.getMessage("patternCookieBannerMissingReject_name"),
            className: "cookie-banner-missing-reject",
            detectionFunctions: [
                function (node, nodeOld) {
                    return false;
                }
            ],
            infoUrl: brw.i18n.getMessage("patternCookieBannerMissingReject_infoUrl"),
            info: brw.i18n.getMessage("patternCookieBannerMissingReject_info"),
            languages: [
                "en",
                "de"
            ]
        },
        {
            /**
             * Sneaking into Basket Pattern (UWG-Anhang Nr. 2).
             * Items the user never explicitly chose end up in the basket —
             * detected cross-page by comparing the tracked cart-item count
             * (badge + add-to-cart clicks, scripts/sneak_basket.js) against
             * the item count actually shown at checkout. Imperative
             * detection like the cookie-banner patterns above (cross-page
             * state can't be a single-node predicate), hence the no-op
             * detection function.
             */
            name: brw.i18n.getMessage("patternSneakingIntoBasket_name"),
            className: "sneaking-into-basket",
            detectionFunctions: [
                function (node, nodeOld) {
                    return false;
                }
            ],
            infoUrl: brw.i18n.getMessage("patternSneakingIntoBasket_infoUrl"),
            info: brw.i18n.getMessage("patternSneakingIntoBasket_info"),
            languages: [
                "de"
            ]
        }
    ]
}

/**
 * Checks if the `patternConfig` is valid.
 * @returns {boolean} `true` if the `patternConfig` is valid, `false` otherwise.
 */
function validatePatternConfig() {
    // Create an array with the names of the configured patterns.
    let names = patternConfig.patterns.map(p => p.name);
    // Check if there are duplicate names.
    if ((new Set(names)).size !== names.length) {
        // If there are duplicate names, the configuration is invalid.
        return false;
    }
    // Check every single configured pattern for validity.
    for (let pattern of patternConfig.patterns) {
        // Ensure that the name is a non-empty string.
        if (!pattern.name || typeof pattern.name !== "string") {
            return false;
        }
        // Ensure that the class name is a non-empty string.
        if (!pattern.className || typeof pattern.className !== "string") {
            return false;
        }
        // Ensure that the detection functions are a non-empty array.
        if (!Array.isArray(pattern.detectionFunctions) || pattern.detectionFunctions.length <= 0) {
            return false;
        }
        // Check every single configured detection function for validity.
        for (let detectionFunc of pattern.detectionFunctions) {
            // Ensure that the detection function is a function with two arguments.
            if (typeof detectionFunc !== "function" || detectionFunc.length !== 2) {
                return false;
            }
        }
        // Ensure that the info URL is a non-empty string.
        if (!pattern.infoUrl || typeof pattern.infoUrl !== "string") {
            return false;
        }
        // Ensure that the info/explanation is a non-empty string.
        if (!pattern.info || typeof pattern.info !== "string") {
            return false;
        }
        // Ensure that the languages are a non-empty array.
        if (!Array.isArray(pattern.languages) || pattern.languages.length <= 0) {
            return false;
        }
        // Check every single language for being a non-empty string.
        for (let language of pattern.languages) {
            // Ensure that the language is a non-empty string.
            if (!language || typeof language !== "string") {
                return false;
            }
        }
    }
    // If all checks have been passed successfully, the configuration is valid and `true` is returned.
    return true;
}

/**
 * @type {boolean} `true` if the `patternConfig` is valid, `false` otherwise.
 */
export const patternConfigIsValid = validatePatternConfig();

/**
 * Prefix for all CSS classes that are added to elements on websites by the extension.
 * @constant
 */
export const extensionClassPrefix = "__ph__";

/**
 * The class that is added to elements detected as patterns.
 * Elements with this class get a black border from the CSS styles.
 * @constant
 */
export const patternDetectedClassName = extensionClassPrefix + "pattern-detected";

/**
 * A class for the elements created as shadows for pattern elements
 * for displaying individual elements using the popup.
 */
export const currentPatternClassName = extensionClassPrefix + "current-pattern";

/**
 * A list of HTML tags that should be ignored during pattern detection.
 * The elements with these tags are removed from the DOM copy. iframe/embed/
 * object are excluded so they're never themselves treated as pattern-
 * bearing nodes — their actual (same-origin) contents are separately
 * skipped per-frame via WIDGET_IFRAME_HOSTS in content.js when they belong
 * to a known third-party widget; cross-origin frame contents are already
 * unreachable regardless (browser same-origin policy).
 */
export const tagBlacklist = ["script", "style", "noscript", "iframe", "embed", "object"];

/**
 * When false (default), detected elements get no visible border — only the
 * internal tracking classes used by the popup/report are applied. Flip to
 * true only for local debugging.
 */
export const SHOW_DEBUG_BOXES = false;

/**
 * Class that draws the visible debug border around a detected element (see
 * stylesheets/style.css). Kept separate from patternDetectedClassName so the
 * always-on functional tracking class never carries a visual side effect.
 */
export const debugBoxClassName = extensionClassPrefix + "debug-box";

/**
 * Maps each pattern's `className` to the German legal norm it violates, for
 * the PDF report (report/report.js). Mirrors Kali's server-side NORM_MAP
 * (app/compliance.py) for the same 8 pattern types this extension detects.
 * @constant
 * @type {Object.<string, string>}
 */
export const normMap = {
    "countdown": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "scarcity": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "social-proof": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "forced-continuity": "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB",
    "pre-ticked-box": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "autoplay": "Art. 25 DSA",
    "trick-questions": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "decoy-pricing": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "cookie-banner-asymmetry": "Art. 25 DSA",
    "cookie-banner-missing-reject": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "sneaking-into-basket": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3 Nr. 2",
};
