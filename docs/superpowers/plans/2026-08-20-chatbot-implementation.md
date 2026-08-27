# Findings-Chatbot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single-scan chat endpoint that lets Verbraucherzentrale
case-workers ask Claude questions about a completed scan's findings, with
the full scan context (pages + findings) supplied directly in the prompt,
mandatory disclaimer + source citation baked into the system prompt, and a
tool-use fallback for on-demand finding detail / fresh norm-text lookups —
wired into `scan_detail.html` via a plain JS fetch, no persistence.

**Architecture:** New `app/chat.py` module implements architecture option
(c) from the design brainstorm as the primary path (`build_scan_context`
renders every page + finding of one scan as a compact text block, embedded
in the system prompt) with option (a) (direct wrappers around
`app/db.py`/`app/compliance.py` functions, exposed as two Claude tools) as
the fallback for "give me more detail on finding X" / "what's the full text
of a norm not in my context". `chat_with_scan()` runs a manual tool-use loop
against the existing `_LLM_CLIENT` (built exactly the way `app/main.py`
already builds it — `anthropic.Anthropic(api_key=...)` only when
`ANTHROPIC_API_KEY` is set) and degrades to a fixed "chat unavailable"
string when that client is `None`, matching how the rest of the app already
treats a missing key. A new `POST /scans/{scan_id}/chat` route in
`app/main.py` is the only new HTTP surface; chat history is passed in by the
caller on every request and never written to SQLite — it evaporates on page
reload, per the "no persistence" decision.

**Tech Stack:** No new dependencies — reuses `anthropic` (already in
`requirements.txt`, same client-construction pattern as `app/main.py` /
`app/analysis/llm_classify.py`), `httpx` (already used by
`app/compliance.py:fetch_citation`), `fastapi`/`pydantic` (already used for
`ExtensionScanRequest` in `app/main.py`), plain `<script>` JS in the
existing Jinja2 templates.

**Spec:** `docs/superpowers/specs/2026-08-20-chatbot-design-brainstorm.md`

## Global Constraints

- No new pip dependencies — every piece of this feature is built on
  `anthropic`, `httpx`, `fastapi`, `pydantic`, all already installed.
- No new DB tables or schema changes — chat history is request-scoped only,
  supplied by the caller each turn, never persisted.
- Model id is `"claude-sonnet-5"` for every chat/tool-loop call — the exact
  string already used by `app/analysis/llm_classify.py:classify_text` and
  `app/site_crawler.py`'s LLM calls in this codebase; match existing
  convention, don't introduce a second model choice.
- `chat_with_scan` and everything it calls must accept `llm_client=None` and
  degrade to a fixed, non-crashing response — the same "construct only if
  `ANTHROPIC_API_KEY` is set, else `None`" contract `app/main.py`'s
  `_LLM_CLIENT` already follows. No new way of constructing an Anthropic
  client is introduced.
- Reuse `app.compliance.fetch_citation` and `app.compliance.map_to_norm`
  as-is — never reimplement norm lookup or mapping logic in `app/chat.py`.
- Every chat reply's correctness is enforced through the system prompt
  (mandatory disclaimer + mandatory Finding-ID/Norm citation), not through
  post-hoc validation of Claude's output — consistent with how
  `llm_classify.py` trusts its few-shot prompt rather than double-checking
  results.
- Do not modify `app/scan.py`, `app/site_crawler.py`, or `extension/` —
  those are being edited concurrently elsewhere. `app/chat.py` defines its
  own `LEGAL_TEXT_MCP_BASE_URL` default (same value as `app/scan.py`'s)
  instead of importing it, to avoid coupling the chat module to a file
  under concurrent edit.
- Follow existing test conventions: `pytest.mark.asyncio` for async tests,
  hand-rolled fake `client`/`messages`/response objects (see
  `tests/test_llm_classify.py`, `tests/test_site_crawler.py`) rather than a
  mocking library, `TestClient`/`monkeypatch` for route tests (see
  `tests/test_main.py`).

---

### Task 1: Scan Context Builder

**Files:**
- Create: `app/chat.py`
- Test: `tests/test_chat.py`

**Interfaces:**
- Consumes: `get_scan`, `get_pages`, `get_findings` from `app/db.py`
  (existing, signatures: `get_scan(conn, scan_id) -> dict | None`,
  `get_pages(conn, scan_id) -> list[dict]`,
  `get_findings(conn, scan_id) -> list[dict]`)
- Produces: `build_scan_context(conn: sqlite3.Connection, scan_id: int) -> str`
  — later tasks embed this text block into the chat system prompt.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chat.py
from app.db import init_db, insert_scan, insert_page, insert_finding
from app.chat import build_scan_context


def _conn_with_scan():
    conn = init_db(":memory:")
    scan_id = insert_scan(conn, "https://example.com")
    page_id = insert_page(conn, scan_id, "https://example.com/checkout", "checkout_payment")
    finding_id = insert_finding(
        conn,
        scan_id,
        {
            "pattern_type": "Confirm Shaming",
            "target_norm": "Art. 25 DSA",
            "confidence_score": 0.8,
            "evidence_data": {"quote": "No thanks, I hate saving money", "citation": "Art. 25 DSA Volltext..."},
        },
        page_id=page_id,
    )
    return conn, scan_id, page_id, finding_id


def test_build_scan_context_includes_scan_pages_and_findings():
    conn, scan_id, page_id, finding_id = _conn_with_scan()

    context = build_scan_context(conn, scan_id)

    assert "https://example.com" in context
    assert "checkout_payment" in context
    assert f"Finding #{finding_id}" in context
    assert "Confirm Shaming" in context
    assert "Art. 25 DSA" in context
    assert "No thanks, I hate saving money" in context
    assert "Art. 25 DSA Volltext..." in context  # already-cached citation is reused, not re-fetched


def test_build_scan_context_handles_scan_with_no_findings():
    conn = init_db(":memory:")
    scan_id = insert_scan(conn, "https://empty.example.com")

    context = build_scan_context(conn, scan_id)

    assert "https://empty.example.com" in context
    assert "Funde (0)" in context
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.chat'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/chat.py
import sqlite3

from app.db import get_findings, get_pages, get_scan


def build_scan_context(conn: sqlite3.Connection, scan_id: int) -> str:
    """Renders one scan's pages + findings as a compact text block for the
    chat system prompt — architecture option (c) from the design brainstorm
    (full scan context directly in the prompt, no retrieval). Findings
    already carry a cached `citation` in `evidence_data` (set by
    `app/scan.py`'s `citation_cache` during the scan) — that cached text is
    surfaced here and reused as-is, never re-fetched per chat message."""
    scan = get_scan(conn, scan_id)
    pages = get_pages(conn, scan_id)
    findings = get_findings(conn, scan_id)
    page_url_by_id = {p["id"]: p["url"] for p in pages}

    lines = [f"Scan-URL: {scan['url']}", f"Gestartet: {scan['started_at']}", ""]

    if pages:
        lines.append("Gecrawlte Seiten:")
        for p in pages:
            lines.append(f"- Seite {p['id']}: {p['url']} (Kategorie: {p['category']})")
        lines.append("")

    lines.append(f"Funde ({len(findings)}):")
    for f in findings:
        page_url = page_url_by_id.get(f.get("page_id"), scan["url"])
        evidence = f["evidence_data"]
        excerpt = evidence.get("quote") or evidence.get("selector") or evidence.get("excerpt") or ""
        citation = evidence.get("citation")
        lines.append(
            f"- Finding #{f['id']} | {f['pattern_type']} | Norm: {f['target_norm']} | "
            f"Confidence: {f['confidence_score']} | Seite: {page_url}"
        )
        if excerpt:
            lines.append(f'  Beleg: "{excerpt}"')
        if citation:
            lines.append(f"  Normzitat (bereits vorhanden): {citation}")

    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/chat.py tests/test_chat.py
git commit -m "feat: scan context builder for chatbot prompt"
```

---

### Task 2: Chat System Prompt, Disclaimer, and Fallback Tools

**Files:**
- Modify: `app/chat.py`
- Test: `tests/test_chat.py`

**Interfaces:**
- Consumes: `build_scan_context` (Task 1), `app.compliance.fetch_citation`
  (existing: `async def fetch_citation(norm: str, base_url: str, client=None) -> str | None`),
  `get_findings` (existing)
- Produces: `SYSTEM_PROMPT_TEMPLATE: str` (has one `{context}` placeholder),
  `CHAT_TOOLS: list[dict]` (Anthropic tool definitions),
  `async def _execute_tool(name: str, tool_input: dict, conn: sqlite3.Connection, scan_id: int, http_client: httpx.AsyncClient) -> str`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chat.py`:

```python
import httpx
import pytest

from app.chat import CHAT_TOOLS, SYSTEM_PROMPT_TEMPLATE, _execute_tool


def test_system_prompt_template_has_disclaimer_and_citation_requirement():
    rendered = SYSTEM_PROMPT_TEMPLATE.format(context="Scan-URL: https://example.com")
    assert "keine Rechtsberatung" in rendered
    assert "Finding-ID" in rendered
    assert "Verbraucherzentrale" in rendered
    assert "https://example.com" in rendered


def test_chat_tools_declares_finding_detail_and_norm_citation_tools():
    tool_names = {t["name"] for t in CHAT_TOOLS}
    assert tool_names == {"get_finding_detail", "get_norm_citation"}


@pytest.mark.asyncio
async def test_execute_tool_get_finding_detail_returns_full_evidence():
    conn, scan_id, page_id, finding_id = _conn_with_scan()

    result = await _execute_tool(
        "get_finding_detail", {"finding_id": finding_id}, conn, scan_id, http_client=None
    )

    assert "No thanks, I hate saving money" in result


@pytest.mark.asyncio
async def test_execute_tool_get_finding_detail_reports_missing_finding():
    conn, scan_id, page_id, finding_id = _conn_with_scan()

    result = await _execute_tool(
        "get_finding_detail", {"finding_id": 9999}, conn, scan_id, http_client=None
    )

    assert "nicht" in result.lower()


@pytest.mark.asyncio
async def test_execute_tool_get_norm_citation_fetches_on_demand(monkeypatch):
    conn, scan_id, page_id, finding_id = _conn_with_scan()

    async def fake_fetch_citation(norm, base_url, client=None):
        return f"Volltext von {norm}"

    monkeypatch.setattr("app.chat.fetch_citation", fake_fetch_citation)

    result = await _execute_tool(
        "get_norm_citation", {"norm": "PAngV"}, conn, scan_id, http_client=None
    )

    assert result == "Volltext von PAngV"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat.py -v`
Expected: FAIL with `ImportError: cannot import name 'CHAT_TOOLS'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/chat.py` (needs new imports at the top — replace the existing
import block with):

```python
import json
import sqlite3

import httpx

from app.compliance import fetch_citation
from app.db import get_findings, get_pages, get_scan

# Same default as app/scan.py's LEGAL_TEXT_MCP_BASE_URL. Kept as its own
# constant here (not imported from app.scan) so the chat module doesn't
# couple to scan orchestration for a single default string.
LEGAL_TEXT_MCP_BASE_URL = __import__("os").environ.get("LEGAL_TEXT_MCP_BASE_URL", "http://localhost:8091")


SYSTEM_PROMPT_TEMPLATE = """Du bist der Kali-Analyse-Assistent für Sachbearbeiter:innen \
der Verbraucherzentrale. Du hilfst dabei, die Funde eines abgeschlossenen \
Dark-Pattern-Scans einzuordnen.

WICHTIG — keine Rechtsberatung: Du ordnest gefundene Muster nur Normen zu \
und erklärst den Kontext. Für eine rechtsverbindliche Einschätzung verweise \
immer auf die Verbraucherzentrale oder einen Anwalt/eine Anwältin.

WICHTIG — Quellenpflicht: Jede Aussage über einen Fund muss die konkrete \
Finding-ID (z.B. "Finding #12") und/oder die zitierte Norm nennen, auf der \
sie beruht. Erfinde keine Funde oder Normen, die nicht im Kontext oder in \
einem Tool-Ergebnis stehen.

Bekannte Präzedenzfälle zur Einordnung (nicht erschöpfend):
- LG Berlin II (2025): "Checkout Parkour" + Fake-Countdown + manipulative \
"No thanks"-Links → Verstoß gegen § 5 UWG und Art. 25 DSA.
- BGH/EuGH (2020, "Planet49"): vorangekreuzte Checkboxen sind keine \
wirksame DSGVO-Einwilligung.
- OLG Köln (2024): "Accept All" sofort sichtbar, "Reject" erst auf zweiter \
Ebene → unwirksame Einwilligung durch Nudging.

Scan-Kontext:
{context}
"""

CHAT_TOOLS = [
    {
        "name": "get_finding_detail",
        "description": (
            "Liefert die vollstaendigen Beweisdaten (evidence_data) zu einer "
            "einzelnen Finding-ID dieses Scans, z.B. vollstaendiges Zitat, "
            "Screenshot-Pfad, HAR-Hash — fuer Details, die im Scan-Kontext "
            "nur gekuerzt vorliegen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"finding_id": {"type": "integer"}},
            "required": ["finding_id"],
        },
    },
    {
        "name": "get_norm_citation",
        "description": (
            "Holt den vollen Gesetzestext einer Rechtsnorm von "
            "legal-text-mcp-de, falls er noch nicht im Scan-Kontext "
            "vorhanden ist (kein bereits gecachtes Normzitat)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"norm": {"type": "string"}},
            "required": ["norm"],
        },
    },
]


async def _execute_tool(
    name: str, tool_input: dict, conn: sqlite3.Connection, scan_id: int, http_client
) -> str:
    if name == "get_finding_detail":
        findings = get_findings(conn, scan_id)
        match = next((f for f in findings if f["id"] == tool_input["finding_id"]), None)
        if match is None:
            return f"Finding #{tool_input['finding_id']} wurde in diesem Scan nicht gefunden."
        return json.dumps(match["evidence_data"], ensure_ascii=False)

    if name == "get_norm_citation":
        citation = await fetch_citation(tool_input["norm"], LEGAL_TEXT_MCP_BASE_URL, client=http_client)
        return citation or f"Kein Zitat fuer Norm {tool_input['norm']!r} gefunden."

    return f"Unbekanntes Tool: {name}"
```

(Move the `build_scan_context` function from Task 1 below these new
definitions, or above — order doesn't matter; keep both in the same file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/chat.py tests/test_chat.py
git commit -m "feat: chat system prompt, disclaimer, and fallback tool definitions"
```

---

### Task 3: Chat Orchestration — Manual Tool-Use Loop

**Files:**
- Modify: `app/chat.py`
- Test: `tests/test_chat.py`

**Interfaces:**
- Consumes: `build_scan_context`, `SYSTEM_PROMPT_TEMPLATE`, `CHAT_TOOLS`,
  `_execute_tool` (Tasks 1-2); `get_scan` (existing)
- Produces: `async def chat_with_scan(scan_id: int, message: str, history: list[dict], conn: sqlite3.Connection, llm_client=None, http_client=None) -> str`
  — `history` is a list of `{"role": "user"|"assistant", "content": str}`
  dicts (the Anthropic message shape); the caller (the FastAPI route in
  Task 4) is responsible for holding onto history across turns, this
  function does not persist anything.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chat.py`:

```python
from app.chat import chat_with_scan


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeToolUseBlock:
    def __init__(self, name, input, id):
        self.type = "tool_use"
        self.name = name
        self.input = input
        self.id = id


class _FakeResponse:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class _FakeSequentialMessages:
    """Returns one canned response per call, in order, and records every
    call's kwargs so tests can inspect the messages/system sent to Claude."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeSequentialMessages(responses)


@pytest.mark.asyncio
async def test_chat_with_scan_returns_fixed_message_without_llm_client():
    conn, scan_id, page_id, finding_id = _conn_with_scan()

    reply = await chat_with_scan(scan_id, "Warum ist das ein Dark Pattern?", [], conn, llm_client=None)

    assert "kein ANTHROPIC_API_KEY" in reply


@pytest.mark.asyncio
async def test_chat_with_scan_returns_final_text_without_tool_use():
    conn, scan_id, page_id, finding_id = _conn_with_scan()
    client = _FakeClient([_FakeResponse("end_turn", [_FakeTextBlock("Finding #1 ist Confirm Shaming (Art. 25 DSA).")])])

    reply = await chat_with_scan(scan_id, "Was wurde gefunden?", [], conn, llm_client=client)

    assert reply == "Finding #1 ist Confirm Shaming (Art. 25 DSA)."
    sent_system = client.messages.calls[0]["system"]
    assert "https://example.com" in sent_system  # scan context was embedded


@pytest.mark.asyncio
async def test_chat_with_scan_executes_tool_then_returns_final_answer():
    conn, scan_id, page_id, finding_id = _conn_with_scan()
    tool_call = _FakeToolUseBlock("get_finding_detail", {"finding_id": finding_id}, "tool_1")
    client = _FakeClient([
        _FakeResponse("tool_use", [tool_call]),
        _FakeResponse("end_turn", [_FakeTextBlock(f"Laut Finding #{finding_id} liegt Confirm Shaming vor.")]),
    ])

    reply = await chat_with_scan(scan_id, "Warum ist Finding 1 ein Dark Pattern?", [], conn, llm_client=client)

    assert f"Finding #{finding_id}" in reply
    second_call_messages = client.messages.calls[1]["messages"]
    tool_result_messages = [
        m for m in second_call_messages
        if m["role"] == "user" and isinstance(m["content"], list) and m["content"][0].get("type") == "tool_result"
    ]
    assert len(tool_result_messages) == 1
    assert tool_result_messages[0]["content"][0]["tool_use_id"] == "tool_1"


@pytest.mark.asyncio
async def test_chat_with_scan_returns_message_for_unknown_scan():
    conn = init_db(":memory:")

    reply = await chat_with_scan(9999, "Hallo?", [], conn, llm_client=_FakeClient([]))

    assert "9999" in reply
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat.py -v`
Expected: FAIL with `ImportError: cannot import name 'chat_with_scan'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/chat.py`:

```python
MODEL = "claude-sonnet-5"
# ponytail: hard iteration cap instead of detecting true loops — good enough
# for a handful of fallback tool calls per chat turn; raise if a real
# multi-tool workflow needs more.
MAX_TOOL_ITERATIONS = 5


async def chat_with_scan(
    scan_id: int,
    message: str,
    history: list[dict],
    conn: sqlite3.Connection,
    llm_client=None,
    http_client=None,
) -> str:
    """Answers one chat turn about scan_id. Degrades to a fixed message
    when llm_client is None — the same "construct only if ANTHROPIC_API_KEY
    is set" contract app.main._LLM_CLIENT already follows, reused as-is
    (this function never constructs its own client)."""
    if llm_client is None:
        return "Chat nicht verfuegbar: kein ANTHROPIC_API_KEY konfiguriert."

    scan = get_scan(conn, scan_id)
    if scan is None:
        return f"Scan {scan_id} wurde nicht gefunden."

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=build_scan_context(conn, scan_id))
    messages = list(history) + [{"role": "user", "content": message}]

    owns_http_client = http_client is None
    if owns_http_client:
        http_client = httpx.AsyncClient(timeout=5.0)

    try:
        for _ in range(MAX_TOOL_ITERATIONS):
            response = llm_client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=system_prompt,
                tools=CHAT_TOOLS,
                messages=messages,
            )

            if response.stop_reason != "tool_use":
                return next((b.text for b in response.content if b.type == "text"), "")

            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result_text = await _execute_tool(block.name, block.input, conn, scan_id, http_client)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_text})
            messages.append({"role": "user", "content": tool_results})

        return "Entschuldigung, die Antwort konnte nicht abgeschlossen werden (zu viele Tool-Aufrufe)."
    finally:
        if owns_http_client:
            await http_client.aclose()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/chat.py tests/test_chat.py
git commit -m "feat: chat_with_scan manual tool-use loop with graceful no-key fallback"
```

---

### Task 4: `POST /scans/{scan_id}/chat` Route

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `chat_with_scan` (Task 3), `get_scan` (existing), `_get_conn`
  dependency (existing), `_LLM_CLIENT` (existing module-level constant)
- Produces: route `POST /scans/{scan_id}/chat` — request body
  `{"message": str, "history": [{"role": str, "content": str}, ...]}`,
  response body `{"reply": str}`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main.py`:

```python
def test_scan_chat_returns_reply_from_chat_with_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))

    from app.db import init_db, insert_scan
    conn = init_db(str(tmp_path / "test.db"))
    scan_id = insert_scan(conn, "https://example.com")
    conn.close()

    received = {}

    async def fake_chat_with_scan(scan_id_arg, message, history, conn, llm_client=None):
        received["scan_id"] = scan_id_arg
        received["message"] = message
        received["history"] = history
        return "Feste Test-Antwort"

    monkeypatch.setattr(main_module, "chat_with_scan", fake_chat_with_scan)

    with TestClient(main_module.app) as client:
        response = client.post(
            f"/scans/{scan_id}/chat",
            json={"message": "Warum ist das ein Dark Pattern?", "history": []},
        )

    assert response.status_code == 200
    assert response.json() == {"reply": "Feste Test-Antwort"}
    assert received["scan_id"] == scan_id
    assert received["message"] == "Warum ist das ein Dark Pattern?"


def test_scan_chat_404_for_missing_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    with TestClient(main_module.app) as client:
        response = client.post("/scans/9999/chat", json={"message": "Hallo?", "history": []})
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v -k scan_chat`
Expected: FAIL with `404 Not Found` (route doesn't exist yet) or
`AttributeError: module 'app.main' has no attribute 'chat_with_scan'`

- [ ] **Step 3: Write minimal implementation**

In `app/main.py`, add the import (next to the existing `from app.scan import
run_site_scan` line):

```python
from app.chat import chat_with_scan
```

Add these near the existing `ExtensionScanRequest` model:

```python
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
```

Add the route (after `page_detail`, before `scan_report`):

```python
@app.post("/scans/{scan_id}/chat")
async def scan_chat(
    scan_id: int,
    body: ChatRequest,
    conn: sqlite3.Connection = Depends(_get_conn),
):
    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    reply = await chat_with_scan(
        scan_id,
        body.message,
        [m.model_dump() for m in body.history],
        conn,
        llm_client=_LLM_CLIENT,
    )
    return JSONResponse({"reply": reply})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v -k scan_chat`
Expected: PASS

- [ ] **Step 5: Run the full test_main.py suite to confirm no regressions**

Run: `pytest tests/test_main.py -v`
Expected: PASS (all tests, including the pre-existing scan/page routes)

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_main.py
git commit -m "feat: POST /scans/{scan_id}/chat route"
```

---

### Task 5: Chat Widget in `scan_detail.html`

**Files:**
- Modify: `app/templates/scan_detail.html`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `POST /scans/{scan_id}/chat` (Task 4)
- Produces: no new Python interface — a chat form + log `<div>` + inline
  `<script>` on the scan detail page, following the existing plain-HTML/no-JS-framework
  convention already used throughout `app/templates/`.

`page_detail.html` is deliberately left unchanged: the chat's context is
always the whole scan (per the design brainstorm's Decision 1, scope is one
`scan_id`, not one page), so the widget belongs on the scan-level page. The
existing "Zurueck zur Scan-Uebersicht" link on `page_detail.html` already
gets a user back to the chat.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main.py`:

```python
def test_scan_detail_renders_chat_widget(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    from app.db import init_db, insert_scan
    conn = init_db(str(tmp_path / "test.db"))
    scan_id = insert_scan(conn, "https://example.com")
    conn.close()

    with TestClient(main_module.app) as client:
        response = client.get(f"/scans/{scan_id}")

    assert response.status_code == 200
    assert 'id="chat-form"' in response.text
    assert f"/scans/{scan_id}/chat" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v -k chat_widget`
Expected: FAIL — `assert 'id="chat-form"' in response.text` is False

- [ ] **Step 3: Add the widget to the template**

In `app/templates/scan_detail.html`, insert this block right before the
closing `</body>` tag:

```html
  <h2>Chat: Fragen zu diesem Scan</h2>
  <div id="chat-log"></div>
  <form id="chat-form">
    <input type="text" id="chat-input" placeholder="Frage zum Scan..." required style="width:60%">
    <button type="submit">Senden</button>
  </form>
  <script>
    (function () {
      const chatLog = document.getElementById("chat-log");
      const chatForm = document.getElementById("chat-form");
      const chatInput = document.getElementById("chat-input");
      let chatHistory = [];

      chatForm.addEventListener("submit", async function (event) {
        event.preventDefault();
        const message = chatInput.value;
        chatInput.value = "";
        chatLog.innerHTML += "<p><strong>Du:</strong> " + message + "</p>";

        const response = await fetch("/scans/{{ scan.id }}/chat", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({message: message, history: chatHistory}),
        });
        const data = await response.json();
        chatLog.innerHTML += "<p><strong>Kali:</strong> " + data.reply + "</p>";
        chatHistory.push({role: "user", content: message});
        chatHistory.push({role: "assistant", content: data.reply});
      });
    })();
  </script>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v -k chat_widget`
Expected: PASS

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `pytest -q`
Expected: PASS (all tests except any pre-existing live-API-key-gated skips)

- [ ] **Step 6: Commit**

```bash
git add app/templates/scan_detail.html tests/test_main.py
git commit -m "feat: chat widget on scan detail page"
```

---

## Self-Review Notes

- **Spec coverage:** Decision 1 (scope = single scan, option (c) primary +
  option (a) fallback) → Tasks 1-3; Decision 2 (citation caching, only
  on-demand fresh fetch) → Task 1 (`build_scan_context` surfaces the cached
  `evidence_data.citation`) + Task 2 (`get_norm_citation` tool only fetches
  when the model asks); Decision 3 (mandatory disclaimer in the system
  prompt) → Task 2 (`SYSTEM_PROMPT_TEMPLATE`); Decision 4 (mandatory
  Finding-ID/norm citation in every answer) → Task 2 (same template) +
  Task 3 (the tool loop that supplies Finding-IDs); Decision 5 (no
  persistence) → Task 3/4 (`history` is a caller-supplied parameter, no DB
  writes) + Task 5 (JS `chatHistory` variable, lost on reload); UI
  integration idea (`POST /scans/{scan_id}/chat`, plain JS fetch, no new
  frontend framework) → Task 4 + Task 5.
- **Type consistency checked:** `chat_with_scan`'s `history` parameter is a
  `list[dict]` with `{"role", "content"}` keys in Task 3's tests; Task 4's
  route converts `list[ChatMessage]` (pydantic) to that same shape via
  `.model_dump()` before calling it — matches. `_execute_tool`'s
  `http_client` parameter accepts `None` in every Task 2/3 test
  (`get_finding_detail` never touches it; `chat_with_scan` always
  constructs a real one before the loop runs) — consistent with
  `app.compliance.fetch_citation`'s own `client: httpx.AsyncClient | None = None`
  contract.
- **No new dependencies confirmed:** `requirements.txt` already lists
  `anthropic`, `httpx`, `fastapi`, `python-multipart`, `jinja2` — nothing
  in this plan needs an addition.
- **Known simplification flagged, not hidden:** `MAX_TOOL_ITERATIONS = 5` in
  Task 3 is a hard cap, not true infinite-loop detection — marked with a
  `ponytail:` comment in the code itself, matching the codebase's existing
  convention for this kind of deliberate corner-cut (see
  `app/scan.py`'s `citation_cache` race-condition comment).
