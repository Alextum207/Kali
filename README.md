![Kali](logo.jpg)

# Kali — Dark-Pattern-Monitor

Ein automatisierter Webseiten-/Design-Monitor, der digitale Oberflächen auf
manipulative Gestaltung (Dark Patterns) untersucht — als skalierbares
Marktbeobachtungs-Tool für Verbraucherzentralen und Aufsichtsbehörden, nicht
als reine Browser-Extension. Das System crawlt Zielseiten headless, erkennt
Dark Patterns über Heuristiken, visuelle Analyse und einen Claude-basierten
Textklassifikator, ordnet Funde einschlägigen Rechtsnormen zu (UWG, BGB,
DSA, DSGVO, PAngV) und sichert Screenshot/DOM/HAR gerichtsfest als Beweismittel.

Projekt für den Legal Loves Tech Hackathon 2026, Challenge der Verbraucherzentrale.
Details siehe `CLAUDE.md`.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium   # mandatory — crawling fails with a confusing error without it
```

## `.env`

Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY`. `LEGAL_TEXT_MCP_BASE_URL`
expects a separately running `legal-text-mcp-de` server (see `app/compliance.py`
for the endpoint it calls):

```bash
uvx legal-text-mcp-de http
```

## Run

```bash
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/ and start a scan from the dashboard.

## Frontend (`frontend/`)

Separate React/Vite/shadcn frontend (Lovable-built), runs alongside the
Jinja2 UI and talks to the backend only through the read-only JSON API
(`/api/scans`, CORS-enabled for `http://localhost:8080`):

```bash
cd frontend
npm i
cp .env.example .env   # VITE_API_BASE_URL, defaults to http://localhost:8000
npm run dev
```

Then open http://localhost:8080/ — with the backend (`uvicorn app.main:app
--reload`) running in parallel on :8000.

## PDF reports

PDF generation uses WeasyPrint, which needs GTK libraries (see the WeasyPrint
installation guide). On Windows without GTK the test suite automatically falls
back to a mock (see `tests/conftest.py`) — verify real PDF generation on
Linux/Docker before the demo. If GTK is genuinely unavailable on the demo
machine, `GET /scans/{id}/report.pdf` degrades gracefully to an HTML view of
the same report instead of a server error (`app/main.py::scan_report`).

## Tests

```bash
pytest -q
```

## Demo-Anleitung für die Jury

**Primärer, netzwerkunabhängiger Demo-Pfad** (kein Internet nötig, garantiert
reproduzierbar):

1. `uvicorn app.main:app --reload` starten, Dashboard unter
   http://127.0.0.1:8000/ öffnen.
2. Als Start-URL den `file://`-Pfad zu `tests/fixtures/fake_shop/index.html`
   eingeben (absoluter Pfad auf dem Vorführ-Rechner).
3. Scan starten — die Seite aktualisiert sich automatisch, während der
   Crawler `index.html` → `product.html` → `cart.html` → `checkout.html` →
   `account.html` durchläuft.
4. Ergebnis: garantiert mindestens 4 deterministische Funde (Fake Urgency,
   Trick Questions, Visuelle Tarnung, Fehlende Reject-Option/Cookie-Banner —
   siehe `tests/test_demo_flow.py`), plus bei aktivem `ANTHROPIC_API_KEY`
   zusätzlich Confirm Shaming und Sneaking/Hidden Costs.
5. "PDF-Report herunterladen" klicken — funktioniert mit oder ohne
   funktionierende WeasyPrint/GTK-Installation (siehe oben).

**Zusatz-Demo (optional, braucht Internet):** eine echte externe Website
scannen, um den Site-Crawl mit Kategorie-Priorisierung und den Flow-Walk
(z.B. bis zum Checkout durchklicken) live zu zeigen.

**Extension:** `chrome://extensions` → Entwicklermodus → "Entpackt laden" →
`vendor/pattern-highlighter/chrome/` auswählen. Dann `fake_shop/index.html`
im Browser öffnen (lokale Datei), Popup zeigt Live-Funde inkl. Cookie-Wall-
Umrandung, "PDF-Report erstellen" öffnet die Druckansicht mit
Screenshot-Thumbnails.

## Architektur & Sicherheit

- **Strikte Trennung**: Crawler (`app/crawler.py`, `app/site_crawler.py`),
  Erkennungs-Engine (`app/analysis/`), Datenhaltung (`app/db.py`), Reporting
  (`app/reports.py`) sind unabhängige Module ohne Zirkelabhängigkeiten.
- **SSRF-Schutz** (`app/url_safety.py::validate_scan_url`): blockt private/
  Loopback-/Link-lokale IPs, Cloud-Metadata-Adressen und `file://`
  außerhalb kontrollierter Test-Fixtures, bevor irgendeine URL an Playwright
  geht. Gilt für die Start-URL und jeden vom Crawler entdeckten Link.
- **CAPTCHA-Abbruch** (`CaptchaRequiredError`): ein erkanntes CAPTCHA auf
  der Start-Seite bricht den Scan sauber ab (`status='error'` im UI) statt
  es zu umgehen oder falsche Ergebnisse zu erzeugen.
- **Host-Scope**: der Crawler bleibt auf den Host der Start-URL plus dessen
  Subdomains beschränkt — kein Domain-übergreifendes Following.
- **Kein Backend-Call aus der Chrome-Extension**: alle 10
  Extension-Pattern-Typen laufen rein clientseitig (kein API-Key, keine
  Netzwerkabhängigkeit außer der gescannten Seite selbst) — siehe
  `CLAUDE.md` für die bewusste Entscheidung dahinter.
- **Keine automatische Cookie-Zustimmung**: `apply_consent_rules`
  (Python) und `consent.js` (Extension) erkennen und lesen Consent-Banner
  aus, klicken höchstens einen bereits identifizierten Reject-Button —
  nie "Akzeptieren", nie ungefragt.

## Bekannte Einschränkungen / bewusst verschobene Features

Ein größerer, mehrphasiger Ausbau (einheitliches Detection-Schema über
Python+Extension, robusteres MutationObserver-Handling, iframe-fähige
Reports, produktionsreiferer Crawler mit robots.txt/Rate-Limit/Checkpoints,
eine mehrstufige ML-Erkennungs-Kaskade, Drip-Pricing-Historie über den
Checkout-Flow, CI-Pipeline) ist bewusst auf **nach dem Hackathon**
verschoben, um die Submission nicht zu gefährden. Details zu jedem
nicht-erkennbaren Pattern-Typ und dem geplanten Ausbau: siehe
`TECHNISCHE-UEBERSICHT.md` im Projekt-Root.
