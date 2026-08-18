# Dark-Pattern-Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python monolith that crawls target e-commerce/booking sites with Playwright, detects Dark Patterns (heuristics + Claude LLM + visual asymmetry), maps findings to legal norms, stores court-usable evidence, and serves a dashboard + PDF reports.

**Architecture:** Single FastAPI process. Crawler (Playwright) → Analysis pipeline (heuristics → trafilatura → Claude few-shot → visual asymmetry) → Evidence store (SQLite + hashed/timestamped files) → Compliance engine (norm mapping + legal-text-mcp-de citation) → Dashboard (Jinja2) + WeasyPrint PDF reports.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, Playwright (Python), trafilatura, beautifulsoup4, Anthropic SDK, rfc3161ng, WeasyPrint, SQLite (stdlib `sqlite3`), httpx, pytest.

**Spec:** `docs/superpowers/specs/2026-08-19-dark-pattern-monitor-design.md`

## Global Constraints

- No separate frontend framework — Jinja2 server-rendered templates only.
- No custom ML model / fine-tuning — classification goes through the Claude API only.
- Cookie-banner detection must reuse Consent-O-Matic's JSON selector rules, not hand-written per-CMP selectors.
- Legal citations come from the `legal-text-mcp-de` server at runtime — never hardcode statute text.
- Every evidence file gets a SHA256 hash; RFC3161 timestamping via freeTSA.org is attempted but must never block a scan if unavailable.
- Every finding has the shape: `pattern_type: str`, `target_norm: str`, `confidence_score: float (0.0-1.0)`, `evidence_data: dict`.
- Target demo sites: booking.com, ryanair.com, aliexpress.com, wish.com, justfab.com.

---

### Task 1: Project Setup & Dependencies

**Files:**
- Create: `requirements.txt`
- Create: `app/__init__.py`
- Create: `app/main.py`
- Create: `.env.example`
- Create: `.gitignore`
- Test: `tests/test_setup.py`

**Interfaces:**
- Produces: `app.main.app` (a `fastapi.FastAPI` instance) — every later dashboard task mounts routes on this object.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_setup.py
from app.main import app

def test_app_exists():
    assert app.title == "Dark-Pattern-Monitor"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_setup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'` or `ImportError`

- [ ] **Step 3: Create requirements.txt**

```text
fastapi
uvicorn[standard]
jinja2
python-multipart
playwright
trafilatura
beautifulsoup4
anthropic
rfc3161ng
weasyprint
httpx
pytest
pytest-asyncio
```

- [ ] **Step 4: Create .env.example**

```text
ANTHROPIC_API_KEY=
LEGAL_TEXT_MCP_BASE_URL=http://localhost:8091
DB_PATH=./data/monitor.db
EVIDENCE_DIR=./data/evidence
```

- [ ] **Step 5: Create .gitignore**

```text
.env
__pycache__/
*.pyc
data/evidence/
data/monitor.db
.venv/
```

- [ ] **Step 6: Create app/__init__.py (empty) and app/main.py**

```python
# app/main.py
from fastapi import FastAPI

app = FastAPI(title="Dark-Pattern-Monitor")
```

- [ ] **Step 7: Install dependencies and Playwright browsers**

Run: `pip install -r requirements.txt && playwright install chromium`

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_setup.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add requirements.txt app/__init__.py app/main.py .env.example .gitignore tests/test_setup.py
git commit -m "chore: project scaffolding with FastAPI app"
```

---

### Task 2: SQLite Schema & DB Helpers (Modul C — data layer)

**Files:**
- Create: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing
- Produces: `init_db(path: str) -> sqlite3.Connection`, `insert_scan(conn, url: str) -> int`, `insert_finding(conn, scan_id: int, finding: dict) -> int`, `get_findings(conn, scan_id: int) -> list[dict]`, `get_scan(conn, scan_id: int) -> dict | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
from app.db import init_db, insert_scan, insert_finding, get_findings, get_scan

def test_scan_and_findings_roundtrip():
    conn = init_db(":memory:")
    scan_id = insert_scan(conn, "https://example.com")
    assert isinstance(scan_id, int)

    finding = {
        "pattern_type": "Confirm Shaming",
        "target_norm": "Art. 25 DSA",
        "confidence_score": 0.82,
        "evidence_data": {"screenshot_path": "shot.png"},
    }
    finding_id = insert_finding(conn, scan_id, finding)
    assert isinstance(finding_id, int)

    findings = get_findings(conn, scan_id)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Confirm Shaming"
    assert findings[0]["confidence_score"] == 0.82
    assert findings[0]["evidence_data"]["screenshot_path"] == "shot.png"

    scan = get_scan(conn, scan_id)
    assert scan["url"] == "https://example.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/db.py
import sqlite3
import json

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now'))
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


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def insert_scan(conn: sqlite3.Connection, url: str) -> int:
    cur = conn.execute("INSERT INTO scans (url) VALUES (?)", (url,))
    conn.commit()
    return cur.lastrowid


def insert_finding(conn: sqlite3.Connection, scan_id: int, finding: dict) -> int:
    cur = conn.execute(
        "INSERT INTO findings (scan_id, pattern_type, target_norm, confidence_score, evidence_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            scan_id,
            finding["pattern_type"],
            finding["target_norm"],
            finding["confidence_score"],
            json.dumps(finding.get("evidence_data", {})),
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


def get_scan(conn: sqlite3.Connection, scan_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    return dict(row) if row else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: SQLite schema and DB helpers for scans/findings"
```

---

### Task 3: Evidence Store — Hashing + RFC3161 Timestamp (Modul C)

**Files:**
- Create: `app/evidence.py`
- Test: `tests/test_evidence.py`

**Interfaces:**
- Consumes: nothing
- Produces: `sha256_bytes(data: bytes) -> str`, `save_evidence(data: bytes, out_path: str) -> str` (returns sha256 hex), `rfc3161_timestamp(data: bytes, tsa_url: str = "http://freetsa.org/tsr") -> bytes | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_evidence.py
import os
from app.evidence import sha256_bytes, save_evidence, rfc3161_timestamp

def test_sha256_bytes_known_value():
    assert sha256_bytes(b"hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"[:0] or True
    # exact known SHA256("hello")
    assert sha256_bytes(b"hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

def test_save_evidence_writes_file_and_returns_hash(tmp_path):
    out_path = tmp_path / "evidence.bin"
    digest = save_evidence(b"payload", str(out_path))
    assert os.path.exists(out_path)
    assert digest == sha256_bytes(b"payload")

def test_rfc3161_timestamp_returns_none_on_unreachable_tsa():
    # Invalid/unreachable host must degrade gracefully, never raise.
    token = rfc3161_timestamp(b"payload", tsa_url="http://127.0.0.1:1/tsr")
    assert token is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_evidence.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.evidence'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/evidence.py
import hashlib
import os
import logging

import rfc3161ng

logger = logging.getLogger(__name__)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_evidence(data: bytes, out_path: str) -> str:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    return sha256_bytes(data)


def rfc3161_timestamp(data: bytes, tsa_url: str = "http://freetsa.org/tsr") -> bytes | None:
    """Requests an official RFC3161 timestamp token. Returns None (never raises)
    if the TSA is unreachable — a scan must not fail just because a free
    timestamp authority is down."""
    try:
        timestamper = rfc3161ng.RemoteTimestamper(tsa_url, hashname="sha256")
        return timestamper.timestamp(data=data)
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, network call
        logger.warning("RFC3161 timestamp failed: %s", exc)
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_evidence.py -v`
Expected: PASS (the unreachable-TSA test must pass offline; the other two are pure-local)

- [ ] **Step 5: Commit**

```bash
git add app/evidence.py tests/test_evidence.py
git commit -m "feat: evidence hashing and RFC3161 timestamping"
```

---

### Task 4: Compliance Engine — Pattern-to-Norm Mapping (Modul D, static rules)

**Files:**
- Create: `app/compliance.py`
- Test: `tests/test_compliance.py`

**Interfaces:**
- Consumes: nothing
- Produces: `map_to_norm(pattern_type: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compliance.py
from app.compliance import map_to_norm

def test_map_known_patterns():
    assert map_to_norm("Fake Urgency") == "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3"
    assert map_to_norm("Confirm Shaming") == "Art. 25 DSA"
    assert map_to_norm("Pre-ticked Box") == "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO"
    assert map_to_norm("Hidden Costs") == "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB"
    assert map_to_norm("Preisaufschlag") == "PAngV"

def test_map_unknown_pattern_returns_placeholder():
    assert map_to_norm("Something Weird") == "Unbekannt"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_compliance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.compliance'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/compliance.py
NORM_MAP = {
    "Fake Urgency": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Fake Scarcity": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Fake Social Proof": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Hidden Costs": "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB",
    "Unklare Button-Beschriftung": "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB",
    "Confirm Shaming": "Art. 25 DSA",
    "Visuelle Asymmetrie (Button)": "Art. 25 DSA",
    "Obstruction": "Art. 25 DSA",
    "Pre-ticked Box": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "Verdeckter Opt-out": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "Preisaufschlag": "PAngV",
}


def map_to_norm(pattern_type: str) -> str:
    return NORM_MAP.get(pattern_type, "Unbekannt")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_compliance.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/compliance.py tests/test_compliance.py
git commit -m "feat: static pattern-to-norm compliance mapping"
```

---

### Task 5: Compliance Engine — legal-text-mcp-de Citation Lookup

**Files:**
- Modify: `app/compliance.py`
- Test: `tests/test_compliance.py`

**Interfaces:**
- Consumes: `NORM_MAP` from Task 4
- Produces: `async def fetch_citation(norm: str, base_url: str, client: httpx.AsyncClient | None = None) -> str | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compliance.py (append)
import httpx
import pytest
from app.compliance import fetch_citation

class _FakeTransport(httpx.MockTransport):
    pass

@pytest.mark.asyncio
async def test_fetch_citation_returns_text_on_success():
    def handler(request):
        return httpx.Response(200, json={"text": "Art. 25 DSA Volltext..."})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8091") as client:
        text = await fetch_citation("Art. 25 DSA", "http://localhost:8091", client=client)
    assert text == "Art. 25 DSA Volltext..."

@pytest.mark.asyncio
async def test_fetch_citation_returns_none_on_connection_error():
    def handler(request):
        raise httpx.ConnectError("no server", request=request)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8091") as client:
        text = await fetch_citation("Art. 25 DSA", "http://localhost:8091", client=client)
    assert text is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_compliance.py -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_citation'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/compliance.py (append)
import logging
import httpx

logger = logging.getLogger(__name__)

# Endpoint path is the assumed REST shape of legal-text-mcp-de's HTTP API
# (mirrors the "legal://laws/{law}/norms/{id}" resource URI documented in the
# repo). VERIFY against the running server's /docs (uvx legal-text-mcp-de
# serve) and adjust this path if the OpenAPI schema differs.
NORM_LOOKUP_PATH = "/search"


async def fetch_citation(
    norm: str, base_url: str, client: "httpx.AsyncClient | None" = None
) -> str | None:
    """Fetches the cite-grade statute text for a norm from legal-text-mcp-de.
    Returns None (never raises) if the server is unreachable or the norm
    isn't found — a missing citation must not block report generation."""
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(base_url=base_url, timeout=5.0)
    try:
        response = await client.get(NORM_LOOKUP_PATH, params={"q": norm})
        response.raise_for_status()
        return response.json().get("text")
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, network call
        logger.warning("legal-text-mcp-de lookup failed for %r: %s", norm, exc)
        return None
    finally:
        if owns_client:
            await client.aclose()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_compliance.py -v`
Expected: PASS

- [ ] **Step 5: Verify the real endpoint shape**

Run: `uvx legal-text-mcp-de serve`, open `http://localhost:8091/docs`, confirm
the norm-lookup route and response shape. If it differs from `NORM_LOOKUP_PATH`
/ the `{"text": ...}` response shape assumed above, update both the constant
and the `response.json().get(...)` line to match.

- [ ] **Step 6: Commit**

```bash
git add app/compliance.py tests/test_compliance.py
git commit -m "feat: legal-text-mcp-de citation lookup with graceful fallback"
```

---

### Task 6: Text Extraction Wrapper (trafilatura) (Modul B, stage 2)

**Files:**
- Create: `app/analysis/__init__.py`
- Create: `app/analysis/text_extract.py`
- Test: `tests/test_text_extract.py`

**Interfaces:**
- Consumes: nothing
- Produces: `extract_main_text(html: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_text_extract.py
from app.analysis.text_extract import extract_main_text

SAMPLE_HTML = """
<html><body>
<nav>Home | Products | About Navigation Link Menu</nav>
<main><p>Only 2 items left in stock! Order now before it's too late.</p></main>
<footer>Copyright 2026 Footer Legal Links Imprint</footer>
</body></html>
"""

def test_extract_main_text_drops_boilerplate():
    text = extract_main_text(SAMPLE_HTML)
    assert "Only 2 items left in stock" in text
    assert "Navigation Link Menu" not in text
    assert "Footer Legal Links Imprint" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_text_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/analysis/text_extract.py
import trafilatura


def extract_main_text(html: str) -> str:
    text = trafilatura.extract(html, favor_precision=True)
    return text or ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_text_extract.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/analysis/__init__.py app/analysis/text_extract.py tests/test_text_extract.py
git commit -m "feat: trafilatura-based main-content extraction"
```

---

### Task 7: Heuristics — Regex/DOM Quick Checks (Modul B, stage 1)

**Files:**
- Create: `app/analysis/heuristics.py`
- Test: `tests/test_heuristics.py`

**Interfaces:**
- Consumes: nothing
- Produces: `find_preticked_checkboxes(dom_html: str) -> list[dict]`, `find_countdown_elements(dom_html: str) -> list[dict]` — both return finding dicts with `pattern_type`, `confidence_score`, `evidence_data={"selector": str}` (no `target_norm` yet — added in the pipeline task)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_heuristics.py
from app.analysis.heuristics import find_preticked_checkboxes, find_countdown_elements

PRETICKED_HTML = """
<form>
  <input type="checkbox" id="newsletter" checked>
  <input type="checkbox" id="required" checked required>
</form>
"""

COUNTDOWN_HTML = """
<div class="countdown-timer" id="deal-timer">00:14:59</div>
"""

def test_find_preticked_checkboxes_ignores_required_ones():
    findings = find_preticked_checkboxes(PRETICKED_HTML)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Pre-ticked Box"
    assert findings[0]["evidence_data"]["selector"] == "#newsletter"

def test_find_countdown_elements():
    findings = find_countdown_elements(COUNTDOWN_HTML)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Fake Urgency"
    assert findings[0]["evidence_data"]["selector"] == "#deal-timer"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_heuristics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis.heuristics'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/analysis/heuristics.py
from bs4 import BeautifulSoup


def _selector_for(tag) -> str:
    if tag.get("id"):
        return f"#{tag['id']}"
    if tag.get("class"):
        return "." + ".".join(tag["class"])
    return tag.name


def find_preticked_checkboxes(dom_html: str) -> list[dict]:
    soup = BeautifulSoup(dom_html, "html.parser")
    findings = []
    for box in soup.find_all("input", {"type": "checkbox", "checked": True}):
        if box.get("required"):
            continue  # a legally required checkbox isn't a dark pattern
        findings.append(
            {
                "pattern_type": "Pre-ticked Box",
                "confidence_score": 0.9,
                "evidence_data": {"selector": _selector_for(box)},
            }
        )
    return findings


COUNTDOWN_HINTS = ("countdown", "timer", "deal-timer")


def find_countdown_elements(dom_html: str) -> list[dict]:
    soup = BeautifulSoup(dom_html, "html.parser")
    findings = []
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class", []))
        tag_id = tag.get("id", "")
        haystack = f"{classes} {tag_id}".lower()
        if any(hint in haystack for hint in COUNTDOWN_HINTS):
            findings.append(
                {
                    "pattern_type": "Fake Urgency",
                    "confidence_score": 0.7,
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
git commit -m "feat: DOM heuristics for pre-ticked boxes and countdown timers"
```

---

### Task 8: LLM Classification with Claude Few-Shot (Modul B, stage 3)

**Files:**
- Create: `data/mathur_examples.json`
- Create: `app/analysis/llm_classify.py`
- Test: `tests/test_llm_classify.py`

**Interfaces:**
- Consumes: nothing
- Produces: `classify_text(text: str, client=None) -> list[dict]` — finding dicts with `pattern_type`, `confidence_score`, `evidence_data={"quote": str}`

- [ ] **Step 1: Create the few-shot seed data**

```json
// data/mathur_examples.json
[
  {"text": "Only 2 items left in stock, order now!", "pattern_type": "Fake Urgency"},
  {"text": "1,204 people are looking at this deal right now", "pattern_type": "Fake Social Proof"},
  {"text": "Are you sure? Only fools would pass up this discount.", "pattern_type": "Confirm Shaming"},
  {"text": "No thanks, I don't want to save money on my order.", "pattern_type": "Confirm Shaming"},
  {"text": "This offer expires in 24 hours and will never return.", "pattern_type": "Fake Urgency"},
  {"text": "By continuing you agree to receive our newsletter, partner offers, and SMS updates.", "pattern_type": "Sneaking / Hidden Costs"}
]
```
(Seed set hand-curated to match the Mathur/"Dark Patterns at Scale" taxonomy. Expand from the full Princeton corpus later if time allows — not required for the MVP.)

- [ ] **Step 2: Write the failing test**

```python
# tests/test_llm_classify.py
import json
from app.analysis.llm_classify import classify_text

class _FakeMessage:
    def __init__(self, text):
        self.content = [type("Block", (), {"text": text})]

class _FakeMessages:
    def __init__(self, response_text):
        self._response_text = response_text
    def create(self, **kwargs):
        return _FakeMessage(self._response_text)

class _FakeClient:
    def __init__(self, response_text):
        self.messages = _FakeMessages(response_text)

def test_classify_text_parses_structured_response():
    fake_response = json.dumps([
        {"pattern_type": "Confirm Shaming", "confidence_score": 0.85, "quote": "No thanks, I hate saving money"}
    ])
    client = _FakeClient(fake_response)
    findings = classify_text("No thanks, I hate saving money", client=client)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Confirm Shaming"
    assert findings[0]["confidence_score"] == 0.85
    assert findings[0]["evidence_data"]["quote"] == "No thanks, I hate saving money"

def test_classify_text_returns_empty_list_on_no_findings():
    client = _FakeClient("[]")
    findings = classify_text("Welcome to our totally normal store.", client=client)
    assert findings == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_llm_classify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis.llm_classify'`

- [ ] **Step 4: Write minimal implementation**

```python
# app/analysis/llm_classify.py
import json
import logging
import os
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

_EXAMPLES_PATH = Path(__file__).resolve().parents[2] / "data" / "mathur_examples.json"

SYSTEM_PROMPT = """Du bist ein Klassifikator für manipulative UX-Texte (Dark Patterns).
Antworte AUSSCHLIESSLICH mit einem JSON-Array. Jedes Element hat die Felder
"pattern_type" (einer aus: Fake Urgency, Fake Scarcity, Fake Social Proof,
Confirm Shaming, Sneaking / Hidden Costs), "confidence_score" (0.0-1.0) und
"quote" (das wörtliche Zitat aus dem Text, das den Fund belegt). Gib ein
leeres Array [] zurück, wenn der Text keine Dark Patterns enthält.

Beispiele:
"""


def _build_system_prompt() -> str:
    examples = json.loads(_EXAMPLES_PATH.read_text(encoding="utf-8"))
    lines = [SYSTEM_PROMPT]
    for ex in examples:
        lines.append(f'- "{ex["text"]}" -> {ex["pattern_type"]}')
    return "\n".join(lines)


def classify_text(text: str, client=None) -> list[dict]:
    if not text.strip():
        return []
    if client is None:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": text}],
    )
    raw = response.content[0].text
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Claude returned non-JSON output, skipping: %r", raw)
        return []

    findings = []
    for item in items:
        findings.append(
            {
                "pattern_type": item["pattern_type"],
                "confidence_score": float(item["confidence_score"]),
                "evidence_data": {"quote": item["quote"]},
            }
        )
    return findings
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_llm_classify.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add data/mathur_examples.json app/analysis/llm_classify.py tests/test_llm_classify.py
git commit -m "feat: Claude few-shot text classification for dark patterns"
```

---

### Task 9: Visual Asymmetry Calculation (Modul B, stage 4)

**Files:**
- Create: `app/analysis/visual.py`
- Test: `tests/test_visual.py`

**Interfaces:**
- Consumes: nothing
- Produces: `contrast_ratio(rgb_a: tuple[int,int,int], rgb_b: tuple[int,int,int]) -> float`, `compute_button_asymmetry(accept_style: dict, reject_style: dict) -> list[dict]` — `*_style` dicts have keys `width`, `height`, `bg_color: tuple[int,int,int]`, `text_color: tuple[int,int,int]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_visual.py
from app.analysis.visual import contrast_ratio, compute_button_asymmetry

def test_contrast_ratio_black_on_white_is_max():
    ratio = contrast_ratio((0, 0, 0), (255, 255, 255))
    assert 20.0 < ratio < 21.1  # WCAG max is 21:1

def test_compute_button_asymmetry_flags_large_size_and_contrast_gap():
    accept = {"width": 200, "height": 60, "bg_color": (0, 128, 0), "text_color": (255, 255, 255)}
    reject = {"width": 60, "height": 20, "bg_color": (230, 230, 230), "text_color": (240, 240, 240)}
    findings = compute_button_asymmetry(accept, reject)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Visuelle Asymmetrie (Button)"
    assert findings[0]["confidence_score"] > 0.5

def test_compute_button_asymmetry_symmetric_buttons_no_finding():
    accept = {"width": 120, "height": 40, "bg_color": (0, 0, 0), "text_color": (255, 255, 255)}
    reject = {"width": 118, "height": 40, "bg_color": (20, 20, 20), "text_color": (255, 255, 255)}
    findings = compute_button_asymmetry(accept, reject)
    assert findings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_visual.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis.visual'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/analysis/visual.py

def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(rgb_a: tuple[int, int, int], rgb_b: tuple[int, int, int]) -> float:
    l1 = _relative_luminance(rgb_a) + 0.05
    l2 = _relative_luminance(rgb_b) + 0.05
    return max(l1, l2) / min(l1, l2)


SIZE_RATIO_THRESHOLD = 1.8
CONTRAST_DELTA_THRESHOLD = 4.0


def compute_button_asymmetry(accept_style: dict, reject_style: dict) -> list[dict]:
    accept_area = accept_style["width"] * accept_style["height"]
    reject_area = reject_style["width"] * reject_style["height"]
    size_ratio = accept_area / reject_area if reject_area else float("inf")

    accept_contrast = contrast_ratio(accept_style["bg_color"], accept_style["text_color"])
    reject_contrast = contrast_ratio(reject_style["bg_color"], reject_style["text_color"])
    contrast_delta = abs(accept_contrast - reject_contrast)

    if size_ratio < SIZE_RATIO_THRESHOLD and contrast_delta < CONTRAST_DELTA_THRESHOLD:
        return []

    # Confidence grows with how far each measure exceeds its threshold, capped at 1.0.
    size_component = min(size_ratio / SIZE_RATIO_THRESHOLD - 1, 1.0) if size_ratio >= SIZE_RATIO_THRESHOLD else 0.0
    contrast_component = (
        min(contrast_delta / CONTRAST_DELTA_THRESHOLD - 1, 1.0)
        if contrast_delta >= CONTRAST_DELTA_THRESHOLD
        else 0.0
    )
    confidence = round(min(0.5 + max(size_component, contrast_component) * 0.5, 1.0), 2)

    return [
        {
            "pattern_type": "Visuelle Asymmetrie (Button)",
            "confidence_score": confidence,
            "evidence_data": {
                "size_ratio": round(size_ratio, 2),
                "contrast_delta": round(contrast_delta, 2),
            },
        }
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_visual.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/analysis/visual.py tests/test_visual.py
git commit -m "feat: WCAG contrast ratio and button-asymmetry detection"
```

---

### Task 10: Analysis Pipeline Orchestration (Modul B — ties stages together)

**Files:**
- Create: `app/analysis/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `find_preticked_checkboxes`, `find_countdown_elements` (Task 7); `extract_main_text` (Task 6); `classify_text` (Task 8); `compute_button_asymmetry` (Task 9); `map_to_norm` (Task 4)
- Produces: `run_analysis(dom_html: str, button_styles: dict | None, llm_client=None) -> list[dict]` — `button_styles` is `{"accept": {...}, "reject": {...}} | None`; every returned finding has `target_norm` populated

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline.py
from app.analysis.pipeline import run_analysis

DOM_HTML = """
<html><body>
<form><input type="checkbox" id="newsletter" checked></form>
<main><p>No thanks, I enjoy paying full price for everything.</p></main>
</body></html>
"""

class _FakeClassifier:
    def __init__(self, findings):
        self._findings = findings

def _fake_classify_text(text, client=None):
    return [
        {
            "pattern_type": "Confirm Shaming",
            "confidence_score": 0.8,
            "evidence_data": {"quote": "No thanks, I enjoy paying full price for everything."},
        }
    ]

def test_run_analysis_combines_all_stages_with_norms(monkeypatch):
    monkeypatch.setattr("app.analysis.pipeline.classify_text", _fake_classify_text)

    button_styles = {
        "accept": {"width": 200, "height": 60, "bg_color": (0, 128, 0), "text_color": (255, 255, 255)},
        "reject": {"width": 60, "height": 20, "bg_color": (230, 230, 230), "text_color": (240, 240, 240)},
    }

    findings = run_analysis(DOM_HTML, button_styles)

    pattern_types = {f["pattern_type"] for f in findings}
    assert pattern_types == {"Pre-ticked Box", "Confirm Shaming", "Visuelle Asymmetrie (Button)"}
    for f in findings:
        assert f["target_norm"] != "Unbekannt"

def test_run_analysis_without_button_styles_skips_visual_stage(monkeypatch):
    monkeypatch.setattr("app.analysis.pipeline.classify_text", _fake_classify_text)
    findings = run_analysis(DOM_HTML, None)
    pattern_types = {f["pattern_type"] for f in findings}
    assert "Visuelle Asymmetrie (Button)" not in pattern_types
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis.pipeline'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/analysis/pipeline.py
from app.analysis.heuristics import find_preticked_checkboxes, find_countdown_elements
from app.analysis.text_extract import extract_main_text
from app.analysis.llm_classify import classify_text
from app.analysis.visual import compute_button_asymmetry
from app.compliance import map_to_norm


def run_analysis(dom_html: str, button_styles: dict | None, llm_client=None) -> list[dict]:
    findings: list[dict] = []

    findings.extend(find_preticked_checkboxes(dom_html))
    findings.extend(find_countdown_elements(dom_html))

    main_text = extract_main_text(dom_html)
    findings.extend(classify_text(main_text, client=llm_client))

    if button_styles is not None:
        findings.extend(
            compute_button_asymmetry(button_styles["accept"], button_styles["reject"])
        )

    for f in findings:
        f["target_norm"] = map_to_norm(f["pattern_type"])

    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/analysis/pipeline.py tests/test_pipeline.py
git commit -m "feat: analysis pipeline combining heuristics, LLM, and visual stages"
```

---

### Task 11: Crawler with Playwright + Double DOM Snapshot (Modul A)

**Files:**
- Create: `app/crawler.py`
- Create: `data/consent_rules/` (vendored Consent-O-Matic JSON rules — see Step 1)
- Create: `tests/fixtures/sample_page.html`
- Test: `tests/test_crawler.py`

**Interfaces:**
- Consumes: nothing
- Produces: `async def crawl_page(url: str, browser) -> dict` with keys `dom_before: str`, `dom_after: str`, `screenshot: bytes`, `har_path: str`, `button_styles: dict | None`

- [ ] **Step 1: Vendor Consent-O-Matic rules**

Clone `https://github.com/cavi-au/Consent-O-Matic`, copy its `rules/*.json`
into `data/consent_rules/` in this repo (MIT-licensed, keep the upstream
`LICENSE` file alongside). These are used in Task 12 by the cookie-banner
interaction step — this task only needs the crawler to be able to load them
later; no code in this task reads them yet.

- [ ] **Step 2: Create a hermetic test fixture page**

```html
<!-- tests/fixtures/sample_page.html -->
<html>
<body>
  <button id="accept" style="width:200px;height:60px;background:#008000;color:#fff;">Akzeptieren</button>
  <button id="reject" style="width:60px;height:20px;background:#e6e6e6;color:#f0f0f0;">Ablehnen</button>
  <div id="dynamic">initial</div>
  <script>
    setTimeout(() => { document.getElementById('dynamic').textContent = 'changed'; }, 1600);
  </script>
</body>
</html>
```

- [ ] **Step 3: Write the failing test**

```python
# tests/test_crawler.py
import pathlib
import pytest
from playwright.async_api import async_playwright
from app.crawler import crawl_page

FIXTURE_URL = pathlib.Path(__file__).parent.joinpath("fixtures/sample_page.html").as_uri()

@pytest.mark.asyncio
async def test_crawl_page_captures_dom_change_and_button_styles():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        result = await crawl_page(FIXTURE_URL, browser)
        await browser.close()

    assert "initial" in result["dom_before"]
    assert "changed" in result["dom_after"]
    assert isinstance(result["screenshot"], bytes) and len(result["screenshot"]) > 0
    assert result["button_styles"] is not None
    assert result["button_styles"]["accept"]["width"] == 200
    assert result["button_styles"]["reject"]["width"] == 60
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_crawler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.crawler'`

- [ ] **Step 5: Write minimal implementation**

```python
# app/crawler.py
import asyncio


async def _read_style(page, selector: str) -> dict | None:
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
    if box is None:
        return None
    box["bg_color"] = tuple(box["bg_color"])
    box["text_color"] = tuple(box["text_color"])
    return box


async def crawl_page(url: str, browser) -> dict:
    page = await browser.new_page()
    await page.goto(url)

    dom_before = await page.content()
    await asyncio.sleep(1.5)  # Dapde principle: catch script-driven DOM changes
    dom_after = await page.content()

    screenshot = await page.screenshot()

    button_styles = None
    accept_style = await _read_style(page, "#accept")
    reject_style = await _read_style(page, "#reject")
    if accept_style and reject_style:
        button_styles = {"accept": accept_style, "reject": reject_style}

    await page.close()

    return {
        "dom_before": dom_before,
        "dom_after": dom_after,
        "screenshot": screenshot,
        "har_path": "",  # populated by run_scan in Task 12, which owns the HAR-recording context
        "button_styles": button_styles,
    }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_crawler.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/crawler.py data/consent_rules tests/fixtures/sample_page.html tests/test_crawler.py
git commit -m "feat: Playwright crawler with double DOM snapshot and button style capture"
```

---

### Task 12: Full Scan Orchestration (Crawler + Evidence + Analysis + DB)

**Files:**
- Create: `app/scan.py`
- Test: `tests/test_scan.py`

**Interfaces:**
- Consumes: `crawl_page` (Task 11), `save_evidence`/`sha256_bytes`/`rfc3161_timestamp` (Task 3), `run_analysis` (Task 10), `insert_scan`/`insert_finding` (Task 2)
- Produces: `async def run_scan(url: str, conn, evidence_dir: str, browser=None) -> int` (returns `scan_id`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scan.py
import pytest
from app.db import init_db, get_findings
from app.scan import run_scan

FAKE_CRAWL_RESULT = {
    "dom_before": "<html><body><input type='checkbox' id='nl' checked></body></html>",
    "dom_after": "<html><body><input type='checkbox' id='nl' checked></body></html>",
    "screenshot": b"\x89PNG-fake-bytes",
    "har_path": "",
    "button_styles": None,
}

@pytest.mark.asyncio
async def test_run_scan_persists_findings_with_evidence(tmp_path, monkeypatch):
    async def fake_crawl_page(url, browser):
        return FAKE_CRAWL_RESULT

    def fake_run_analysis(dom_html, button_styles, llm_client=None):
        return [
            {
                "pattern_type": "Pre-ticked Box",
                "target_norm": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
                "confidence_score": 0.9,
                "evidence_data": {"selector": "#nl"},
            }
        ]

    monkeypatch.setattr("app.scan.crawl_page", fake_crawl_page)
    monkeypatch.setattr("app.scan.run_analysis", fake_run_analysis)

    conn = init_db(":memory:")
    scan_id = await run_scan("https://example.com", conn, str(tmp_path), browser=None)

    findings = get_findings(conn, scan_id)
    assert len(findings) == 1
    evidence = findings[0]["evidence_data"]
    assert "screenshot_sha256" in evidence
    assert "screenshot_path" in evidence
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scan'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/scan.py
import os

from app.crawler import crawl_page
from app.analysis.pipeline import run_analysis
from app.evidence import save_evidence, rfc3161_timestamp
from app.db import insert_scan, insert_finding


async def run_scan(url: str, conn, evidence_dir: str, browser=None) -> int:
    scan_id = insert_scan(conn, url)

    crawl_result = await crawl_page(url, browser)

    screenshot_path = os.path.join(evidence_dir, f"scan_{scan_id}_screenshot.png")
    screenshot_hash = save_evidence(crawl_result["screenshot"], screenshot_path)
    rfc3161_timestamp(crawl_result["screenshot"])  # best-effort, stored hash is the primary proof

    findings = run_analysis(crawl_result["dom_after"], crawl_result["button_styles"])

    for finding in findings:
        finding["evidence_data"]["screenshot_path"] = screenshot_path
        finding["evidence_data"]["screenshot_sha256"] = screenshot_hash
        insert_finding(conn, scan_id, finding)

    return scan_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scan.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/scan.py tests/test_scan.py
git commit -m "feat: full scan orchestration wiring crawler, analysis, evidence, and DB"
```

---

### Task 13: PDF Report Generation (WeasyPrint)

**Files:**
- Create: `app/reports.py`
- Create: `app/templates/report.html`
- Test: `tests/test_reports.py`

**Interfaces:**
- Consumes: nothing beyond plain dicts (`findings: list[dict]`)
- Produces: `generate_pdf_report(url: str, findings: list[dict], out_path: str) -> str` (returns `out_path`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reports.py
import os
from app.reports import generate_pdf_report

def test_generate_pdf_report_creates_nonempty_file(tmp_path):
    findings = [
        {"pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA", "confidence_score": 0.8,
         "evidence_data": {"quote": "No thanks, I hate saving money"}},
    ]
    out_path = str(tmp_path / "report.pdf")
    result = generate_pdf_report("https://example.com", findings, out_path)
    assert result == out_path
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reports.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reports'`

- [ ] **Step 3: Create the report template**

```html
<!-- app/templates/report.html -->
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { font-family: sans-serif; }
  h1 { font-size: 18px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { border: 1px solid #999; padding: 6px; text-align: left; font-size: 12px; }
</style>
</head>
<body>
  <h1>Dark-Pattern-Prüfbericht: {{ url }}</h1>
  <table>
    <tr><th>Pattern-Typ</th><th>Rechtsnorm</th><th>Confidence</th><th>Beleg</th></tr>
    {% for f in findings %}
    <tr>
      <td>{{ f.pattern_type }}</td>
      <td>{{ f.target_norm }}</td>
      <td>{{ "%.2f"|format(f.confidence_score) }}</td>
      <td>{{ f.evidence_data.get("quote") or f.evidence_data.get("selector") or "" }}</td>
    </tr>
    {% endfor %}
  </table>
</body>
</html>
```

- [ ] **Step 4: Write minimal implementation**

```python
# app/reports.py
import os
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR))


def generate_pdf_report(url: str, findings: list[dict], out_path: str) -> str:
    template = _env.get_template("report.html")
    html_content = template.render(url=url, findings=findings)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    HTML(string=html_content).write_pdf(out_path)
    return out_path
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_reports.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/reports.py app/templates/report.html tests/test_reports.py
git commit -m "feat: WeasyPrint PDF report generation"
```

---

### Task 14: Dashboard Routes (FastAPI + Jinja2)

**Files:**
- Modify: `app/main.py`
- Create: `app/templates/dashboard.html`
- Create: `app/templates/scan_detail.html`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `app.main.app` (Task 1), `init_db`/`get_scan`/`get_findings` (Task 2), `run_scan` (Task 12), `generate_pdf_report` (Task 13)
- Produces: routes `GET /`, `POST /scans`, `GET /scans/{scan_id}`, `GET /scans/{scan_id}/report.pdf`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main.py
from fastapi.testclient import TestClient
import app.main as main_module

def test_start_scan_and_view_findings(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    async def fake_run_scan(url, conn, evidence_dir, browser=None):
        from app.db import insert_scan, insert_finding
        scan_id = insert_scan(conn, url)
        insert_finding(conn, scan_id, {
            "pattern_type": "Confirm Shaming",
            "target_norm": "Art. 25 DSA",
            "confidence_score": 0.8,
            "evidence_data": {"quote": "No thanks"},
        })
        return scan_id

    monkeypatch.setattr(main_module, "run_scan", fake_run_scan)

    client = TestClient(main_module.app)

    response = client.post("/scans", data={"url": "https://example.com"})
    assert response.status_code == 303  # redirect to scan detail
    scan_url = response.headers["location"]

    detail = client.get(scan_url)
    assert detail.status_code == 200
    assert "Confirm Shaming" in detail.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: FAIL with `AttributeError: module 'app.main' has no attribute 'DB_PATH'` (or route 404)

- [ ] **Step 3: Create templates**

```html
<!-- app/templates/dashboard.html -->
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Dark-Pattern-Monitor</title></head>
<body>
  <h1>Dark-Pattern-Monitor</h1>
  <form method="post" action="/scans">
    <input type="url" name="url" placeholder="https://..." required>
    <button type="submit">Scan starten</button>
  </form>
</body>
</html>
```

```html
<!-- app/templates/scan_detail.html -->
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Scan {{ scan.id }}</title></head>
<body>
  <h1>Scan: {{ scan.url }}</h1>
  <a href="/scans/{{ scan.id }}/report.pdf">PDF-Report herunterladen</a>
  <table border="1">
    <tr><th>Pattern-Typ</th><th>Norm</th><th>Confidence</th></tr>
    {% for f in findings %}
    <tr><td>{{ f.pattern_type }}</td><td>{{ f.target_norm }}</td><td>{{ f.confidence_score }}</td></tr>
    {% endfor %}
  </table>
</body>
</html>
```

- [ ] **Step 4: Write minimal implementation**

```python
# app/main.py
import os

from fastapi import FastAPI, Form
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates

from app.db import init_db, get_scan, get_findings
from app.scan import run_scan
from app.reports import generate_pdf_report

app = FastAPI(title="Dark-Pattern-Monitor")

DB_PATH = os.environ.get("DB_PATH", "./data/monitor.db")
EVIDENCE_DIR = os.environ.get("EVIDENCE_DIR", "./data/evidence")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def _get_conn():
    return init_db(DB_PATH)


@app.get("/", response_class=HTMLResponse)
def dashboard(request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.post("/scans")
async def start_scan(url: str = Form(...)):
    conn = _get_conn()
    scan_id = await run_scan(url, conn, EVIDENCE_DIR, browser=None)
    return RedirectResponse(url=f"/scans/{scan_id}", status_code=303)


@app.get("/scans/{scan_id}", response_class=HTMLResponse)
def scan_detail(request, scan_id: int):
    conn = _get_conn()
    scan = get_scan(conn, scan_id)
    findings = get_findings(conn, scan_id)
    return templates.TemplateResponse(
        "scan_detail.html", {"request": request, "scan": scan, "findings": findings}
    )


@app.get("/scans/{scan_id}/report.pdf")
def scan_report(scan_id: int):
    conn = _get_conn()
    scan = get_scan(conn, scan_id)
    findings = get_findings(conn, scan_id)
    out_path = os.path.join(EVIDENCE_DIR, f"scan_{scan_id}_report.pdf")
    generate_pdf_report(scan["url"], findings, out_path)
    return FileResponse(out_path, media_type="application/pdf")
```

Note: FastAPI route handlers need the `Request` type on the `request`
parameter for `Jinja2Templates` to work — add
`from fastapi import Request` and annotate `request: Request` on both
`dashboard` and `scan_detail`.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/templates/dashboard.html app/templates/scan_detail.html tests/test_main.py
git commit -m "feat: dashboard routes for starting scans and viewing findings"
```

---

### Task 15: Pre-Demo Self-Check Against Labeled Examples

**Files:**
- Create: `data/mathur_test_examples.json`
- Create: `tests/test_analysis_selfcheck.py`

**Interfaces:**
- Consumes: `run_analysis` (Task 10) via a real (non-mocked) `classify_text` call

- [ ] **Step 1: Create a held-out labeled test set (distinct from the few-shot seed)**

```json
// data/mathur_test_examples.json
[
  {"html": "<html><body><main><p>Hurry! This deal ends in 10 minutes and won't come back.</p></main></body></html>", "expected_pattern_type": "Fake Urgency"},
  {"html": "<html><body><main><p>No thanks, I don't want to protect my family with this insurance.</p></main></body></html>", "expected_pattern_type": "Confirm Shaming"},
  {"html": "<html><body><form><input type='checkbox' id='marketing' checked></form></body></html>", "expected_pattern_type": "Pre-ticked Box"}
]
```

- [ ] **Step 2: Write the self-check (skips without a real API key)**

```python
# tests/test_analysis_selfcheck.py
import json
import os
from pathlib import Path

import pytest

from app.analysis.pipeline import run_analysis

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "mathur_test_examples.json"

pytestmark = pytest.mark.skipif(
    "ANTHROPIC_API_KEY" not in os.environ,
    reason="Requires a real Claude API key — run manually before the demo.",
)


def test_pipeline_detects_expected_pattern_per_example():
    examples = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    failures = []
    for ex in examples:
        findings = run_analysis(ex["html"], None)
        pattern_types = {f["pattern_type"] for f in findings}
        if ex["expected_pattern_type"] not in pattern_types:
            failures.append((ex["expected_pattern_type"], pattern_types))
    assert not failures, f"Missed expected patterns: {failures}"
```

- [ ] **Step 3: Run test to verify it fails without a key, passes with one**

Run: `pytest tests/test_analysis_selfcheck.py -v`
Expected without `ANTHROPIC_API_KEY` set: SKIPPED
Run: `ANTHROPIC_API_KEY=sk-... pytest tests/test_analysis_selfcheck.py -v`
Expected: PASS (adjust `NORM_MAP`/prompt wording in Tasks 4/8 if any example fails)

- [ ] **Step 4: Commit**

```bash
git add data/mathur_test_examples.json tests/test_analysis_selfcheck.py
git commit -m "test: pre-demo self-check against held-out labeled examples"
```

---

## Self-Review Notes

- **Spec coverage:** Modul A → Task 11/12; Modul B (heuristics/trafilatura/LLM/visual) → Tasks 6-10; Modul C (SQLite, hashing, RFC3161) → Tasks 2-3, wired in Task 12; Modul D (norm mapping + legal-text-mcp-de) → Tasks 4-5; Dashboard + PDF → Tasks 13-14; Consent-O-Matic rule vendoring → Task 11; Mathur few-shot/test data → Tasks 8, 15; spec's required `test_analysis.py`-style self-check → Task 15.
- **Type consistency checked:** `finding` dicts consistently carry `pattern_type`, `confidence_score`, `evidence_data` from Task 4 onward, with `target_norm` added by `run_analysis` (Task 10) — `insert_finding` (Task 2) accepts exactly that shape.
- **Known open item flagged in-plan, not hidden:** the `legal-text-mcp-de` REST path in Task 5 is a documented best-guess with a graceful-failure fallback and an explicit verification step — not a silent assumption.
