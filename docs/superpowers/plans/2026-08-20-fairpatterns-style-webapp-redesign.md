# FairPatterns-Style Web App Redesign + Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Kali's minimal 4-page web UI and bare-bones PDF report with a
FairPatterns-inspired (concept only, no copied text/branding) scan dashboard,
filterable findings view, and litigation-grade report — while removing the
Chrome extension, which no longer fits the web-app-first product.

**Architecture:** Stays inside the existing FastAPI + Jinja2 + WeasyPrint
stack. A new `app/static/style.css` (hand-written, CSS variables, no
framework) plus a shared `base.html` layout give all pages one visual
system. A new `aggregate_risk_score()` in `app/compliance.py` computes one
risk metric reused by the dashboard, scan detail, and report. Findings
filtering is server-side via query parameters — no JavaScript. The Chrome
extension (`extension/`) and its `cookies` handoff plumbing through
`main.py` → `scan.py` → `site_crawler.py` are deleted.

**Tech Stack:** FastAPI, Jinja2, WeasyPrint (unchanged). No new
dependencies.

**Spec:** `docs/superpowers/specs/2026-08-20-fairpatterns-style-webapp-redesign-design.md`

## Global Constraints

- No 1:1 copy of FairPatterns text, branding, or markup — concept only.
- No new pip dependencies. No CSS/JS framework, no build step.
- No client-side JavaScript for filtering — server-side query params only
  (explicit user instruction: keep code minimal).
- Backend modules outside this plan's file list (`crawler.py`,
  `analysis/*`, `evidence.py`) are NOT to be touched beyond what Task 8
  requires for extension removal.
- Every non-trivial function change ships with its own test in the same
  task (TDD: failing test → minimal implementation → passing test).
- Keep diffs as small as correctness allows — reuse existing helpers
  (`_attach_display_fields`, `NORM_MAP`, `STATUTE_TEXTS`) rather than
  duplicating logic.

---

## Task 1: `list_scans()` in `app/db.py`

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `list_scans(conn: sqlite3.Connection) -> list[dict]` — all
  scans, newest first (`ORDER BY id DESC`), each dict has the same shape
  as `get_scan()`'s return value (`id`, `url`, `started_at`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_list_scans_returns_newest_first():
    from app.db import list_scans

    conn = init_db(":memory:")
    first_id = insert_scan(conn, "https://a.example.com")
    second_id = insert_scan(conn, "https://b.example.com")

    scans = list_scans(conn)

    assert [s["id"] for s in scans] == [second_id, first_id]
    assert scans[0]["url"] == "https://b.example.com"


def test_list_scans_returns_empty_list_when_no_scans():
    from app.db import list_scans

    conn = init_db(":memory:")
    assert list_scans(conn) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -k list_scans -v`
Expected: FAIL with `ImportError: cannot import name 'list_scans'`

- [ ] **Step 3: Write minimal implementation**

Add to `app/db.py`, after `get_scan`:

```python
def list_scans(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM scans ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS (all tests in the file, including the two new ones)

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: add list_scans() for the dashboard scan overview"
```

---

## Task 2: `aggregate_risk_score()` in `app/compliance.py`

**Files:**
- Modify: `app/compliance.py`
- Test: `tests/test_compliance.py`

**Interfaces:**
- Consumes: `findings: list[dict]` with at least `confidence_score: float`
  and `pattern_type: str` keys (same shape `get_findings()` /
  `get_page_findings()` already return).
- Produces: `aggregate_risk_score(findings: list[dict]) -> dict` returning
  `{"score": float, "level": "niedrig"|"mittel"|"hoch", "by_category":
  dict[str, int]}`. Used by Task 4 (dashboard), Task 5 (scan detail), and
  Task 7 (report).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_compliance.py`:

```python
def test_aggregate_risk_score_empty_findings():
    from app.compliance import aggregate_risk_score

    result = aggregate_risk_score([])

    assert result == {"score": 0.0, "level": "niedrig", "by_category": {}}


def test_aggregate_risk_score_low_level():
    from app.compliance import aggregate_risk_score

    result = aggregate_risk_score([
        {"pattern_type": "Pre-ticked Box", "confidence_score": 0.2},
    ])

    assert result["score"] == pytest.approx(0.25)
    assert result["level"] == "niedrig"
    assert result["by_category"] == {"Pre-ticked Box": 1}


def test_aggregate_risk_score_medium_level():
    from app.compliance import aggregate_risk_score

    result = aggregate_risk_score([
        {"pattern_type": "Confirm Shaming", "confidence_score": 0.5},
    ])

    assert result["score"] == pytest.approx(0.55)
    assert result["level"] == "mittel"


def test_aggregate_risk_score_high_level_and_multiple_categories():
    from app.compliance import aggregate_risk_score

    result = aggregate_risk_score([
        {"pattern_type": "Confirm Shaming", "confidence_score": 0.9},
        {"pattern_type": "Confirm Shaming", "confidence_score": 0.9},
        {"pattern_type": "Fake Urgency", "confidence_score": 0.9},
    ])

    assert result["level"] == "hoch"
    assert result["score"] <= 1.0
    assert result["by_category"] == {"Confirm Shaming": 2, "Fake Urgency": 1}
```

`tests/test_compliance.py` already imports `pytest` (see the top of the
file) — no new import line needed for `pytest.approx`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_compliance.py -k aggregate_risk_score -v`
Expected: FAIL with `ImportError: cannot import name 'aggregate_risk_score'`

- [ ] **Step 3: Write minimal implementation**

Add to `app/compliance.py`, after `map_to_norm` (needs `from collections
import Counter` added to the existing import block at the top of the
file):

```python
def aggregate_risk_score(findings: list[dict]) -> dict:
    """Simple, explainable risk metric — mean confidence across findings,
    nudged up by finding volume. Not empirically calibrated; the level
    cutoffs (0.34 / 0.67) are a deliberate simplification for the demo.
    ponytail: revisit cutoffs/weighting if real scans show a level that
    reads as clearly wrong to a reviewer."""
    if not findings:
        return {"score": 0.0, "level": "niedrig", "by_category": {}}

    mean_confidence = sum(f["confidence_score"] for f in findings) / len(findings)
    volume_factor = min(len(findings) / 20, 0.15)
    score = min(mean_confidence + volume_factor, 1.0)

    if score < 0.34:
        level = "niedrig"
    elif score < 0.67:
        level = "mittel"
    else:
        level = "hoch"

    by_category = dict(Counter(f["pattern_type"] for f in findings))
    return {"score": score, "level": level, "by_category": by_category}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_compliance.py -v`
Expected: PASS (all tests, including the four new ones)

- [ ] **Step 5: Commit**

```bash
git add app/compliance.py tests/test_compliance.py
git commit -m "feat: add aggregate_risk_score() for dashboard/report risk metric"
```

---

## Task 3: Design system — `static/style.css` + `base.html`

**Files:**
- Create: `app/static/style.css`
- Create: `app/templates/base.html`
- Modify: `app/main.py` (mount `/static`)
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `/static/style.css` served as `text/css`. `base.html` Jinja
  template with `{% block title %}` and `{% block content %}` blocks, a
  nav bar (`Kali` brand link to `/`, `Dashboard` link to `/`), and a
  `<link rel="stylesheet" href="/static/style.css">`. Tasks 4–6 extend
  this template with `{% extends "base.html" %}`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main.py`:

```python
def test_static_stylesheet_is_served():
    with TestClient(main_module.app) as client:
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -k static_stylesheet -v`
Expected: FAIL with 404 (no `/static` mount yet, no file yet)

- [ ] **Step 3: Write minimal implementation**

Create `app/static/style.css`:

```css
:root {
  --color-bg: #ffffff;
  --color-text: #111111;
  --color-border: #dddddd;
  --color-muted: #666666;
  --color-risk-low: #1a7f37;
  --color-risk-medium: #b35c00;
  --color-risk-high: #c9302c;
  --font-size-sm: 0.85rem;
  --font-size-base: 1rem;
  --font-size-lg: 1.25rem;
  --font-size-xl: 1.75rem;
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 1rem;
  --space-4: 1.5rem;
  --space-5: 2rem;
  --space-6: 3rem;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: -apple-system, "Segoe UI", sans-serif;
  color: var(--color-text);
  background: var(--color-bg);
  font-size: var(--font-size-base);
}

.nav {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.nav-brand { font-weight: 700; font-size: var(--font-size-lg); text-decoration: none; color: var(--color-text); }
.nav a { text-decoration: none; color: var(--color-text); }
.container { max-width: 960px; margin: 0 auto; padding: var(--space-5); }
h1 { font-size: var(--font-size-xl); margin-bottom: var(--space-4); }

table { width: 100%; border-collapse: collapse; margin-bottom: var(--space-4); }
th, td { border-bottom: 1px solid var(--color-border); padding: var(--space-2) var(--space-3); text-align: left; font-size: var(--font-size-sm); }
th { color: var(--color-muted); font-weight: 600; text-transform: uppercase; font-size: 0.75rem; }

.badge { display: inline-block; padding: var(--space-1) var(--space-2); border-radius: 4px; font-size: var(--font-size-sm); font-weight: 600; color: #fff; }
.badge-niedrig { background: var(--color-risk-low); }
.badge-mittel { background: var(--color-risk-medium); }
.badge-hoch { background: var(--color-risk-high); }

.card { border: 1px solid var(--color-border); border-radius: 8px; padding: var(--space-4); margin-bottom: var(--space-4); }

.filters { display: flex; gap: var(--space-3); margin-bottom: var(--space-4); align-items: flex-end; flex-wrap: wrap; }
.filters label { display: flex; flex-direction: column; font-size: var(--font-size-sm); gap: var(--space-1); }

.scan-form { display: flex; gap: var(--space-3); margin-bottom: var(--space-5); flex-wrap: wrap; }

button, input, select {
  font-family: inherit;
  font-size: var(--font-size-base);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: 4px;
}

button {
  cursor: pointer;
  background: var(--color-text);
  color: #fff;
  border-color: var(--color-text);
}
```

Create `app/templates/base.html`:

```html
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>{% block title %}Kali{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <nav class="nav">
    <a href="/" class="nav-brand">Kali</a>
    <a href="/">Dashboard</a>
  </nav>
  <main class="container">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

In `app/main.py`, add the import next to the other `fastapi` imports:

```python
from fastapi.staticfiles import StaticFiles
```

And mount it right after `templates = Jinja2Templates(...)` (`app/main.py:55`):

```python
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
    name="static",
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 5: Commit**

```bash
git add app/static/style.css app/templates/base.html app/main.py tests/test_main.py
git commit -m "feat: add shared design system (style.css + base.html layout)"
```

---

## Task 4: Dashboard = scan overview

**Files:**
- Modify: `app/templates/dashboard.html`
- Modify: `app/main.py:86-88` (`dashboard` route)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `list_scans(conn)` (Task 1), `get_findings(conn, scan_id)`
  (existing), `aggregate_risk_score(findings)` (Task 2), `base.html`
  (Task 3).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main.py`:

```python
def test_dashboard_lists_scans_with_risk_badge(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))

    from app.db import init_db, insert_scan, insert_finding

    conn = init_db(str(tmp_path / "test.db"))
    scan_id = insert_scan(conn, "https://example.com")
    insert_finding(conn, scan_id, {
        "pattern_type": "Confirm Shaming",
        "target_norm": "Art. 25 DSA",
        "confidence_score": 0.9,
        "evidence_data": {},
    })
    conn.close()

    with TestClient(main_module.app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "example.com" in response.text
    assert "badge-hoch" in response.text


def test_dashboard_shows_empty_state_without_scans(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    with TestClient(main_module.app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Noch keine Scans" in response.text
```

`test_dashboard_renders` (existing, `tests/test_main.py:92`) already
asserts `"Scan starten" in response.text` — the new template keeps that
button, so it must keep passing unmodified.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -k dashboard -v`
Expected: FAIL — `test_dashboard_lists_scans_with_risk_badge` and
`test_dashboard_shows_empty_state_without_scans` fail because the current
template never renders scan rows or an empty-state message.

- [ ] **Step 3: Write minimal implementation**

In `app/main.py`, change the import line at `app/main.py:21` from:

```python
from app.db import init_db, get_scan, get_findings, get_pages, get_page_findings
```

to:

```python
from app.compliance import aggregate_risk_score
from app.db import init_db, get_scan, get_findings, get_pages, get_page_findings, list_scans
```

Replace the `dashboard` route (`app/main.py:86-88`):

```python
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, conn: sqlite3.Connection = Depends(_get_conn)):
    scans = list_scans(conn)
    for scan in scans:
        scan["risk"] = aggregate_risk_score(get_findings(conn, scan["id"]))
    return templates.TemplateResponse(request, "dashboard.html", {"scans": scans})
```

Replace `app/templates/dashboard.html`:

```html
{% extends "base.html" %}
{% block title %}Dashboard – Kali{% endblock %}
{% block content %}
<h1>Scans</h1>

<form class="scan-form" method="post" action="/scans">
  <input type="url" name="url" placeholder="https://..." required>
  <input type="number" name="max_pages" value="5" min="1" title="Max. Seiten">
  <button type="submit">Scan starten</button>
</form>

{% if scans %}
<table>
  <tr><th>URL</th><th>Gestartet</th><th>Risiko</th></tr>
  {% for s in scans %}
  <tr>
    <td><a href="/scans/{{ s.id }}">{{ s.url }}</a></td>
    <td>{{ s.started_at }}</td>
    <td><span class="badge badge-{{ s.risk.level }}">{{ s.risk.level }} ({{ "%.2f"|format(s.risk.score) }})</span></td>
  </tr>
  {% endfor %}
</table>
{% else %}
<p>Noch keine Scans.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/templates/dashboard.html tests/test_main.py
git commit -m "feat: dashboard becomes a scan overview with risk badges"
```

---

## Task 5: Scan detail — risk header + server-side filters

**Files:**
- Modify: `app/templates/scan_detail.html`
- Modify: `app/main.py:171-180` (`scan_detail` route)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `aggregate_risk_score` (Task 2), `_attach_display_fields`
  (existing, `app/main.py:73-83`).
- Query params: `pattern_type: str | None`, `target_norm: str | None`,
  `min_confidence: float | None` — all optional, all AND-combined.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main.py`:

```python
def test_scan_detail_shows_risk_badge(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    from app.db import init_db, insert_scan, insert_finding

    conn = init_db(str(tmp_path / "test.db"))
    scan_id = insert_scan(conn, "https://example.com")
    insert_finding(conn, scan_id, {
        "pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA",
        "confidence_score": 0.9, "evidence_data": {},
    })
    conn.close()

    with TestClient(main_module.app) as client:
        response = client.get(f"/scans/{scan_id}")

    assert response.status_code == 200
    assert "badge-hoch" in response.text


def test_scan_detail_filters_by_pattern_type(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    from app.db import init_db, insert_scan, insert_finding

    conn = init_db(str(tmp_path / "test.db"))
    scan_id = insert_scan(conn, "https://example.com")
    insert_finding(conn, scan_id, {
        "pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA",
        "confidence_score": 0.9, "evidence_data": {},
    })
    insert_finding(conn, scan_id, {
        "pattern_type": "Fake Urgency", "target_norm": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
        "confidence_score": 0.6, "evidence_data": {},
    })
    conn.close()

    with TestClient(main_module.app) as client:
        response = client.get(f"/scans/{scan_id}", params={"pattern_type": "Fake Urgency"})

    assert response.status_code == 200
    assert "Fake Urgency" in response.text
    assert "Confirm Shaming" not in response.text


def test_scan_detail_filters_by_min_confidence(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main_module, "EVIDENCE_DIR", str(tmp_path / "evidence"))

    from app.db import init_db, insert_scan, insert_finding

    conn = init_db(str(tmp_path / "test.db"))
    scan_id = insert_scan(conn, "https://example.com")
    insert_finding(conn, scan_id, {
        "pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA",
        "confidence_score": 0.9, "evidence_data": {},
    })
    insert_finding(conn, scan_id, {
        "pattern_type": "Fake Urgency", "target_norm": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
        "confidence_score": 0.3, "evidence_data": {},
    })
    conn.close()

    with TestClient(main_module.app) as client:
        response = client.get(f"/scans/{scan_id}", params={"min_confidence": "0.5"})

    assert "Confirm Shaming" in response.text
    assert "Fake Urgency" not in response.text
```

`test_scan_detail_lists_pages` (existing, `tests/test_main.py:224`) and
`test_scan_detail_404_for_missing_scan` (`tests/test_main.py:99`) must
keep passing unmodified — the pages table and 404 behavior are unchanged.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -k scan_detail -v`
Expected: FAIL — the three new tests fail (no risk badge rendered, no
filtering applied yet).

- [ ] **Step 3: Write minimal implementation**

Replace the `scan_detail` route (`app/main.py:171-180`):

```python
@app.get("/scans/{scan_id}", response_class=HTMLResponse)
def scan_detail(
    request: Request,
    scan_id: int,
    pattern_type: str | None = None,
    target_norm: str | None = None,
    min_confidence: float | None = None,
    conn: sqlite3.Connection = Depends(_get_conn),
):
    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    pages = get_pages(conn, scan_id)
    findings = _attach_display_fields(get_findings(conn, scan_id), pages, scan["url"])
    risk = aggregate_risk_score(findings)

    filtered = findings
    if pattern_type:
        filtered = [f for f in filtered if f["pattern_type"] == pattern_type]
    if target_norm:
        filtered = [f for f in filtered if f["target_norm"] == target_norm]
    if min_confidence is not None:
        filtered = [f for f in filtered if f["confidence_score"] >= min_confidence]

    return templates.TemplateResponse(
        request, "scan_detail.html",
        {
            "scan": scan,
            "pages": pages,
            "findings": filtered,
            "risk": risk,
            "pattern_types": sorted({f["pattern_type"] for f in findings}),
            "target_norms": sorted({f["target_norm"] for f in findings}),
            "selected_pattern_type": pattern_type or "",
            "selected_target_norm": target_norm or "",
            "selected_min_confidence": min_confidence,
        },
    )
```

Replace `app/templates/scan_detail.html`:

```html
{% extends "base.html" %}
{% block title %}Scan {{ scan.id }} – Kali{% endblock %}
{% block content %}
<h1>Scan: {{ scan.url }}</h1>
<a href="/scans/{{ scan.id }}/report.pdf">PDF-Report herunterladen</a>

<div class="card">
  <span class="badge badge-{{ risk.level }}">{{ risk.level }} ({{ "%.2f"|format(risk.score) }})</span>
  {% for category, count in risk.by_category.items() %}
  <span>{{ category }}: {{ count }}</span>
  {% endfor %}
</div>

<h2>Gecrawlte Seiten</h2>
<table>
  <tr><th>URL</th><th>Kategorie</th></tr>
  {% for p in pages %}
  <tr><td><a href="/scans/{{ scan.id }}/pages/{{ p.id }}">{{ p.url }}</a></td><td>{{ p.category }}</td></tr>
  {% endfor %}
</table>

<h2>Findings</h2>
<form class="filters" method="get">
  <label>Pattern-Typ
    <select name="pattern_type">
      <option value="">Alle</option>
      {% for pt in pattern_types %}
      <option value="{{ pt }}" {% if pt == selected_pattern_type %}selected{% endif %}>{{ pt }}</option>
      {% endfor %}
    </select>
  </label>
  <label>Norm
    <select name="target_norm">
      <option value="">Alle</option>
      {% for norm in target_norms %}
      <option value="{{ norm }}" {% if norm == selected_target_norm %}selected{% endif %}>{{ norm }}</option>
      {% endfor %}
    </select>
  </label>
  <label>Min. Confidence
    <input type="number" name="min_confidence" step="0.1" min="0" max="1" value="{{ selected_min_confidence or '' }}">
  </label>
  <button type="submit">Filtern</button>
</form>

<table>
  <tr><th>Pattern-Typ</th><th>Norm</th><th>Confidence</th><th>Auswirkung</th><th>Link</th><th>Zeit</th><th>Screenshot</th></tr>
  {% for f in findings %}
  <tr>
    <td>{{ f.pattern_type }}</td>
    <td>{{ f.target_norm }}</td>
    <td>{{ f.confidence_score }}</td>
    <td>{{ f.evidence_data.get("impact") or "–" }}</td>
    <td>{% if f.page_url %}<a href="{{ f.page_url }}" target="_blank">{{ f.page_url }}</a>{% else %}–{% endif %}</td>
    <td>{{ f.created_at }}</td>
    <td>{% if f.screenshot_url %}<a href="{{ f.screenshot_url }}" target="_blank">ansehen</a>{% else %}–{% endif %}</td>
  </tr>
  {% endfor %}
</table>
{% endblock %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/templates/scan_detail.html tests/test_main.py
git commit -m "feat: scan detail gets risk header and server-side findings filters"
```

---

## Task 6: Page detail — apply shared layout

**Files:**
- Modify: `app/templates/page_detail.html`
- Test: `tests/test_main.py` (no new test — existing coverage suffices)

**Interfaces:** None new — same context dict as today
(`scan`, `page_id`, `findings`), just wrapped in `base.html`.

- [ ] **Step 1: Confirm existing coverage is sufficient**

`test_page_detail_shows_findings_for_one_page`
(`tests/test_main.py:200-221`) already asserts `"Trick Questions" in
response.text` — that's enough to catch a broken template. No new test
needed for a pure layout change (YAGNI — the content and route are
untouched).

- [ ] **Step 2: Run it first to confirm it currently passes**

Run: `pytest tests/test_main.py -k page_detail -v`
Expected: PASS (baseline, before the template edit)

- [ ] **Step 3: Rewrite the template**

Replace `app/templates/page_detail.html`:

```html
{% extends "base.html" %}
{% block title %}Seite {{ page_id }} – Scan {{ scan.id }} – Kali{% endblock %}
{% block content %}
<h1>Seite: {{ scan.url }}</h1>
<a href="/scans/{{ scan.id }}">Zurück zur Scan-Übersicht</a>

<table>
  <tr><th>Pattern-Typ</th><th>Norm</th><th>Confidence</th><th>Auswirkung</th><th>Link</th><th>Zeit</th><th>Screenshot</th></tr>
  {% for f in findings %}
  <tr>
    <td>{{ f.pattern_type }}</td>
    <td>{{ f.target_norm }}</td>
    <td>{{ f.confidence_score }}</td>
    <td>{{ f.evidence_data.get("impact") or "–" }}</td>
    <td>{% if f.page_url %}<a href="{{ f.page_url }}" target="_blank">{{ f.page_url }}</a>{% else %}–{% endif %}</td>
    <td>{{ f.created_at }}</td>
    <td>{% if f.screenshot_url %}<a href="{{ f.screenshot_url }}" target="_blank">ansehen</a>{% else %}–{% endif %}</td>
  </tr>
  {% endfor %}
</table>
{% endblock %}
```

- [ ] **Step 4: Run test to verify it still passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS (all tests in the file — this confirms the layout change
didn't break the existing route)

- [ ] **Step 5: Commit**

```bash
git add app/templates/page_detail.html
git commit -m "style: apply shared layout to page detail view"
```

---

## Task 7: Report redesign — cover page + norm summary

**Files:**
- Modify: `app/templates/report.html`
- Modify: `app/reports.py`
- Test: `tests/test_reports.py`

**Interfaces:**
- Consumes: `aggregate_risk_score` (Task 2).
- `generate_pdf_report(url, findings, out_path) -> str` signature is
  UNCHANGED — it now computes `risk` and `by_norm` internally and passes
  them into the template context as `risk` and `by_norm`. Existing direct
  `template.render(url=..., findings=...)` calls in `tests/test_reports.py`
  (no `risk`/`by_norm` kwargs) must keep working — both new template
  sections are guarded by `{% if risk %}` / `{% if by_norm %}`, so Jinja's
  `Undefined` (falsy) skips them cleanly.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_reports.py`:

```python
def test_generate_pdf_report_computes_risk_and_norm_summary(tmp_path, monkeypatch):
    """generate_pdf_report must pass risk + by_norm into the template
    context — verified by capturing the render() call args instead of
    parsing the binary PDF."""
    captured = {}

    class _CapturingTemplate:
        def render(self, **kwargs):
            captured.update(kwargs)
            return "<html></html>"

    import app.reports as reports_module
    monkeypatch.setattr(reports_module._env, "get_template", lambda name: _CapturingTemplate())

    findings = [
        {"pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA", "confidence_score": 0.9,
         "evidence_data": {}},
        {"pattern_type": "Fake Urgency", "target_norm": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
         "confidence_score": 0.9, "evidence_data": {}},
    ]
    out_path = str(tmp_path / "report.pdf")
    reports_module.generate_pdf_report("https://example.com", findings, out_path)

    assert captured["risk"]["level"] == "hoch"
    assert captured["by_norm"] == {"Art. 25 DSA": 1, "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3": 1}


def test_report_template_renders_cover_and_norm_summary_when_risk_given():
    from jinja2 import Environment, FileSystemLoader

    templates_dir = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("report.html")

    findings = [
        {"pattern_type": "Confirm Shaming", "target_norm": "Art. 25 DSA", "confidence_score": 0.9,
         "evidence_data": {}},
    ]
    html = template.render(
        url="https://example.com",
        findings=findings,
        risk={"score": 0.9, "level": "hoch", "by_category": {"Confirm Shaming": 1}},
        by_norm={"Art. 25 DSA": 1},
    )

    assert "badge-hoch" in html
    assert "Art. 25 DSA" in html


def test_report_template_renders_without_risk_context():
    """Direct template.render() calls without risk/by_norm (as used
    elsewhere in this file) must not crash and must not render a cover
    section."""
    from jinja2 import Environment, FileSystemLoader

    templates_dir = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("report.html")

    html = template.render(url="https://example.com", findings=[])

    assert "badge-" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reports.py -v`
Expected: FAIL — the two new tests assert content (`captured["risk"]`,
`"badge-hoch"`) that doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

Replace `app/reports.py`:

```python
import os
from collections import Counter

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.compliance import aggregate_risk_score

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR))


def generate_pdf_report(url: str, findings: list[dict], out_path: str) -> str:
    """Generate a PDF report from findings.

    Args:
        url: The website URL that was scanned.
        findings: List of finding dicts with pattern_type, target_norm, confidence_score, evidence_data.
        out_path: Path to write the PDF file to.

    Returns:
        The out_path (for convenience).
    """
    template = _env.get_template("report.html")
    risk = aggregate_risk_score(findings)
    by_norm = dict(Counter(f["target_norm"] for f in findings))
    html_content = template.render(url=url, findings=findings, risk=risk, by_norm=by_norm)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    HTML(string=html_content).write_pdf(out_path)
    return out_path
```

Replace `app/templates/report.html` (the `<body>` content — the existing
findings table markup at the bottom is UNCHANGED, so every pre-existing
citation/impact/link/screenshot assertion in `tests/test_reports.py`
keeps passing):

```html
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { font-family: -apple-system, "Segoe UI", sans-serif; margin: 20px; color: #111; }
  .cover { text-align: center; padding: 60px 0; page-break-after: always; }
  .cover h1 { font-size: 22px; margin-bottom: 8px; }
  .cover .score { font-size: 40px; font-weight: 700; margin: 20px 0; }
  .badge-niedrig { color: #1a7f37; }
  .badge-mittel { color: #b35c00; }
  .badge-hoch { color: #c9302c; }
  h1 { font-size: 18px; margin-bottom: 20px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
  th, td { border: 1px solid #999; padding: 8px; text-align: left; font-size: 12px; }
  th { background-color: #f0f0f0; font-weight: bold; }
  .citation { display: block; margin-top: 4px; padding-top: 4px; border-top: 1px solid #ddd; font-size: 11px; color: #666; font-style: italic; }
  .evidence { word-break: break-word; }
</style>
</head>
<body>
  {% if risk %}
  <div class="cover">
    <h1>Dark-Pattern-Prüfbericht</h1>
    <p>{{ url }}</p>
    <div class="score badge-{{ risk.level }}">{{ "%.2f"|format(risk.score) }} — {{ risk.level }}</div>
    <p>{{ findings|length }} Funde</p>
  </div>
  {% endif %}

  {% if by_norm %}
  <h1>Zusammenfassung nach Rechtsnorm</h1>
  <table>
    <tr><th>Rechtsnorm</th><th>Anzahl Funde</th></tr>
    {% for norm, count in by_norm.items() %}
    <tr><td>{{ norm }}</td><td>{{ count }}</td></tr>
    {% endfor %}
  </table>
  {% endif %}

  <h1>Dark-Pattern-Prüfbericht: {{ url }}</h1>
  <table>
    <tr>
      <th>Pattern-Typ</th>
      <th>Rechtsnorm</th>
      <th>Confidence</th>
      <th>Auswirkung</th>
      <th>Link</th>
      <th>Zeit</th>
      <th>Screenshot</th>
      <th>Beleg</th>
    </tr>
    {% for f in findings %}
    <tr>
      <td>{{ f.pattern_type }}</td>
      <td>{{ f.target_norm }}</td>
      <td>{{ "%.2f"|format(f.confidence_score) }}</td>
      <td>{{ f.evidence_data.get("impact") or "–" }}</td>
      <td>{{ f.page_url or "–" }}</td>
      <td>{{ f.created_at }}</td>
      <td>{{ f.screenshot_url or "–" }}</td>
      <td>
        <div class="evidence">
          {{ f.evidence_data.get("quote") or f.evidence_data.get("selector") or "" }}
          {% if f.evidence_data.get("citation") %}
          <span class="citation">{{ f.evidence_data.get("citation") }}</span>
          {% endif %}
        </div>
      </td>
    </tr>
    {% endfor %}
  </table>
</body>
</html>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reports.py -v`
Expected: PASS (all tests in the file, old and new)

- [ ] **Step 5: Commit**

```bash
git add app/reports.py app/templates/report.html tests/test_reports.py
git commit -m "feat: litigation-grade report cover page + norm summary"
```

---

## Task 8: Remove the Chrome extension

**Files:**
- Delete: `extension/` (entire directory — `background.js`, `popup.js`,
  `popup.html`, `manifest.json`, `README.md`, `icons/`, `knopfdruck.webm`)
- Modify: `app/main.py` (remove `/scans/extension` route + `ExtensionScanRequest`)
- Modify: `app/scan.py` (remove `cookies` param from `run_site_scan`)
- Modify: `app/site_crawler.py` (remove `cookies` param from `crawl_site`,
  remove `_chrome_cookies_to_playwright`, remove `_SAME_SITE_MAP`)
- Modify: `tests/test_main.py` (remove the 3 extension-route tests)
- Modify: `tests/test_site_crawler.py` (remove cookie-handoff tests)
- Test: full suite (this task is subtractive — no new test, existing
  tests must still pass after removal)

**Interfaces:** `run_site_scan(start_url, conn, evidence_dir, browser,
max_pages=None, llm_client=None, url_validator=None) -> int` — same as
today minus the `cookies` parameter. `crawl_site(start_url, browser,
max_pages, har_dir, consent_rules_dir=..., llm_client=None,
url_validator=validate_scan_url, time_budget_seconds=None) -> dict` —
same as today minus `cookies`.

- [ ] **Step 1: Delete the extension directory**

```bash
git rm -r extension/
```

- [ ] **Step 2: Remove the extension route from `app/main.py`**

Delete the `ExtensionScanRequest` class and `start_scan_from_extension`
route (`app/main.py:131-168`, the block between `class
ExtensionScanRequest(BaseModel):` and the blank line before `@app.get("/scans/{scan_id}")`).

Remove the now-unused `BaseModel` and `JSONResponse` imports if nothing
else in `app/main.py` uses them — check first:

```bash
grep -n "BaseModel\|JSONResponse" app/main.py
```

If those greps only show the import line itself after the route is
deleted, remove `from pydantic import BaseModel` and `JSONResponse` from
the `fastapi.responses` import line (`app/main.py:15`).

- [ ] **Step 3: Remove the extension tests from `tests/test_main.py`**

Delete `test_start_scan_from_extension_forwards_cookies_and_returns_scan_id`,
`test_start_scan_from_extension_rejects_unsafe_url`, and
`test_start_scan_from_extension_returns_409_when_captcha_required`
(`tests/test_main.py:120-179`).

- [ ] **Step 4: Remove `cookies` from `run_site_scan` in `app/scan.py`**

In `app/scan.py`, change the `run_site_scan` signature (currently
`app/scan.py:127-136`) to drop the `cookies` parameter:

```python
async def run_site_scan(
    start_url: str,
    conn,
    evidence_dir: str,
    browser,
    max_pages: int | None = None,
    llm_client=None,
    url_validator=None,
) -> int:
```

Update the docstring comment above `crawl_kwargs` (`app/scan.py:142-146`)
to drop the cookies mention, and remove the `if cookies is not None:
crawl_kwargs["cookies"] = cookies` block:

```python
    # url_validator is only forwarded when the caller overrides it (tests
    # exercising file:// fixtures, same pattern as crawl_site's own default
    # param) — production always relies on crawl_site's own default
    # (validate_scan_url).
    crawl_kwargs = {"max_pages": max_pages, "har_dir": evidence_dir, "llm_client": llm_client}
    if url_validator is not None:
        crawl_kwargs["url_validator"] = url_validator
```

- [ ] **Step 5: Remove `cookies` from `crawl_site` in `app/site_crawler.py`**

Delete the `_SAME_SITE_MAP` dict and `_chrome_cookies_to_playwright`
function entirely (`app/site_crawler.py:79-104` — from `_SAME_SITE_MAP =
{` through the end of `_chrome_cookies_to_playwright`'s closing `return
converted`).

In `crawl_site`'s signature (`app/site_crawler.py:292-302`), remove the
`cookies: list[dict] | None = None,` parameter. In its docstring, remove
the final paragraph starting with `cookies, if given, are in
chrome.cookies.getAll() shape...`. Remove the injection block:

```python
    if cookies:
        await context.add_cookies(_chrome_cookies_to_playwright(cookies))
```

(the lines directly below `context = await browser.new_context(record_har_path=har_path)`).

- [ ] **Step 6: Remove cookie-handoff tests from `tests/test_site_crawler.py`**

Delete `test_chrome_cookies_to_playwright_maps_fields`,
`test_chrome_cookies_to_playwright_maps_unspecified_samesite_to_lax`, and
`test_crawl_site_injects_cookies_before_crawling`. Update the import line
`from app.site_crawler import crawl_site, _chrome_cookies_to_playwright`
to just `from app.site_crawler import crawl_site`.

- [ ] **Step 7: Run the full test suite**

Run: `pytest -q`
Expected: PASS — no test references the extension, `cookies`, or
`_chrome_cookies_to_playwright` anymore. (Playwright-dependent tests in
`test_site_crawler.py`/`test_site_scan_integration.py` need `playwright
install chromium` to have been run per `README.md`; that's a pre-existing
environment requirement, not something this task changes.)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: remove Chrome extension — web-app-first product, per CLAUDE.md"
```

---

## Task 9: Backend audit — confirm no leftover dead code

**Files:**
- Test: full suite (verification-only task, changes only if the audit
  finds something)

This task is intentionally small: Task 8's removal is the only backend
change in this plan, and a prior review of `app/*.py` (line counts,
function inventories for `crawler.py`/`site_crawler.py`) found the
backend already lean with clearly separated responsibilities — no
speculative rewrite is justified. This task verifies that claim still
holds after Task 8's removal, rather than assuming it.

- [ ] **Step 1: Search for any remaining reference to removed symbols**

```bash
grep -rn "cookies\|_chrome_cookies_to_playwright\|ExtensionScanRequest\|scans/extension" app/ tests/ --include=*.py
```

Expected: no matches. If any turn up, remove them (they're leftover
dead code from Task 8, not new work).

- [ ] **Step 2: Confirm `app/llm_utils.py` earns its place as a module**

```bash
grep -rn "from app.llm_utils import\|import app.llm_utils" app/
```

Expected: two call sites — `app/site_crawler.py` and
`app/analysis/llm_classify.py`. `extract_text()` is genuinely shared
between two independent modules (crawl-time interaction parsing and
text-classification response parsing) — inlining it into either would
duplicate the `ThinkingBlock`-safety logic in the other. **Verdict: keep
`app/llm_utils.py` as-is, no change.**

- [ ] **Step 3: Run the full suite one last time**

Run: `pytest -q`
Expected: PASS, same pass count as the end of Task 8 (this task makes no
code changes unless Step 1 found something).

- [ ] **Step 4: Commit only if Step 1 found and fixed something**

```bash
git add -A
git commit -m "chore: remove leftover extension references found in backend audit"
```

If Step 1 found nothing, skip this commit — there's nothing to commit.

---

## Self-Review Notes

- **Spec coverage:** IA (dashboard/scan-detail/page-detail/report) →
  Tasks 4–7. Risk score → Task 2. Design system → Task 3. Report redesign
  → Task 7. Extension removal → Task 8. Backend audit → Task 9. Every
  spec section maps to a task.
- **Filter mechanism deviation from the original spec draft:** the spec
  was updated in the same brainstorming session (before this plan was
  written) to server-side query-param filters instead of vanilla JS, per
  the user's explicit "as little code as possible" instruction — Task 5
  already reflects the updated spec, not the superseded JS version.
- **Type/signature consistency checked:** `aggregate_risk_score` return
  shape (`score`/`level`/`by_category`) is identical across Tasks 2, 4,
  5, 7. `run_site_scan`/`crawl_site` signatures in Task 8 match their
  actual current signatures (verified against `app/scan.py` and
  `app/site_crawler.py` before writing the task).
- **No placeholders:** every step has literal code, not a description of
  code to write.
