import http from "node:http";
import assert from "node:assert/strict";

globalThis.chrome = { i18n: { getMessage: (key) => key } };

const constantsPath = new URL("../vendor/pattern-highlighter/chrome/scripts/constants.js", import.meta.url);
const constantsLike = await import(constantsPath.href);
const { patternConfig } = constantsLike;
const countdown = patternConfig.patterns.find((pattern) => pattern.className === "countdown");
assert.ok(countdown, "countdown pattern exists");

const templates = [
    {
        name: "reset-offer-remains",
        expected: true,
        html: () => `<main><h1>Flash sale</h1><p>Hurry, offer ends soon. Buy before the timer runs out.</p><p>Discount price: 19,99 €</p><button>Buy now</button><div id="countdown">02:00</div><script>let target = Date.now() + 120000; function tick(){ let remaining = target - Date.now(); if (remaining <= 0) { target = Date.now() + 120000; remaining = target - Date.now(); } document.getElementById("countdown").innerText = "02:00"; } setInterval(tick, 1000);</script></main>`,
        after: () => `<main><h1>Flash sale</h1><p>Hurry, offer ends soon. Buy before the timer runs out.</p><p>Discount price: 19,99 €</p><button>Buy now</button><div id="countdown">02:00</div></main>`,
    },
    {
        name: "reset-german-offer-remains",
        expected: true,
        html: () => `<section class="product"><h2>Sommer Deal</h2><p>Nur heute: Rabatt auf dieses Produkt.</p><p>Preis: 29,99 €</p><button>In den Warenkorb</button><div class="countdown-timer">Angebot endet in: 01:30</div><script>let target = Date.now() + 90000; setInterval(() => { if (Date.now() > target) target = Date.now() + 90000; document.querySelector(".countdown-timer").textContent = "Angebot endet in: 01:30"; }, 1000);</script></section>`,
        after: () => `<section class="product"><h2>Sommer Deal</h2><p>Nur heute: Rabatt auf dieses Produkt.</p><p>Preis: 29,99 €</p><button>In den Warenkorb</button><div class="countdown-timer">Angebot endet in: 01:30</div></section>`,
    },
    {
        name: "reset-checkout-offer-remains",
        expected: true,
        html: () => `<article><h2>Checkout discount</h2><p>Only 29 minutes remaining for this deal.</p><p>Coupon price $12.00</p><a href="/checkout">Checkout</a><div class="timer">29 minutes remaining</div><script>localStorage.setItem("deal_deadline", Date.now() + 1740000); setInterval(() => document.querySelector(".timer").textContent = "29 minutes remaining", 1000);</script></article>`,
        after: () => `<article><h2>Checkout discount</h2><p>Only 29 minutes remaining for this deal.</p><p>Coupon price $12.00</p><a href="/checkout">Checkout</a><div class="timer">29 minutes remaining</div></article>`,
    },
    {
        name: "expires-correctly",
        expected: false,
        html: () => `<main><h1>Flash sale</h1><p>Discount price: 19,99 €</p><button>Buy now</button><div id="countdown">02:00</div><script>const target = Date.now() + 120000; setInterval(() => { document.getElementById("countdown").innerText = Date.now() > target ? "Abgelaufen" : "02:00"; }, 1000);</script></main>`,
        after: () => `<main><h1>Flash sale</h1><p>Discount price: 19,99 €</p><button>Buy now</button><div id="countdown">Abgelaufen</div></main>`,
    },
    {
        name: "offer-removed-after-expiry",
        expected: false,
        html: () => `<main><h1>Flash sale</h1><p>Deal price: $15.00</p><button>Buy now</button><div id="countdown">02:00</div><script>setInterval(() => document.getElementById("countdown").innerText = "02:00", 1000);</script></main>`,
        after: () => `<main><h1>Sale ended</h1><p>This offer is no longer available.</p><div id="countdown">02:00</div></main>`,
    },
    {
        name: "event-countdown",
        expected: false,
        html: () => `<main><h1>Webinar starts in 01:10:00</h1><p>Join the conference livestream when the event begins.</p></main>`,
        after: () => `<main><h1>Webinar starts in 01:10:00</h1><p>Join the conference livestream when the event begins.</p></main>`,
    },
    { name: "plain-product", expected: false, html: () => `<main><h1>Desk lamp</h1><p>Warm dimmable light with a two-year warranty.</p><button>Add to cart</button></main>` },
    { name: "current-clock", expected: false, html: () => `<div id="clock">10:00:00</div><script>setInterval(() => { document.getElementById("clock").textContent = new Date().toLocaleTimeString(); }, 1000);</script>` },
    { name: "limited-copy-no-countdown", expected: false, html: () => `<main><h1>Seasonal pricing</h1><p>Limited time offer on annual plans, no automatic timer is used.</p></main>` },
    { name: "shipping-eta", expected: false, html: () => `<main><h1>Order tracking</h1><p>Delivery estimate: 2 days 4 hours. Shipping updates appear here.</p></main>` },
    { name: "docs-example", expected: false, html: () => `<article><h1>How countdown timers work</h1><pre>setInterval(() => render(Date.now()), 1000)</pre><p>This documentation explains timer code without selling anything.</p></article>` },
];

function stripScripts(html) {
    return html.replace(/<script\b[\s\S]*?<\/script>/gi, " ");
}

function textOnly(html) {
    return stripScripts(html).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function scriptsFrom(html) {
    const scripts = [];
    html.replace(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi, (_match, attrs, body) => {
        const src = attrs.match(/\bsrc\s*=\s*["']([^"']+)["']/i);
        scripts.push({ src: src ? src[1] : "", textContent: body || "" });
        return "";
    });
    return scripts;
}

function attrsFrom(attrText) {
    const attrs = [];
    attrText.replace(/\b([\w:-]+)(?:\s*=\s*["']([^"']*)["'])?/g, (_match, name, value = "") => {
        attrs.push({ name, value });
        return "";
    });
    return attrs;
}

function nodesFrom(html) {
    const nodes = [];
    const bodyText = textOnly(html);
    const bodyNode = {
        tagName: "BODY",
        innerText: bodyText,
        textContent: bodyText,
        attributes: [],
        dataset: {},
        parentElement: null,
        hasAttribute: () => false,
        getAttribute: () => null,
    };
    const elementRe = /<([a-z0-9-]+)\b([^>]*)>([\s\S]*?)<\/\1>/gi;
    let match;
    while ((match = elementRe.exec(stripScripts(html)))) {
        const [, tagName, attrText, body] = match;
        const attrs = attrsFrom(attrText);
        const id = attrs.find((attr) => attr.name === "id")?.value || "";
        const className = attrs.find((attr) => attr.name === "class")?.value || "";
        const innerText = body.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
        nodes.push({
            tagName: tagName.toUpperCase(),
            id,
            className,
            innerText,
            textContent: innerText,
            attributes: attrs,
            dataset: Object.fromEntries(attrs.filter((attr) => attr.name.startsWith("data-")).map((attr) => [attr.name.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase()), attr.value])),
            parentElement: bodyNode,
            hasAttribute: (name) => attrs.some((attr) => attr.name === name),
            getAttribute: (name) => attrs.find((attr) => attr.name === name)?.value || null,
        });
    }
    return nodes.length ? nodes : [bodyNode];
}

function makeStorage(entries = []) {
    const map = new Map(entries.map((entry) => [entry.key, entry.value]));
    return {
        length: entries.length,
        key: (index) => entries[index]?.key || null,
        getItem: (key) => map.get(key) ?? null,
    };
}

function caseFor(batch, index, origin) {
    const template = templates[(batch * 17 + index * 7) % templates.length];
    const path = `/batch-${batch}/page-${String(index + 1).padStart(3, "0")}-${template.name}`;
    return {
        path,
        url: origin + path,
        html: `<!doctype html><html><body>${template.html(batch, index)}</body></html>`,
        afterHtml: `<!doctype html><html><body>${(template.after || template.html)(batch, index)}</body></html>`,
        expected: template.expected,
        template: template.name,
        storage: template.storage?.() || [],
        sessionStorage: [],
        cookie: template.cookie?.() || "",
    };
}

function detect(testCase, html) {
    globalThis.__phCountdownPageEvidence = null;
    const bodyText = textOnly(html);
    globalThis.document = { body: { innerText: bodyText, textContent: bodyText }, scripts: scriptsFrom(html), cookie: testCase.cookie };
    globalThis.localStorage = makeStorage(testCase.storage);
    globalThis.sessionStorage = makeStorage(testCase.sessionStorage);
    const beforeNode = nodesFrom(html).find((node) => countdown.detectionFunctions.some((fn) => fn(node, null)));
    if (!beforeNode) {
        return false;
    }
    const beforeSignature = constantsLike.countdownOfferSignature(beforeNode);
    const afterNode = nodesFrom(testCase.afterHtml).find((node) => countdown.detectionFunctions.some((fn) => fn(node, null))) ||
        nodesFrom(testCase.afterHtml).find((node) => /countdown|timer|deadline|angebot|offer|remaining|left/i.test(`${node.id} ${node.className} ${node.innerText}`));
    if (!afterNode) {
        return false;
    }
    return constantsLike.countdownTextLooksReset(beforeNode.innerText, afterNode.innerText) &&
        constantsLike.countdownOfferStillPresent(beforeSignature, afterNode);
}

async function startServer(casesByPath) {
    const server = http.createServer((request, response) => {
        const testCase = casesByPath.get(request.url);
        if (!testCase) {
            response.writeHead(404, { "content-type": "text/plain" });
            response.end("not found");
            return;
        }
        response.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" });
        response.end(testCase.html);
    });
    await new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(0, "127.0.0.1", resolve);
    });
    return server;
}

async function runBatch(batch) {
    const casesByPath = new Map();
    const server = await startServer(casesByPath);
    const { port } = server.address();
    const origin = `http://127.0.0.1:${port}`;
    const cases = Array.from({ length: 100 }, (_value, index) => caseFor(batch, index, origin));
    for (const testCase of cases) {
        casesByPath.set(testCase.path, testCase);
    }

    try {
        const failures = [];
        for (const testCase of cases) {
            const response = await fetch(testCase.url);
            const html = await response.text();
            const actual = detect(testCase, html);
            if (actual !== testCase.expected) {
                failures.push({ url: testCase.url, template: testCase.template, expected: testCase.expected, actual });
            }
        }
        const positives = cases.filter((testCase) => testCase.expected).length;
        console.log(`Batch ${batch}: ${100 - failures.length}/100 passed, expected positives=${positives}`);
        if (failures.length) {
            console.log(JSON.stringify(failures.slice(0, 10), null, 2));
        }
        return failures;
    } finally {
        await new Promise((resolve) => server.close(resolve));
    }
}

let clean = 0;
for (let batch = 1; clean < 2; batch++) {
    const failures = await runBatch(batch);
    if (failures.length) {
        process.exit(1);
    }
    clean++;
}
console.log("Clean streak reached: 2 consecutive 100-URL batches.");
