# Site-Crawl Category-Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Dark-Pattern-Monitor from single-page scans to a site-wide
crawl that follows internal links (BFS, same domain + subdomains), routes
each visited page to one of 5 dark-pattern categories, drives a per-category
LLM interaction agent (checkout flow, cancellation flow, cookie banner,
popup dismissal), and detects 9 additional pattern types derived from a
dark-patterns taxonomy book excerpt.

**Architecture:** One shared Playwright `BrowserContext` per site scan (one
HAR file for the whole site). A BFS loop in `app/site_crawler.py` classifies
each page's category (heuristic + LLM fallback), snapshots it (DOM,
screenshot, button styles — reusing `app/crawler.py`'s existing per-page
logic, factored into a shared helper), runs the analysis pipeline, and asks
an LLM for the next interaction to take before moving to the next queued
URL. A new `pages` table sits between `scans` and `findings` so results can
be grouped by page.

**Tech Stack:** No new dependencies. Reuses Playwright, BeautifulSoup,
`anthropic`, `httpx`, `sqlite3` — all already in `requirements.txt`.

**Spec:** `docs/superpowers/specs/2026-08-19-site-crawl-category-agents-design.md`

## Global Constraints

- No new pip dependencies — every new capability (readability scoring,
  link discovery, contrast scanning) is built on stdlib + BeautifulSoup +
  Playwright, all already installed.
- Every discovered link (not the user-supplied start URL, which the route
  handler already validates) must pass through URL validation before the
  crawler navigates to it — reuse `app/url_safety.py:validate_scan_url`.
  `crawl_site` takes the validator as an injectable parameter
  (`url_validator=validate_scan_url` default) so tests can exercise
  multi-page link-following against local `file://` fixtures without
  fighting the loopback/private-IP rejection that's correct for production.
- `max_pages` is always a parameter with an environment-variable default
  (`MAX_PAGES_PER_SCAN`, default `15`) — never a hardcoded constant.
- Every finding keeps the existing shape: `pattern_type: str`,
  `target_norm: str`, `confidence_score: float (0.0-1.0)`,
  `evidence_data: dict`.
- Every new `pattern_type` string added to `app/analysis/llm_classify.py`'s
  `SYSTEM_PROMPT` enum gets a `NORM_MAP` entry and a contract-test entry in
  the SAME task/commit — this exact class of bug (prompt emits a string
  `NORM_MAP` doesn't have) already happened once in this codebase and was
  fixed; don't reintroduce it by splitting the two across tasks.
- `run_analysis` becomes `async def` in this plan (Task 8) — every existing
  caller and test must be updated in that same task, not left broken for a
  later task to fix.
- Follow existing test conventions: hermetic fixtures (`file://` URIs, no
  real network), `pytest.mark.asyncio` for async tests, `client=None` /
  `llm_client=None` dependency-injection pattern for anything that calls
  the `anthropic` SDK so tests can pass a fake.

---

### Task 1: Pages Table & Page-Scoped DB Helpers

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `insert_page(conn, scan_id: int, url: str, category: str) -> int`,
  `get_pages(conn, scan_id: int) -> list[dict]`,
  `get_page_findings(conn, page_id: int) -> list[dict]`. `insert_finding`
  gains an optional `page_id: int | None = None` fifth parameter (default
  `None`, so every existing caller keeps working unchanged).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
def test_pages_and_page_scoped_findings_roundtrip():
    from app.db import insert_page, get_pages, get_page_findings

    conn = init_db(":memory:")
    scan_id = insert_scan(conn, "https://example.com")
    page_id = insert_page(conn, scan_id, "https://example.com/checkout", "checkout_payment")
    assert isinstance(page_id, int)

    finding = {
        "pattern_type": "Trick Questions",
        "target_norm": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
        "confidence_score": 0.75,
        "evidence_data": {"selector_a": "#a", "selector_b": "#b"},
    }
    finding_id = insert_finding(conn, scan_id, finding, page_id=page_id)
    assert isinstance(finding_id, int)

    pages = get_pages(conn, scan_id)
    assert len(pages) == 1
    assert pages[0]["url"] == "https://example.com/checkout"
    assert pages[0]["category"] == "checkout_payment"

    page_findings = get_page_findings(conn, page_id)
    assert len(page_findings) == 1
    assert page_findings[0]["pattern_type"] == "Trick Questions"

    # backward compatible: existing scan-level insert (no page_id) still works
    legacy_finding = {
        "pattern_type": "Confirm Shaming",
        "target_norm": "Art. 25 DSA",
        "confidence_score": 0.8,
        "evidence_data": {},
    }
    insert_finding(conn, scan_id, legacy_finding)
    assert len(get_findings(conn, scan_id)) == 2


def test_init_db_adds_page_id_column_idempotently(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn1 = init_db(db_path)
    conn1.close()
    conn2 = init_db(db_path)  # second run on the same file must not raise
    cols = [row[1] for row in conn2.execute("PRAGMA table_info(findings)")]
    assert "page_id" in cols
    conn2.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'insert_page'`

- [ ] **Step 3: Implement the schema migration and new helpers**

Replace the top of `app/db.py` (the `SCHEMA` string and `init_db`) with:

```python
import sqlite3
import json

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL REFERENCES scans(id),
    url TEXT NOT NULL,
    category TEXT NOT NULL,
    crawled_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL REFERENCES scans(id),
    pattern_type TEXT NOT NULL,
    target_norm TEXT NOT NULL,
    confidence_score REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _ensure_page_id_column(conn: sqlite3.Connection) -> None:
    """ALTER TABLE ADD COLUMN isn't idempotent like CREATE TABLE IF NOT
    EXISTS — guard it so init_db can run safely on every app startup."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(findings)")]
    if "page_id" not in cols:
        conn.execute("ALTER TABLE findings ADD COLUMN page_id INTEGER REFERENCES pages(id)")


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_page_id_column(conn)
    conn.commit()
    return conn


def insert_scan(conn: sqlite3.Connection, url: str) -> int:
    cur = conn.execute("INSERT INTO scans (url) VALUES (?)", (url,))
    conn.commit()
    return cur.lastrowid


def insert_page(conn: sqlite3.Connection, scan_id: int, url: str, category: str) -> int:
    cur = conn.execute(
        "INSERT INTO pages (scan_id, url, category) VALUES (?, ?, ?)",
        (scan_id, url, category),
    )
    conn.commit()
    return cur.lastrowid


def get_pages(conn: sqlite3.Connection, scan_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM pages WHERE scan_id = ? ORDER BY id", (scan_id,)
    ).fetchall()
    return [dict(row) for row in rows]


def insert_finding(conn: sqlite3.Connection, scan_id: int, finding: dict, page_id: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO findings (scan_id, pattern_type, target_norm, confidence_score, evidence_json, page_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            scan_id,
            finding["pattern_type"],
            finding["target_norm"],
            finding["confidence_score"],
            json.dumps(finding.get("evidence_data", {})),
            page_id,
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_findings(conn: sqlite3.Connection, scan_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM findings WHERE scan_id = ? ORDER BY id", (scan_id,)
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["evidence_data"] = json.loads(d.pop("evidence_json"))
        result.append(d)
    return result


def get_page_findings(conn: sqlite3.Connection, page_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM findings WHERE page_id = ? ORDER BY id", (page_id,)
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["evidence_data"] = json.loads(d.pop("evidence_json"))
        result.append(d)
    return result


def get_scan(conn: sqlite3.Connection, scan_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    return dict(row) if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (all tests, including the pre-existing roundtrip test)

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: pages table and page-scoped finding helpers"
```

---

### Task 2: Same-Domain Link Discovery

**Files:**
- Create: `app/site_crawler.py`
- Test: `tests/test_site_crawler.py`

**Interfaces:**
- Consumes: nothing
- Produces: `discover_links(dom_html: str, base_url: str, allowed_hosts: set[str]) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_site_crawler.py
from app.site_crawler import discover_links

DOM_WITH_LINKS = """
<html><body>
<a href="/products">Produkte</a>
<a href="https://checkout.example.com/pay">Zur Kasse</a>
<a href="https://external-tracker.com/pixel">Tracking</a>
<a href="#section">Anker</a>
<a href="mailto:info@example.com">Mail</a>
<a href="/products">Duplikat</a>
</body></html>
"""


def test_discover_links_filters_to_allowed_domain_and_subdomains():
    links = discover_links(DOM_WITH_LINKS, "https://www.example.com/", {"example.com"})
    assert "https://www.example.com/products" in links
    assert "https://checkout.example.com/pay" in links
    assert not any("external-tracker.com" in l for l in links)
    assert not any(l.startswith("#") for l in links)
    assert not any(l.startswith("mailto:") for l in links)


def test_discover_links_dedupes():
    links = discover_links(DOM_WITH_LINKS, "https://www.example.com/", {"example.com"})
    assert links.count("https://www.example.com/products") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_site_crawler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.site_crawler'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/site_crawler.py
import logging
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def discover_links(dom_html: str, base_url: str, allowed_hosts: set[str]) -> list[str]:
    """Extracts internal navigation links from a page. Filters to
    `allowed_hosts` (exact match or subdomain), drops anchors/mailto/tel/js
    links, and dedupes. Does NOT enforce http(s)-only or SSRF safety — that
    is `app.url_safety.validate_scan_url`'s job, applied by the caller
    before navigating to any of these URLs."""
    soup = BeautifulSoup(dom_html, "html.parser")
    seen: set[str] = set()
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href).split("#")[0]
        parsed = urlparse(absolute)
        host = parsed.hostname or ""
        if not any(host == h or host.endswith("." + h) for h in allowed_hosts):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)
    return links
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_site_crawler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/site_crawler.py tests/test_site_crawler.py
git commit -m "feat: same-domain link discovery for site-wide crawling"
```

---

### Task 3: Page-Category Classification

**Files:**
- Modify: `app/site_crawler.py`
- Test: `tests/test_site_crawler.py`

**Interfaces:**
- Consumes: nothing
- Produces: `PAGE_CATEGORIES: tuple[str, ...]`,
  `classify_page_category(url: str, dom_html: str, llm_client=None) -> str`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_site_crawler.py`:

```python
from app.site_crawler import classify_page_category


def test_classify_page_category_by_url_keyword():
    assert classify_page_category("https://shop.example.com/checkout", "<h1>Kasse</h1>") == "checkout_payment"
    assert classify_page_category("https://shop.example.com/konto/abo", "<h1>Mein Abo</h1>") == "account_subscription"
    assert classify_page_category("https://shop.example.com/p/sneaker-123", "<h1>Sneaker</h1>") == "product_category"


def test_classify_page_category_falls_back_to_other_without_llm():
    assert classify_page_category("https://shop.example.com/about-us", "<h1>Über uns</h1>") == "other"


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, response_text):
        self._response_text = response_text

    def create(self, **kwargs):
        return _FakeMessage(self._response_text)


class _FakeClient:
    def __init__(self, response_text):
        self.messages = _FakeMessages(response_text)


def test_classify_page_category_uses_llm_fallback_for_ambiguous_pages():
    client = _FakeClient("popup_leadform")
    result = classify_page_category("https://shop.example.com/about-us", "<h1>Über uns</h1>", llm_client=client)
    assert result == "popup_leadform"


def test_classify_page_category_llm_failure_falls_back_to_other():
    class _BrokenClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("API down")

    result = classify_page_category("https://shop.example.com/about-us", "<h1>Über uns</h1>", llm_client=_BrokenClient())
    assert result == "other"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_site_crawler.py -v`
Expected: FAIL with `ImportError: cannot import name 'classify_page_category'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/site_crawler.py`:

```python
PAGE_CATEGORIES = (
    "cookie_consent",
    "checkout_payment",
    "product_category",
    "account_subscription",
    "popup_leadform",
    "other",
)

_CATEGORY_KEYWORDS = {
    "checkout_payment": ("checkout", "kasse", "warenkorb", "cart", "bestellung", "payment", "zahlung"),
    "account_subscription": ("account", "konto", "abo", "subscription", "kündig", "cancel"),
    "product_category": ("product", "produkt", "/p/", "kategorie", "category"),
}


def _llm_classify_category(url: str, dom_html: str, client) -> str:
    import re

    text_sample = re.sub(r"<[^>]+>", " ", dom_html)[:1500]
    prompt = (
        "Klassifiziere folgende Webseite in genau eine Kategorie: "
        "cookie_consent, checkout_payment, product_category, account_subscription, "
        "popup_leadform, other. Antworte NUR mit dem Kategorie-Namen, nichts sonst.\n\n"
        f"URL: {url}\n\nSeiteninhalt (Auszug): {text_sample}"
    )
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=20,
        messages=[{"role": "user", "content": prompt}],
    )
    result = response.content[0].text.strip().lower()
    return result if result in PAGE_CATEGORIES else "other"


def classify_page_category(url: str, dom_html: str, llm_client=None) -> str:
    haystack = url.lower()
    soup = BeautifulSoup(dom_html, "html.parser")
    heading = soup.find(["h1", "h2"])
    if heading:
        haystack += " " + heading.get_text(strip=True).lower()

    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return category

    if llm_client is not None:
        try:
            return _llm_classify_category(url, dom_html, llm_client)
        except Exception as exc:  # noqa: BLE001 - deliberate broad catch, LLM call
            logger.warning("LLM category classification failed, using 'other': %s", exc)

    return "other"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_site_crawler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/site_crawler.py tests/test_site_crawler.py
git commit -m "feat: heuristic + LLM-fallback page-category classification"
```

---

### Task 4: New DOM Heuristics — Trick Questions & Autoplay Media

**Files:**
- Modify: `app/analysis/heuristics.py`
- Test: `tests/test_heuristics.py`

**Interfaces:**
- Consumes: nothing
- Produces: `find_trick_questions(dom_html: str) -> list[dict]`,
  `find_autoplay_media(dom_html: str) -> list[dict]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_heuristics.py`:

```python
from app.analysis.heuristics import find_trick_questions, find_autoplay_media

TRICK_QUESTION_HTML = """
<form>
  <input type="checkbox" id="newsletter">
  <label for="newsletter">Bitte ankreuzen, wenn Sie Angebote erhalten möchten</label>
  <input type="checkbox" id="tracking" checked>
  <label for="tracking">Bitte NICHT ankreuzen, wenn Sie Tracking ablehnen</label>
</form>
"""

CONSISTENT_CHECKBOXES_HTML = """
<form>
  <input type="checkbox" id="a"><label for="a">Newsletter abonnieren</label>
  <input type="checkbox" id="b"><label for="b">SMS-Updates abonnieren</label>
</form>
"""

AUTOPLAY_HTML = """
<video id="hero-video" autoplay></video>
<audio id="bg-audio" autoplay></audio>
<video id="manual-video"></video>
"""


def test_find_trick_questions_flags_opposite_polarity_labels():
    findings = find_trick_questions(TRICK_QUESTION_HTML)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Trick Questions"
    assert findings[0]["evidence_data"]["selector_a"] == "#newsletter"
    assert findings[0]["evidence_data"]["selector_b"] == "#tracking"


def test_find_trick_questions_ignores_consistent_polarity():
    assert find_trick_questions(CONSISTENT_CHECKBOXES_HTML) == []


def test_find_autoplay_media_flags_autoplay_attribute():
    findings = find_autoplay_media(AUTOPLAY_HTML)
    selectors = {f["evidence_data"]["selector"] for f in findings}
    assert selectors == {"#hero-video", "#bg-audio"}
    assert all(f["pattern_type"] == "Exploiting Addiction (Autoplay)" for f in findings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_heuristics.py -v`
Expected: FAIL with `ImportError: cannot import name 'find_trick_questions'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/analysis/heuristics.py`:

```python
_NEGATION_KEYWORDS = ("nicht", "kein", "keine", "not", "don't", "do not")


def _label_text_for(soup, box) -> str:
    box_id = box.get("id")
    if box_id:
        label = soup.find("label", {"for": box_id})
        if label:
            return label.get_text(strip=True)
    parent_label = box.find_parent("label")
    return parent_label.get_text(strip=True) if parent_label else ""


def find_trick_questions(dom_html: str) -> list[dict]:
    """Flags adjacent checkbox pairs whose labels switch polarity (one
    phrased as opt-in, the next as opt-out) — the classic "trick question"
    pattern where a consistent-looking checkbox list actually means the
    opposite of what a quick scan suggests."""
    soup = BeautifulSoup(dom_html, "html.parser")
    boxes = soup.find_all("input", {"type": "checkbox"})
    labeled = [(box, _label_text_for(soup, box)) for box in boxes]
    labeled = [(box, text) for box, text in labeled if text]

    findings = []
    for i in range(len(labeled) - 1):
        box_a, text_a = labeled[i]
        box_b, text_b = labeled[i + 1]
        negated_a = any(kw in text_a.lower() for kw in _NEGATION_KEYWORDS)
        negated_b = any(kw in text_b.lower() for kw in _NEGATION_KEYWORDS)
        if negated_a != negated_b:
            findings.append(
                {
                    "pattern_type": "Trick Questions",
                    "confidence_score": 0.65,
                    "evidence_data": {
                        "selector_a": _selector_for(box_a),
                        "selector_b": _selector_for(box_b),
                        "text_a": text_a,
                        "text_b": text_b,
                    },
                }
            )
    return findings


def find_autoplay_media(dom_html: str) -> list[dict]:
    soup = BeautifulSoup(dom_html, "html.parser")
    findings = []
    for tag in soup.find_all(("video", "audio")):
        if "autoplay" in tag.attrs:
            findings.append(
                {
                    "pattern_type": "Exploiting Addiction (Autoplay)",
                    "confidence_score": 0.6,
                    "evidence_data": {"selector": _selector_for(tag)},
                }
            )
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_heuristics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/analysis/heuristics.py tests/test_heuristics.py
git commit -m "feat: trick-question and autoplay-media DOM heuristics"
```

---

### Task 5: Readability Check for Legally-Relevant Text

**Files:**
- Create: `app/analysis/readability.py`
- Test: `tests/test_readability.py`

**Interfaces:**
- Consumes: nothing
- Produces: `flag_complex_language(text: str) -> dict | None`

**Note:** the design spec sketches this as living in `llm_classify.py`; it's
placed in its own module here instead because it has zero dependency on the
`anthropic` client or the few-shot prompt machinery — a pure text-in,
dict-out function deserves its own single-responsibility file, consistent
with how `text_extract.py` and `visual.py` are already split out.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_readability.py
from app.analysis.readability import flag_complex_language

COMPLEX_LEGAL_TEXT = (
    "Willkommen in unserem Shop! Wir freuen uns, dass Sie da sind. "
    "Schauen Sie sich gerne um und entdecken Sie unsere neuen Produkte. "
    "Unbeschadet der Bestimmungen des vorstehenden Absatzes bleibt "
    "die außerordentliche Kündigung aus wichtigem Grund unter "
    "gleichzeitiger Wahrung sämtlicher hierin nicht explizit "
    "ausgeschlossener gesetzlicher Widerrufsmöglichkeiten unberührt, "
    "sofern nicht anderweitig vertraglich disponiert wurde."
)

SIMPLE_TEXT = (
    "Willkommen in unserem Shop! Wir freuen uns, dass Sie da sind. "
    "Schauen Sie sich gerne um. Sie können jederzeit kündigen. "
    "Schreiben Sie uns einfach eine E-Mail."
)


def test_flag_complex_language_detects_dense_legal_sentence():
    result = flag_complex_language(COMPLEX_LEGAL_TEXT)
    assert result is not None
    assert result["pattern_type"] == "Verständnis-Barriere (Sprachkomplexität)"
    assert 0.0 <= result["confidence_score"] <= 1.0
    assert "kündigung" in result["evidence_data"]["excerpt"].lower()


def test_flag_complex_language_returns_none_for_uniformly_simple_text():
    assert flag_complex_language(SIMPLE_TEXT) is None


def test_flag_complex_language_returns_none_without_legal_keywords():
    assert flag_complex_language("Ein ganz normaler Text ohne besondere Begriffe.") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_readability.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis.readability'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/analysis/readability.py
import re

_LEGAL_KEYWORDS = ("kündigung", "widerruf", "gebühr", "vertragslaufzeit", "agb", "schiedsgericht")


def _count_syllables(word: str) -> int:
    groups = re.findall(r"[aeiouyäöü]+", word.lower())
    return max(1, len(groups))


def _readability_score(text: str) -> float:
    """A simplified Flesch Reading Ease score. Higher = easier to read.
    Not a precise linguistic instrument — used only as a relative
    comparison between two excerpts of the same page, not an absolute
    grade level."""
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"[A-Za-zÄÖÜäöüß]+", text)
    if not sentences or not words:
        return 100.0
    syllables = sum(_count_syllables(w) for w in words)
    avg_sentence_len = len(words) / len(sentences)
    avg_syllables = syllables / len(words)
    return 206.835 - 1.015 * avg_sentence_len - 84.6 * avg_syllables


def flag_complex_language(text: str) -> dict | None:
    """Compares the readability of legally-relevant sentences (containing
    keywords like "Kündigung"/"Widerruf") against the rest of the page's
    text. A legal excerpt that's meaningfully harder to read than the
    surrounding marketing copy is a comprehension-barrier signal — the
    reader isn't struggling with the whole page, just the part that
    matters legally."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    legal_sentences = [s for s in sentences if any(kw in s.lower() for kw in _LEGAL_KEYWORDS)]
    other_sentences = [s for s in sentences if s not in legal_sentences]
    if not legal_sentences or not other_sentences:
        return None

    legal_score = _readability_score(" ".join(legal_sentences))
    other_score = _readability_score(" ".join(other_sentences))

    if legal_score < other_score - 15:
        return {
            "pattern_type": "Verständnis-Barriere (Sprachkomplexität)",
            "confidence_score": 0.55,
            "evidence_data": {
                "legal_readability_score": round(legal_score, 1),
                "page_readability_score": round(other_score, 1),
                "excerpt": legal_sentences[0][:200],
            },
        }
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_readability.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/analysis/readability.py tests/test_readability.py
git commit -m "feat: readability-gap detection for legal text vs page copy"
```

---

### Task 6: Generic Low-Contrast Legal-Text Scan

**Files:**
- Modify: `app/crawler.py`
- Test: `tests/test_crawler.py`
- Create: `tests/fixtures/camouflaged_text_page.html`

**Interfaces:**
- Consumes: `contrast_ratio` from `app/analysis/visual.py` (existing)
- Produces: `async def find_low_contrast_legal_text(page) -> list[dict]`

This generalizes the existing button-pair contrast check
(`compute_button_asymmetry`, hardcoded to `#accept`/`#reject`) to scan every
leaf text element on the page for legally-relevant keywords and flag any
whose contrast or font size is camouflaged relative to the page's median —
the same WCAG-contrast math, applied broadly instead of to two hardcoded IDs.

- [ ] **Step 1: Create the fixture page**

```html
<!-- tests/fixtures/camouflaged_text_page.html -->
<html>
<body>
  <h1 style="font-size:24px;color:#000;">Willkommen in unserem Shop</h1>
  <p style="font-size:16px;color:#000;">Entdecken Sie unsere neuen Produkte und Angebote.</p>
  <p style="font-size:16px;color:#000;">Kostenloser Versand ab 50 Euro Bestellwert.</p>
  <p id="cancel-clause" style="font-size:9px;color:#eeeeee;background-color:#ffffff;">
    Kündigung nur schriftlich per Post an unsere Geschäftsadresse möglich, Frist 3 Monate.
  </p>
</body>
</html>
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_crawler.py`:

```python
import pathlib
from app.crawler import find_low_contrast_legal_text

CAMOUFLAGE_FIXTURE_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/camouflaged_text_page.html"
).as_uri()


@pytest.mark.asyncio
async def test_find_low_contrast_legal_text_flags_camouflaged_clause():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(CAMOUFLAGE_FIXTURE_URL)
        findings = await find_low_contrast_legal_text(page)
        await browser.close()

    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Visuelle Tarnung (Kontrast)"
    assert "kündigung" in findings[0]["evidence_data"]["excerpt"].lower()
```

(`pytest` and `async_playwright` are already imported at the top of
`tests/test_crawler.py` from Task 11 of the previous plan — reuse those
imports, don't re-import.)

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_crawler.py -v -k low_contrast`
Expected: FAIL with `ImportError: cannot import name 'find_low_contrast_legal_text'`

- [ ] **Step 4: Write minimal implementation**

Add to `app/crawler.py` (needs a new import at the top:
`from app.analysis.visual import contrast_ratio`):

```python
_LEGAL_TEXT_KEYWORDS = ("kündigung", "widerruf", "gebühr", "vertragslaufzeit", "agb", "schiedsgericht")


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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_crawler.py -v -k low_contrast`
Expected: PASS

- [ ] **Step 6: Run the full existing crawler test file to confirm no regression**

Run: `pytest tests/test_crawler.py -v`
Expected: PASS (all tests, including the pre-existing HAR/button-style tests)

- [ ] **Step 7: Commit**

```bash
git add app/crawler.py tests/test_crawler.py tests/fixtures/camouflaged_text_page.html
git commit -m "feat: generic low-contrast legal-text detection"
```

---

### Task 7: Pattern Taxonomy Expansion — NORM_MAP, Prompt, Few-Shots, Contract Test

**Files:**
- Modify: `app/compliance.py`
- Modify: `app/analysis/llm_classify.py`
- Modify: `data/mathur_examples.json`
- Modify: `tests/test_compliance.py`

**Interfaces:**
- Consumes: nothing
- Produces: 9 new `NORM_MAP` keys; `SYSTEM_PROMPT` enum extended to include
  5 LLM-only pattern types.

This task bundles the norm map, the prompt vocabulary, and the contract
test together deliberately (see Global Constraints) — splitting them across
tasks is exactly how the "Sneaking / Hidden Costs" vs "Hidden Costs" bug
happened in this codebase before.

- [ ] **Step 1: Write the failing test**

Replace `test_llm_prompt_pattern_types_all_resolve_to_a_norm` in
`tests/test_compliance.py` with:

```python
def test_llm_prompt_pattern_types_all_resolve_to_a_norm():
    """Contract test: every pattern_type Claude is instructed to emit (per
    llm_classify.SYSTEM_PROMPT's enum list) must resolve through map_to_norm.
    Prevents drift between the prompt's vocabulary and NORM_MAP's keys."""
    prompt_pattern_types = [
        "Fake Urgency",
        "Fake Scarcity",
        "Fake Social Proof",
        "Confirm Shaming",
        "Sneaking / Hidden Costs",
        "Forced Continuity",
        "Decoy Pricing",
        "Nagging",
        "Roach Motel",
        "Forced Path",
    ]
    for pattern_type in prompt_pattern_types:
        assert map_to_norm(pattern_type) != "Unbekannt", pattern_type


def test_map_heuristic_and_visual_pattern_types():
    """Same contract, for the non-LLM pattern types produced by the DOM
    heuristics, readability check, and generic contrast scan."""
    heuristic_pattern_types = [
        "Trick Questions",
        "Exploiting Addiction (Autoplay)",
        "Exploiting Addiction (Infinite Scroll)",
        "Verständnis-Barriere (Sprachkomplexität)",
        "Visuelle Tarnung (Kontrast)",
    ]
    for pattern_type in heuristic_pattern_types:
        assert map_to_norm(pattern_type) != "Unbekannt", pattern_type
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_compliance.py -v`
Expected: FAIL — `map_to_norm("Forced Continuity") == "Unbekannt"` (and similarly for the rest)

- [ ] **Step 3: Extend `NORM_MAP`**

In `app/compliance.py`, replace the `NORM_MAP` dict with:

```python
NORM_MAP = {
    "Fake Urgency": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Fake Scarcity": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Fake Social Proof": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Hidden Costs": "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB",
    "Sneaking / Hidden Costs": "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB",
    "Unklare Button-Beschriftung": "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB",
    "Confirm Shaming": "Art. 25 DSA",
    "Visuelle Asymmetrie (Button)": "Art. 25 DSA",
    "Obstruction": "Art. 25 DSA",
    "Pre-ticked Box": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "Verdeckter Opt-out": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "Preisaufschlag": "PAngV",
    "Trick Questions": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "Forced Continuity": "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB",
    "Decoy Pricing": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Nagging": "Art. 25 DSA",
    "Roach Motel": "Art. 25 DSA",
    "Forced Path": "Art. 25 DSA",
    "Exploiting Addiction (Autoplay)": "Art. 25 DSA",
    "Exploiting Addiction (Infinite Scroll)": "Art. 25 DSA",
    "Verständnis-Barriere (Sprachkomplexität)": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Visuelle Tarnung (Kontrast)": "Art. 25 DSA",
}
```

- [ ] **Step 4: Extend the LLM prompt enum and few-shot examples**

In `app/analysis/llm_classify.py`, replace the `SYSTEM_PROMPT` string with:

```python
SYSTEM_PROMPT = """Du bist ein Klassifikator für manipulative UX-Texte (Dark Patterns).
Antworte AUSSCHLIESSLICH mit einem JSON-Array. Jedes Element hat die Felder
"pattern_type" (einer aus: Fake Urgency, Fake Scarcity, Fake Social Proof,
Confirm Shaming, Sneaking / Hidden Costs, Forced Continuity, Decoy Pricing,
Nagging, Roach Motel, Forced Path), "confidence_score" (0.0-1.0) und
"quote" (das wörtliche Zitat aus dem Text, das den Fund belegt). Gib ein
leeres Array [] zurück, wenn der Text keine Dark Patterns enthält.

Beispiele:
"""
```

Add these entries to `data/mathur_examples.json` (insert before the closing
`]`, keep valid JSON):

```json
  {"text": "Ihr Abo verlängert sich automatisch, sofern Sie nicht rechtzeitig kündigen.", "pattern_type": "Forced Continuity"},
  {"text": "This offer will not come back once this session ends.", "pattern_type": "Nagging"},
  {"text": "Ihre Kündigung ist nur telefonisch während unserer Geschäftszeiten möglich.", "pattern_type": "Roach Motel"},
  {"text": "Um fortzufahren, registrieren Sie sich bitte zunächst kostenlos.", "pattern_type": "Forced Path"},
  {"text": "Basic-Paket: 9,99€ für 1 Feature. Pro-Paket: 10,99€ für 15 Features.", "pattern_type": "Decoy Pricing"}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_compliance.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/compliance.py app/analysis/llm_classify.py data/mathur_examples.json tests/test_compliance.py
git commit -m "feat: expand pattern taxonomy — NORM_MAP, LLM prompt, few-shots, contract test"
```

---

### Task 8: Wire New Detectors Into the Analysis Pipeline + Confidence Boost

**Files:**
- Modify: `app/analysis/pipeline.py`
- Modify: `app/scan.py` (only the `run_analysis` call site — add `await`)
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `find_trick_questions`, `find_autoplay_media` (Task 4),
  `flag_complex_language` (Task 5), `find_low_contrast_legal_text` (Task 6,
  needs `page`)
- Produces: `async def run_analysis(dom_html: str, button_styles: dict | None, llm_client=None, page=None) -> list[dict]`
  — **note the signature change from sync to async**, and the new optional
  `page` parameter. Every existing and future caller must `await` this.

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_pipeline.py` entirely with:

```python
import pytest
from app.analysis.pipeline import run_analysis

DOM_HTML = """
<html><body>
<form><input type="checkbox" id="newsletter" checked></form>
<main><p>No thanks, I enjoy paying full price for everything.</p></main>
</body></html>
"""

TRICK_QUESTION_DOM = """
<html><body>
<form>
  <input type="checkbox" id="a"><label for="a">Ich möchte Angebote erhalten</label>
  <input type="checkbox" id="b" checked><label for="b">Ich möchte NICHT kontaktiert werden</label>
</form>
</body></html>
"""


def _fake_classify_text(text, client=None):
    return [
        {
            "pattern_type": "Confirm Shaming",
            "confidence_score": 0.8,
            "evidence_data": {"quote": "No thanks, I enjoy paying full price for everything."},
        }
    ]


@pytest.mark.asyncio
async def test_run_analysis_combines_all_stages_with_norms(monkeypatch):
    monkeypatch.setattr("app.analysis.pipeline.classify_text", _fake_classify_text)

    button_styles = {
        "accept": {"width": 200, "height": 60, "bg_color": (0, 128, 0), "text_color": (255, 255, 255)},
        "reject": {"width": 60, "height": 20, "bg_color": (230, 230, 230), "text_color": (240, 240, 240)},
    }

    findings = await run_analysis(DOM_HTML, button_styles)

    pattern_types = {f["pattern_type"] for f in findings}
    assert pattern_types == {"Pre-ticked Box", "Confirm Shaming", "Visuelle Asymmetrie (Button)"}
    for f in findings:
        assert f["target_norm"] != "Unbekannt"


@pytest.mark.asyncio
async def test_run_analysis_without_button_styles_skips_visual_stage(monkeypatch):
    monkeypatch.setattr("app.analysis.pipeline.classify_text", _fake_classify_text)
    findings = await run_analysis(DOM_HTML, None)
    pattern_types = {f["pattern_type"] for f in findings}
    assert "Visuelle Asymmetrie (Button)" not in pattern_types


@pytest.mark.asyncio
async def test_run_analysis_finds_trick_questions(monkeypatch):
    monkeypatch.setattr("app.analysis.pipeline.classify_text", lambda text, client=None: [])
    findings = await run_analysis(TRICK_QUESTION_DOM, None)
    assert any(f["pattern_type"] == "Trick Questions" for f in findings)


@pytest.mark.asyncio
async def test_run_analysis_boosts_confidence_when_multiple_pattern_types_cooccur(monkeypatch):
    monkeypatch.setattr("app.analysis.pipeline.classify_text", _fake_classify_text)
    baseline = await run_analysis("<html><body><main><p>x</p></main></body></html>", None)
    baseline_confirm_shaming = next(f for f in baseline if f["pattern_type"] == "Confirm Shaming")

    boosted = await run_analysis(DOM_HTML, None)  # also has Pre-ticked Box
    boosted_confirm_shaming = next(f for f in boosted if f["pattern_type"] == "Confirm Shaming")

    assert boosted_confirm_shaming["confidence_score"] > baseline_confirm_shaming["confidence_score"]


@pytest.mark.asyncio
async def test_run_analysis_skips_page_dependent_checks_without_page(monkeypatch):
    monkeypatch.setattr("app.analysis.pipeline.classify_text", lambda text, client=None: [])
    # Must not raise even though page=None — find_low_contrast_legal_text is
    # page-dependent and simply skipped when no page object is provided.
    findings = await run_analysis(DOM_HTML, None, page=None)
    assert isinstance(findings, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL — `TypeError: object list can't be used in 'await' expression`
(the existing `run_analysis` is still synchronous)

- [ ] **Step 3: Rewrite `run_analysis`**

Replace `app/analysis/pipeline.py` entirely:

```python
import logging

from app.analysis.heuristics import (
    find_preticked_checkboxes,
    find_countdown_elements,
    find_trick_questions,
    find_autoplay_media,
)
from app.analysis.readability import flag_complex_language
from app.analysis.text_extract import extract_main_text
from app.analysis.llm_classify import classify_text
from app.analysis.visual import compute_button_asymmetry
from app.compliance import map_to_norm

logger = logging.getLogger(__name__)

# Confidence rises when multiple distinct manipulation mechanisms co-occur
# on the same page (the book's "Double Shot" effect: persuasion + deception
# stacked together signal deliberate intent, not an isolated UX slip).
_COOCCURRENCE_BOOST = 0.05


async def run_analysis(
    dom_html: str, button_styles: dict | None, llm_client=None, page=None
) -> list[dict]:
    findings: list[dict] = []

    findings.extend(find_preticked_checkboxes(dom_html))
    findings.extend(find_countdown_elements(dom_html))
    findings.extend(find_trick_questions(dom_html))
    findings.extend(find_autoplay_media(dom_html))

    main_text = extract_main_text(dom_html)
    try:
        findings.extend(classify_text(main_text, client=llm_client))
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, LLM call
        logger.warning("classify_text failed, continuing without LLM findings: %s", exc)

    complexity_finding = flag_complex_language(main_text)
    if complexity_finding is not None:
        findings.append(complexity_finding)

    if button_styles is not None:
        findings.extend(
            compute_button_asymmetry(button_styles["accept"], button_styles["reject"])
        )

    if page is not None:
        # imported here to avoid a hard Playwright dependency for callers
        # that only ever pass page=None (e.g. the pre-existing sync tests)
        from app.crawler import find_low_contrast_legal_text

        try:
            findings.extend(await find_low_contrast_legal_text(page))
        except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
            logger.warning("find_low_contrast_legal_text failed: %s", exc)

    distinct_types = {f["pattern_type"] for f in findings}
    if len(distinct_types) > 1:
        boost = _COOCCURRENCE_BOOST * (len(distinct_types) - 1)
        for f in findings:
            f["confidence_score"] = round(min(f["confidence_score"] + boost, 1.0), 2)

    for f in findings:
        f["target_norm"] = map_to_norm(f["pattern_type"])

    return findings
```

- [ ] **Step 4: Update `app/scan.py`'s call site**

In `app/scan.py`, change the existing line

```python
    findings = run_analysis(crawl_result["dom_after"], crawl_result["button_styles"])
```

to:

```python
    findings = await run_analysis(crawl_result["dom_after"], crawl_result["button_styles"])
```

(`run_scan` is already an `async def`, so this is the only change needed
there.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pipeline.py tests/test_scan.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite to confirm no other regressions**

Run: `pytest -q`
Expected: PASS (all tests except the pre-existing live-API-key-gated skip)

- [ ] **Step 7: Commit**

```bash
git add app/analysis/pipeline.py app/scan.py tests/test_pipeline.py
git commit -m "feat: wire new detectors into run_analysis, add co-occurrence confidence boost"
```

---

### Task 9: Extract Shared Per-Page Snapshot Helper in `app/crawler.py`

**Files:**
- Modify: `app/crawler.py`
- Test: `tests/test_crawler.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `async def _snapshot_page(page) -> dict` — returns
  `{"dom_before", "dom_after", "screenshot", "button_styles"}`. `crawl_page`
  keeps its existing public signature and return shape unchanged; it now
  calls `_snapshot_page` internally instead of duplicating the logic. This
  is a pure refactor — no behavior change, verified by the existing test
  suite passing unmodified.

- [ ] **Step 1: Confirm the existing tests pass before refactoring (baseline)**

Run: `pytest tests/test_crawler.py -v`
Expected: PASS (this is the safety net for the refactor — note the count of
passing tests before changing anything)

- [ ] **Step 2: Extract `_snapshot_page` and simplify `crawl_page`**

In `app/crawler.py`, replace the body of `crawl_page` (from `context = await
browser.new_context(...)` through the `return {...}` at the end) with:

```python
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

    return {
        "dom_before": dom_before,
        "dom_after": dom_after,
        "screenshot": screenshot,
        "button_styles": button_styles,
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
```

- [ ] **Step 3: Run the existing tests to confirm the refactor is behavior-preserving**

Run: `pytest tests/test_crawler.py -v`
Expected: PASS — same tests, same count, as the Step 1 baseline

- [ ] **Step 4: Commit**

```bash
git add app/crawler.py
git commit -m "refactor: extract _snapshot_page from crawl_page for reuse by site-wide crawling"
```

---

### Task 10: LLM-Driven Next-Interaction Decision

**Files:**
- Modify: `app/site_crawler.py`
- Test: `tests/test_site_crawler.py`

**Interfaces:**
- Consumes: nothing
- Produces: `decide_next_interaction(category: str, clickable_elements: list[dict], llm_client=None) -> dict | None`.
  `clickable_elements` is `[{"text": str, "selector": str}, ...]`. Return
  value is `{"type": "click", "target": "<selector>"}` or `None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_site_crawler.py` (reuse `_FakeClient`/`_FakeMessages`/
`_FakeMessage`/`_FakeBlock` already defined above in this file):

```python
from app.site_crawler import decide_next_interaction

CLICKABLE_ELEMENTS = [
    {"text": "Startseite", "selector": "nav a#home"},
    {"text": "In den Warenkorb", "selector": "button#add-to-cart"},
    {"text": "Impressum", "selector": "footer a#imprint"},
]


def test_decide_next_interaction_returns_llm_choice_for_relevant_category():
    client = _FakeClient('{"type": "click", "target": "button#add-to-cart"}')
    result = decide_next_interaction("product_category", CLICKABLE_ELEMENTS, llm_client=client)
    assert result == {"type": "click", "target": "button#add-to-cart"}


def test_decide_next_interaction_returns_none_when_llm_says_none():
    client = _FakeClient('{"type": "none"}')
    result = decide_next_interaction("product_category", CLICKABLE_ELEMENTS, llm_client=client)
    assert result is None


def test_decide_next_interaction_returns_none_without_llm_client():
    assert decide_next_interaction("product_category", CLICKABLE_ELEMENTS, llm_client=None) is None


def test_decide_next_interaction_returns_none_for_categories_without_a_goal():
    client = _FakeClient('{"type": "click", "target": "button#add-to-cart"}')
    assert decide_next_interaction("cookie_consent", CLICKABLE_ELEMENTS, llm_client=client) is None
    assert decide_next_interaction("other", CLICKABLE_ELEMENTS, llm_client=client) is None


def test_decide_next_interaction_returns_none_on_llm_failure():
    class _BrokenClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("API down")

    result = decide_next_interaction("product_category", CLICKABLE_ELEMENTS, llm_client=_BrokenClient())
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_site_crawler.py -v`
Expected: FAIL with `ImportError: cannot import name 'decide_next_interaction'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/site_crawler.py`:

```python
import json

# One-line navigation goal per category; categories not listed here (or
# mapped to None) get no LLM-driven interaction — cookie_consent is already
# handled by apply_consent_rules, "other" has no specific journey to drive.
_INTERACTION_GOALS = {
    "checkout_payment": (
        "Klicke dich bis zum letzten Schritt vor der Zahlung durch "
        "(z.B. 'Weiter', 'Zur Kasse', 'Warenkorb ansehen'), aber löse "
        "NIEMALS eine echte Zahlung aus."
    ),
    "account_subscription": (
        "Suche einen Kündigungs- oder Konto-löschen-Link/Button und "
        "klicke ihn an, aber bestätige die Kündigung NICHT endgültig."
    ),
    "product_category": "Klicke auf ein Produkt und danach auf 'In den Warenkorb', falls vorhanden.",
    "popup_leadform": "Klicke den Schließen-Button (X) des Overlays, falls vorhanden.",
}


def decide_next_interaction(category: str, clickable_elements: list[dict], llm_client=None) -> dict | None:
    goal = _INTERACTION_GOALS.get(category)
    if not goal or not clickable_elements or llm_client is None:
        return None

    elements_text = "\n".join(
        f'- "{el["text"]}" (selector: {el["selector"]})' for el in clickable_elements[:40]
    )
    prompt = (
        f"Ziel: {goal}\n\n"
        f"Anklickbare Elemente auf der aktuellen Seite:\n{elements_text}\n\n"
        'Antworte AUSSCHLIESSLICH mit einem JSON-Objekt {"type": "click", "target": "<selector>"} '
        'für das nächste sinnvolle Element, oder {"type": "none"}, falls kein Element zum Ziel passt.'
    )
    try:
        response = llm_client.messages.create(
            model="claude-sonnet-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        result = json.loads(response.content[0].text)
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, LLM call
        logger.warning("decide_next_interaction failed, skipping: %s", exc)
        return None

    if result.get("type") == "click" and result.get("target"):
        return {"type": "click", "target": result["target"]}
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_site_crawler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/site_crawler.py tests/test_site_crawler.py
git commit -m "feat: category-aware LLM next-interaction decision"
```

---

### Task 11: Site-Wide BFS Crawl Orchestrator

**Files:**
- Modify: `app/site_crawler.py`
- Test: `tests/test_site_crawler.py`
- Create: `tests/fixtures/site_two_pages/index.html`
- Create: `tests/fixtures/site_two_pages/page2.html`

**Interfaces:**
- Consumes: `discover_links`, `classify_page_category`,
  `decide_next_interaction` (this module), `_snapshot_page`,
  `apply_consent_rules` (`app/crawler.py`), `validate_scan_url`
  (`app/url_safety.py`)
- Produces: `async def crawl_site(start_url: str, browser, max_pages: int, har_dir: str, consent_rules_dir=DEFAULT_CONSENT_RULES_DIR, llm_client=None, url_validator=validate_scan_url) -> dict`
  — returns `{"pages": [{"url", "category", "dom_after", "screenshot", "button_styles", "infinite_scroll_detected"}, ...], "har_path": str}`.
  `url_validator` is injectable (default `validate_scan_url`) specifically
  so tests can exercise multi-page link-following against local `file://`
  fixtures without the production SSRF check rejecting every non-http(s)
  link — production code never overrides the default.

- [ ] **Step 1: Create the two-page fixture site**

```html
<!-- tests/fixtures/site_two_pages/index.html -->
<html>
<body>
  <h1>Startseite</h1>
  <a href="page2.html">Weiter zu Seite 2</a>
</body>
</html>
```

```html
<!-- tests/fixtures/site_two_pages/page2.html -->
<html>
<body>
  <h1>Seite 2</h1>
  <p>Ende der Test-Site, keine weiteren Links.</p>
</body>
</html>
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_site_crawler.py`:

```python
import pathlib
import pytest
from playwright.async_api import async_playwright
from app.site_crawler import crawl_site

TWO_PAGE_SITE_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/site_two_pages/index.html"
).as_uri()


@pytest.mark.asyncio
async def test_crawl_site_follows_same_directory_links_up_to_max_pages(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        result = await crawl_site(
            TWO_PAGE_SITE_URL, browser, max_pages=5, har_dir=str(tmp_path),
            url_validator=lambda url: None,  # file:// fixtures aren't http(s); bypass SSRF check for this local test
        )
        await browser.close()

    urls = {p["url"] for p in result["pages"]}
    assert TWO_PAGE_SITE_URL in urls
    assert any("page2.html" in u for u in urls)
    assert len(result["pages"]) <= 5
    assert result["har_path"].endswith(".har")
    assert all("category" in p for p in result["pages"])


@pytest.mark.asyncio
async def test_crawl_site_respects_max_pages_limit(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        result = await crawl_site(
            TWO_PAGE_SITE_URL, browser, max_pages=1, har_dir=str(tmp_path),
            url_validator=lambda url: None,
        )
        await browser.close()

    assert len(result["pages"]) == 1
    assert result["pages"][0]["url"] == TWO_PAGE_SITE_URL


@pytest.mark.asyncio
async def test_crawl_site_default_validator_rejects_unsafe_discovered_links(tmp_path, monkeypatch):
    def fake_discover_links(dom_html, base_url, allowed_hosts):
        return ["http://127.0.0.1:9/internal"]  # loopback — must be rejected

    monkeypatch.setattr("app.site_crawler.discover_links", fake_discover_links)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        # Note: no url_validator override here — exercises the real default
        # (validate_scan_url), which also rejects file:// for the start URL's
        # discovered "children" the same way it would reject a loopback IP.
        result = await crawl_site(
            TWO_PAGE_SITE_URL, browser, max_pages=5, har_dir=str(tmp_path)
        )
        await browser.close()

    urls = {p["url"] for p in result["pages"]}
    assert "http://127.0.0.1:9/internal" not in urls
    assert len(result["pages"]) == 1  # only the start page — the discovered link was rejected
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_site_crawler.py -v -k crawl_site`
Expected: FAIL with `ImportError: cannot import name 'crawl_site'`

- [ ] **Step 4: Write minimal implementation**

Add these imports to the top of `app/site_crawler.py`:

```python
import asyncio
import pathlib
import uuid

from app.crawler import DEFAULT_CONSENT_RULES_DIR, _snapshot_page, apply_consent_rules
from app.url_safety import validate_scan_url
```

Append to `app/site_crawler.py`:

```python
async def _extract_clickable_elements(page) -> list[dict]:
    try:
        elements = await page.eval_on_selector_all(
            "a, button",
            """els => els.slice(0, 60).map(el => ({
                text: (el.textContent || el.value || '').trim().slice(0, 80),
                selector: el.tagName.toLowerCase() + (el.id ? '#' + el.id : ''),
            })).filter(e => e.text.length > 0)""",
        )
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
        logger.debug("_extract_clickable_elements failed: %s", exc)
        return []
    return elements


async def _check_infinite_scroll(page) -> bool:
    """Scrolls the page 3 times and checks whether the document keeps
    growing without bound — a technical proxy for infinite-scroll feeds,
    detectable within a single crawl (no multi-session behavioral data
    needed)."""
    try:
        heights = []
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)
            heights.append(await page.evaluate("document.body.scrollHeight"))
        return len(heights) >= 2 and heights[-1] > heights[0]
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, page state can vary
        logger.debug("_check_infinite_scroll failed: %s", exc)
        return False


async def crawl_site(
    start_url: str,
    browser,
    max_pages: int,
    har_dir: str,
    consent_rules_dir: str = DEFAULT_CONSENT_RULES_DIR,
    llm_client=None,
    url_validator=validate_scan_url,
) -> dict:
    """BFS crawl of a whole site starting from start_url, staying within the
    start URL's host + subdomains. One shared browser context (one HAR file
    for the whole site). start_url itself is trusted (the caller already
    validated it, same contract as crawl_page) — every link DISCOVERED
    during the crawl is re-validated with `url_validator` before being
    queued, since those were never seen by the caller."""
    from urllib.parse import urlparse

    pathlib.Path(har_dir).mkdir(parents=True, exist_ok=True)
    har_path = str(pathlib.Path(har_dir) / f"site-crawl-{uuid.uuid4().hex}.har")
    context = await browser.new_context(record_har_path=har_path)

    start_host = urlparse(start_url).hostname or ""
    allowed_hosts = {start_host}

    queue = [start_url]
    visited: set[str] = set()
    pages: list[dict] = []

    try:
        while queue and len(pages) < max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            page = await context.new_page()
            try:
                await page.goto(url)
            except Exception as exc:  # noqa: BLE001 - deliberate broad catch, a dead link shouldn't kill the crawl
                logger.warning("crawl_site: failed to load %r: %s", url, exc)
                await page.close()
                continue

            await apply_consent_rules(page, consent_rules_dir)
            snapshot = await _snapshot_page(page)
            category = classify_page_category(url, snapshot["dom_after"], llm_client=llm_client)
            infinite_scroll = (
                await _check_infinite_scroll(page) if category in ("product_category", "other") else False
            )

            clickable = await _extract_clickable_elements(page)
            interaction = decide_next_interaction(category, clickable, llm_client=llm_client)
            if interaction and interaction.get("target"):
                try:
                    el = await page.query_selector(interaction["target"])
                    if el and await el.is_visible():
                        await el.click(timeout=2000)
                        await asyncio.sleep(1.0)
                        snapshot["dom_after"] = await page.content()
                except Exception as exc:
                    logger.debug("crawl_site: interaction click failed: %s", exc)

            pages.append(
                {
                    "url": url,
                    "category": category,
                    "dom_after": snapshot["dom_after"],
                    "screenshot": snapshot["screenshot"],
                    "button_styles": snapshot["button_styles"],
                    "infinite_scroll_detected": infinite_scroll,
                }
            )

            for link in discover_links(snapshot["dom_after"], url, allowed_hosts):
                if link in visited or link in queue:
                    continue
                try:
                    url_validator(link)
                except ValueError as exc:
                    logger.info("crawl_site: skipping unsafe discovered link %r: %s", link, exc)
                    continue
                queue.append(link)

            await page.close()
    finally:
        await context.close()  # flushes the HAR file to disk

    return {"pages": pages, "har_path": har_path}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_site_crawler.py -v`
Expected: PASS (all tests in this file)

- [ ] **Step 6: Commit**

```bash
git add app/site_crawler.py tests/test_site_crawler.py tests/fixtures/site_two_pages/
git commit -m "feat: site-wide BFS crawl orchestrator with infinite-scroll detection"
```

---

### Task 12: `run_site_scan` — Full Site-Scan Orchestration

**Files:**
- Modify: `app/scan.py`
- Test: `tests/test_scan.py`

**Interfaces:**
- Consumes: `crawl_site` (Task 11), `run_analysis` (Task 8, now async),
  `insert_page`/`get_page_findings` (Task 1), existing evidence/citation
  helpers
- Produces: `async def run_site_scan(start_url: str, conn, evidence_dir: str, browser, max_pages: int | None = None, llm_client=None) -> int`
  (returns `scan_id`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scan.py`:

```python
import pytest
from app.db import get_pages, get_page_findings
from app.scan import run_site_scan

FAKE_SITE_RESULT = {
    "pages": [
        {
            "url": "https://example.com",
            "category": "other",
            "dom_after": "<html><body><input type='checkbox' id='nl' checked></body></html>",
            "screenshot": b"\x89PNG-fake-bytes-1",
            "button_styles": None,
            "infinite_scroll_detected": False,
        },
        {
            "url": "https://example.com/checkout",
            "category": "checkout_payment",
            "dom_after": "<html><body><p>checkout page</p></body></html>",
            "screenshot": b"\x89PNG-fake-bytes-2",
            "button_styles": None,
            "infinite_scroll_detected": False,
        },
    ],
    "har_path": "",  # set to a real temp file path in the test setup below
}


@pytest.mark.asyncio
async def test_run_site_scan_persists_pages_and_page_scoped_findings(tmp_path, monkeypatch):
    har_file = tmp_path / "site.har"
    har_file.write_bytes(b"{}")
    FAKE_SITE_RESULT["har_path"] = str(har_file)

    async def fake_crawl_site(start_url, browser, max_pages, har_dir, llm_client=None):
        return FAKE_SITE_RESULT

    call_count = {"n": 0}

    async def fake_run_analysis(dom_html, button_styles, llm_client=None, page=None):
        call_count["n"] += 1
        if "checkbox" in dom_html:
            return [
                {
                    "pattern_type": "Pre-ticked Box",
                    "target_norm": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
                    "confidence_score": 0.9,
                    "evidence_data": {"selector": "#nl"},
                }
            ]
        return []

    monkeypatch.setattr("app.scan.crawl_site", fake_crawl_site)
    monkeypatch.setattr("app.scan.run_analysis", fake_run_analysis)

    conn = init_db(":memory:")
    scan_id = await run_site_scan("https://example.com", conn, str(tmp_path), browser=None, max_pages=5)

    pages = get_pages(conn, scan_id)
    assert len(pages) == 2
    assert {p["category"] for p in pages} == {"other", "checkout_payment"}

    checkout_page = next(p for p in pages if p["category"] == "checkout_payment")
    other_page = next(p for p in pages if p["category"] == "other")

    assert get_page_findings(conn, other_page["id"])[0]["pattern_type"] == "Pre-ticked Box"
    assert get_page_findings(conn, checkout_page["id"]) == []

    all_scan_findings = get_findings(conn, scan_id)
    assert len(all_scan_findings) == 1
    evidence = all_scan_findings[0]["evidence_data"]
    assert "har_path" in evidence and "har_sha256" in evidence
    assert "screenshot_path" in evidence and "screenshot_sha256" in evidence
```

(`init_db` and `get_findings` are already imported at the top of
`tests/test_scan.py` from the previous plan — reuse them.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scan.py -v -k run_site_scan`
Expected: FAIL with `ImportError: cannot import name 'run_site_scan'`

- [ ] **Step 3: Write minimal implementation**

In `app/scan.py`, add the import `from app.site_crawler import crawl_site`
and `from app.db import insert_page` at the top, then append:

```python
async def run_site_scan(
    start_url: str,
    conn,
    evidence_dir: str,
    browser,
    max_pages: int | None = None,
    llm_client=None,
) -> int:
    if max_pages is None:
        max_pages = int(os.environ.get("MAX_PAGES_PER_SCAN", "15"))

    scan_id = insert_scan(conn, start_url)

    site_result = await crawl_site(
        start_url, browser, max_pages=max_pages, har_dir=evidence_dir, llm_client=llm_client
    )

    with open(site_result["har_path"], "rb") as f:
        har_hash = sha256_bytes(f.read())

    async with httpx.AsyncClient(base_url=LEGAL_TEXT_MCP_BASE_URL, timeout=5.0) as client:
        for page_data in site_result["pages"]:
            page_id = insert_page(conn, scan_id, page_data["url"], page_data["category"])

            screenshot_path = os.path.join(
                evidence_dir, f"scan_{scan_id}_page_{page_id}_screenshot.png"
            )
            screenshot_hash = save_evidence(page_data["screenshot"], screenshot_path)
            rfc3161_timestamp(page_data["screenshot"])  # best-effort, stored hash is the primary proof

            findings = await run_analysis(page_data["dom_after"], page_data["button_styles"])

            for finding in findings:
                finding["evidence_data"]["screenshot_path"] = screenshot_path
                finding["evidence_data"]["screenshot_sha256"] = screenshot_hash
                finding["evidence_data"]["har_path"] = site_result["har_path"]
                finding["evidence_data"]["har_sha256"] = har_hash
                finding["evidence_data"]["citation"] = await fetch_citation(
                    finding["target_norm"], LEGAL_TEXT_MCP_BASE_URL, client=client
                )
                insert_finding(conn, scan_id, finding, page_id=page_id)

    return scan_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scan.py -v`
Expected: PASS (all tests, including the pre-existing `run_scan` test)

- [ ] **Step 5: Commit**

```bash
git add app/scan.py tests/test_scan.py
git commit -m "feat: run_site_scan orchestrates crawl_site into pages + page-scoped findings"
```

---

### Task 13: Dashboard Route Switches to Site-Wide Scans

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `run_site_scan` (Task 12)
- Produces: `POST /scans` now calls `run_site_scan`; accepts an optional
  `max_pages` form field.

- [ ] **Step 1: Write the failing test**

In `tests/test_main.py`, find the existing test that monkeypatches
`main_module.run_scan` (from `test_start_scan_and_view_findings`) and
replace `run_scan`/`fake_run_scan` references with `run_site_scan`/
`fake_run_site_scan` throughout that test — the fake's signature gains
`max_pages=None`:

```python
async def fake_run_site_scan(url, conn, evidence_dir, browser=None, max_pages=None, llm_client=None):
    from app.db import insert_scan, insert_finding
    scan_id = insert_scan(conn, url)
    insert_finding(conn, scan_id, {
        "pattern_type": "Confirm Shaming",
        "target_norm": "Art. 25 DSA",
        "confidence_score": 0.8,
        "evidence_data": {"quote": "No thanks"},
    })
    return scan_id

monkeypatch.setattr(main_module, "run_site_scan", fake_run_site_scan)
```

Also add a new test confirming the optional form field is accepted:

```python
def test_start_scan_accepts_optional_max_pages_field(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    received = {}

    async def fake_run_site_scan(url, conn, evidence_dir, browser=None, max_pages=None, llm_client=None):
        received["max_pages"] = max_pages
        from app.db import insert_scan
        return insert_scan(conn, url)

    monkeypatch.setattr(main_module, "run_site_scan", fake_run_site_scan)

    with TestClient(main_module.app) as client:
        response = client.post("/scans", data={"url": "https://example.com", "max_pages": "3"})

    assert response.status_code == 303
    assert received["max_pages"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py -v`
Expected: FAIL — `AttributeError: module 'app.main' has no attribute 'run_site_scan'`

- [ ] **Step 3: Update `app/main.py`**

Change the import line:

```python
from app.scan import run_site_scan
```

Replace the `start_scan` route:

```python
@app.post("/scans")
async def start_scan(
    request: Request,
    url: str = Form(...),
    max_pages: int | None = Form(None),
    conn: sqlite3.Connection = Depends(_get_conn),
):
    try:
        validate_scan_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scan_id = await run_site_scan(
        url, conn, EVIDENCE_DIR, browser=request.app.state.browser, max_pages=max_pages
    )
    return RedirectResponse(url=f"/scans/{scan_id}", status_code=303)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_main.py
git commit -m "feat: POST /scans runs a site-wide scan, accepts optional max_pages"
```

---

### Task 14: Dashboard — Per-Page Findings View

**Files:**
- Modify: `app/main.py`
- Modify: `app/templates/scan_detail.html`
- Create: `app/templates/page_detail.html`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `get_pages`, `get_page_findings` (Task 1)
- Produces: route `GET /scans/{scan_id}/pages/{page_id}`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main.py`:

```python
def test_page_detail_shows_findings_for_one_page(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    from app.db import init_db, insert_scan, insert_page, insert_finding

    conn = init_db(str(tmp_path / "test.db"))
    scan_id = insert_scan(conn, "https://example.com")
    page_id = insert_page(conn, scan_id, "https://example.com/checkout", "checkout_payment")
    insert_finding(
        conn, scan_id,
        {"pattern_type": "Trick Questions", "target_norm": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
         "confidence_score": 0.7, "evidence_data": {}},
        page_id=page_id,
    )
    conn.close()

    with TestClient(main_module.app) as client:
        response = client.get(f"/scans/{scan_id}/pages/{page_id}")

    assert response.status_code == 200
    assert "Trick Questions" in response.text


def test_scan_detail_lists_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    from app.db import init_db, insert_scan, insert_page

    conn = init_db(str(tmp_path / "test.db"))
    scan_id = insert_scan(conn, "https://example.com")
    insert_page(conn, scan_id, "https://example.com/checkout", "checkout_payment")
    conn.close()

    with TestClient(main_module.app) as client:
        response = client.get(f"/scans/{scan_id}")

    assert response.status_code == 200
    assert "checkout_payment" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py -v -k "page_detail or lists_pages"`
Expected: FAIL — 404 (route doesn't exist) / `checkout_payment` not in
`scan_detail.html`'s output

- [ ] **Step 3: Update templates**

Replace `app/templates/scan_detail.html`:

```html
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Scan {{ scan.id }}</title></head>
<body>
  <h1>Scan: {{ scan.url }}</h1>
  <a href="/scans/{{ scan.id }}/report.pdf">PDF-Report herunterladen</a>

  <h2>Gecrawlte Seiten</h2>
  <table border="1">
    <tr><th>URL</th><th>Kategorie</th></tr>
    {% for p in pages %}
    <tr><td><a href="/scans/{{ scan.id }}/pages/{{ p.id }}">{{ p.url }}</a></td><td>{{ p.category }}</td></tr>
    {% endfor %}
  </table>

  <h2>Alle Findings (Site-weit)</h2>
  <table border="1">
    <tr><th>Pattern-Typ</th><th>Norm</th><th>Confidence</th></tr>
    {% for f in findings %}
    <tr><td>{{ f.pattern_type }}</td><td>{{ f.target_norm }}</td><td>{{ f.confidence_score }}</td></tr>
    {% endfor %}
  </table>
</body>
</html>
```

Create `app/templates/page_detail.html`:

```html
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Seite {{ page_id }} — Scan {{ scan.id }}</title></head>
<body>
  <h1>Seite: {{ scan.url }} (Findings dieser Seite)</h1>
  <a href="/scans/{{ scan.id }}">Zurück zur Scan-Übersicht</a>
  <table border="1">
    <tr><th>Pattern-Typ</th><th>Norm</th><th>Confidence</th></tr>
    {% for f in findings %}
    <tr><td>{{ f.pattern_type }}</td><td>{{ f.target_norm }}</td><td>{{ f.confidence_score }}</td></tr>
    {% endfor %}
  </table>
</body>
</html>
```

- [ ] **Step 4: Update `app/main.py`**

Change the import: `from app.db import init_db, get_scan, get_findings, get_pages, get_page_findings`

Replace `scan_detail` and add `page_detail`:

```python
@app.get("/scans/{scan_id}", response_class=HTMLResponse)
def scan_detail(request: Request, scan_id: int, conn: sqlite3.Connection = Depends(_get_conn)):
    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    pages = get_pages(conn, scan_id)
    findings = get_findings(conn, scan_id)
    return templates.TemplateResponse(
        request, "scan_detail.html", {"scan": scan, "pages": pages, "findings": findings}
    )


@app.get("/scans/{scan_id}/pages/{page_id}", response_class=HTMLResponse)
def page_detail(request: Request, scan_id: int, page_id: int, conn: sqlite3.Connection = Depends(_get_conn)):
    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    findings = get_page_findings(conn, page_id)
    return templates.TemplateResponse(
        request, "page_detail.html", {"scan": scan, "page_id": page_id, "findings": findings}
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_main.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/templates/scan_detail.html app/templates/page_detail.html tests/test_main.py
git commit -m "feat: dashboard lists crawled pages, per-page findings view"
```

---

### Task 15: End-to-End Fake-Shop Fixture & Integration Test

**Files:**
- Create: `tests/fixtures/fake_shop/index.html`
- Create: `tests/fixtures/fake_shop/product.html`
- Create: `tests/fixtures/fake_shop/cart.html`
- Create: `tests/fixtures/fake_shop/checkout.html`
- Create: `tests/fixtures/fake_shop/account.html`
- Test: `tests/test_site_scan_integration.py`

**Interfaces:**
- Consumes: `crawl_site` (Task 11), `run_site_scan` (Task 12) — this is a
  pure integration test, no new production code

This is the plan's final verification: a self-contained fake shop that
exercises multiple categories in one crawl (product → cart → checkout,
plus an account page with a deliberately buried, low-contrast cancellation
clause), proving the whole pipeline works together end-to-end without
hitting any real website.

- [ ] **Step 1: Create the fixture site**

```html
<!-- tests/fixtures/fake_shop/index.html -->
<html>
<body>
  <h1>Fake Shop</h1>
  <a href="product.html">Zum Produkt</a>
  <a href="account.html">Mein Konto</a>
</body>
</html>
```

```html
<!-- tests/fixtures/fake_shop/product.html -->
<html>
<body>
  <h1>Sneaker Modell X</h1>
  <p>Nur noch 2 Stück auf Lager!</p>
  <button id="add-to-cart" onclick="window.location.href='cart.html'">In den Warenkorb</button>
</body>
</html>
```

```html
<!-- tests/fixtures/fake_shop/cart.html -->
<html>
<body>
  <h1>Warenkorb</h1>
  <a href="checkout.html">Zur Kasse</a>
</body>
</html>
```

```html
<!-- tests/fixtures/fake_shop/checkout.html -->
<html>
<body>
  <h1>Bestellübersicht</h1>
  <form>
    <input type="checkbox" id="offers"><label for="offers">Ich möchte Angebote per E-Mail erhalten</label>
    <input type="checkbox" id="calls" checked><label for="calls">Ich möchte NICHT telefonisch kontaktiert werden</label>
  </form>
</body>
</html>
```

```html
<!-- tests/fixtures/fake_shop/account.html -->
<html>
<body>
  <h1>Mein Konto</h1>
  <p style="font-size:16px;color:#000;">Willkommen zurück!</p>
  <p id="cancel-note" style="font-size:9px;color:#eeeeee;background-color:#ffffff;">
    Kündigung nur schriftlich per Post möglich, Frist 3 Monate.
  </p>
</body>
</html>
```

- [ ] **Step 2: Write the failing integration test**

```python
# tests/test_site_scan_integration.py
import json
import pathlib

import pytest
from playwright.async_api import async_playwright

from app.db import init_db, get_pages, get_findings
from app.scan import run_site_scan

FAKE_SHOP_URL = pathlib.Path(__file__).parent.joinpath("fixtures/fake_shop/index.html").as_uri()


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _StubLLMClient:
    """Deterministic stand-in for the Anthropic client: always says "no
    dark patterns" for text classification, and always declines to
    interact further (so the crawl stays within the 5 fixture pages)."""

    class messages:
        @staticmethod
        def create(**kwargs):
            prompt_text = str(kwargs.get("messages", [{}])[0].get("content", ""))
            if "AUSSCHLIESSLICH mit einem JSON-Objekt" in prompt_text:
                return _FakeMessage('{"type": "none"}')
            return _FakeMessage("[]")


@pytest.mark.asyncio
async def test_site_scan_end_to_end_across_fake_shop(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        conn = init_db(":memory:")

        scan_id = await run_site_scan(
            FAKE_SHOP_URL, conn, str(tmp_path), browser,
            max_pages=10, llm_client=_StubLLMClient(),
        )

        await browser.close()

    pages = get_pages(conn, scan_id)
    urls = {p["url"] for p in pages}
    assert FAKE_SHOP_URL in urls
    assert any("product.html" in u for u in urls)
    assert any("account.html" in u for u in urls)

    all_findings = get_findings(conn, scan_id)
    pattern_types = {f["pattern_type"] for f in all_findings}

    # Fake Urgency from product.html's "Nur noch 2 Stück" (heuristic, no LLM needed)
    assert "Fake Urgency" in pattern_types
    # Trick Questions from checkout.html's opposite-polarity checkboxes
    assert "Trick Questions" in pattern_types
    # Visuelle Tarnung from account.html's low-contrast cancellation clause
    assert "Visuelle Tarnung (Kontrast)" in pattern_types

    for f in all_findings:
        assert f["target_norm"] != "Unbekannt"
```

**Note:** `product.html`'s "Nur noch 2 Stück" text does not match
`COUNTDOWN_HINTS` (that heuristic looks at class/id attributes, not text
content) — it is picked up by the existing LLM `classify_text` few-shot
examples in real use. Since this test uses `_StubLLMClient` (always
returns `[]`), replace `assert "Fake Urgency" in pattern_types` with a
DOM-based Fake-Urgency source instead: change `product.html`'s stock notice
to use the existing countdown heuristic's class hook, so the assertion is
backed by a heuristic and stays deterministic without a real LLM call:

```html
<!-- tests/fixtures/fake_shop/product.html — replace the stock-notice line -->
<p class="countdown-timer">Nur noch 2 Stück auf Lager!</p>
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_site_scan_integration.py -v`
Expected: FAIL with `ModuleNotFoundError` or a missing-fixture error before
all fixture files exist; once fixtures exist, it should mostly pass already
(this task adds no new production code) — if any assertion fails, that's a
genuine integration gap in an earlier task, not something to patch here.
Investigate and fix the root cause in the relevant earlier task's module
before proceeding.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_site_scan_integration.py -v`
Expected: PASS

- [ ] **Step 5: Run the entire suite one last time**

Run: `pytest -q`
Expected: PASS (all tests except the pre-existing live-API-key-gated skip)

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/fake_shop/ tests/test_site_scan_integration.py
git commit -m "test: end-to-end fake-shop integration test across the site-wide crawl"
```

---

## Self-Review Notes

- **Spec coverage:** Architektur-Überblick → Tasks 9, 11, 12; `app/site_crawler.py` → Tasks 2, 3, 10, 11; `app/analysis/heuristics.py` erweitert → Task 4; `app/analysis/llm_classify.py` erweitert → Task 7; `app/analysis/pipeline.py` geändert → Task 8; `app/compliance.py` erweitert → Task 7; Datenmodell (`pages`, `page_id`) → Task 1; `run_site_scan` → Task 12; Route-Änderung → Task 13; Dashboard → Task 14; Kategorie-Strategien-Tabelle → Tasks 10-11 (interaction goals) + Task 6 (generic contrast scan covers the "other"/fallback row); Abdeckungs-Matrix → Tasks 4, 5, 6, 7, 11 (infinite scroll); Tests → Task 15; Migrations-Hinweis → Task 1's `_ensure_page_id_column`.
- **Explicitly out of scope items from the spec** (longitudinal effects, causal proof, business intent, login-gated content, Buch-Teil-3 types, real economic Decoy-Pricing modeling) have no tasks — correctly, per the spec's own scoping.
- **Type/signature consistency checked:** `run_analysis` becomes `async def` starting Task 8 — every caller (`app/scan.py`'s `run_scan` legacy path in Task 8, `run_site_scan` in Task 12) and every test file touching it (`test_pipeline.py`, `test_scan.py`) is updated in the same task it changes, never left dangling for a later task. `crawl_site`'s `url_validator` injection point is introduced in Task 11 and consumed nowhere else (production always uses the default) — verified no other task silently assumes a different signature. `_snapshot_page` (Task 9) is consumed by both `crawl_page` (same task) and `crawl_site` (Task 11) with matching return-dict keys (`dom_before`, `dom_after`, `screenshot`, `button_styles`).
- **Known deviation from the spec, called out explicitly:** `flag_complex_language` lives in a new `app/analysis/readability.py` (Task 5) rather than inside `llm_classify.py` as the spec's prose suggested — noted in Task 5's own text as a single-responsibility file-boundary choice, not a silent drift.
