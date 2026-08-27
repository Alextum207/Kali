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

Create a `.env` file in the project root with the following content:

```
ANTHROPIC_API_KEY=
LEGAL_TEXT_MCP_BASE_URL=http://localhost:8091
DB_PATH=./data/monitor.db
EVIDENCE_DIR=./data/evidence
```

Fill in `ANTHROPIC_API_KEY` with your actual Anthropic API key. `LEGAL_TEXT_MCP_BASE_URL`
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

Es gibt zwei Wege, Kali auszuprobieren: **lokal** (empfohlen) und **online**
über die deployte Version auf Render. Beide zeigen dieselbe Anwendung —
lokal ist zuverlässiger und wird deshalb hier zuerst beschrieben.

### Weg A: Lokal (empfohlen)

**Warum lokal statt online?** Bei einem Testlauf während der Entwicklung
lieferte derselbe Scan derselben echten Website online (Render) und lokal
unterschiedliche Ergebnisse — die Ursache dafür ist nicht abschließend
geklärt. Der lokale Pfad ist der einzige, dessen Verhalten vollständig
nachvollzogen und verifiziert wurde. Zusätzlich kann eine kostenlose
Render-Instanz nach Inaktivität eine Weile zum Aufwachen brauchen
("Cold Start") und läuft möglicherweise nicht auf dem allerneuesten
Code-Stand, falls kurz vor der Vorführung noch etwas geändert wurde.

**Voraussetzungen:** Python 3.11+, Node.js 18+, ein Terminal (auf Windows:
"PowerShell" oder "Eingabeaufforderung", auf Mac: "Terminal"-App).

**Schritt für Schritt:**

1. Terminal öffnen, in den Projektordner wechseln (der Ordner, der diese
   README.md enthält):
   ```bash
   cd Kali
   ```
2. Backend-Abhängigkeiten installieren (einmalig, kann ein paar Minuten
   dauern):
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```
3. `.env`-Datei anlegen: eine Textdatei namens `.env` im Projektordner erstellen
   und folgende Zeilen hinzufügen:
   ```
   ANTHROPIC_API_KEY=
   LEGAL_TEXT_MCP_BASE_URL=http://localhost:8091
   DB_PATH=./data/monitor.db
   EVIDENCE_DIR=./data/evidence
   ```
   Dabei `ANTHROPIC_API_KEY=` mit einem echten Anthropic-API-Key ergänzen (ohne
   diesen Key laufen die KI-gestützten Erkennungen nicht, der Rest der Anwendung
   funktioniert trotzdem).
4. Backend starten:
   ```bash
   uvicorn app.main:app --reload
   ```
   Terminal-Fenster offen lassen, solange die Anwendung läuft.
5. Browser öffnen, zu `http://127.0.0.1:8000/` navigieren. Das ist das
   Kali-Dashboard.
6. Eine echte, öffentlich erreichbare Website-Adresse eingeben (z.B. eine
   echte Online-Shop-URL mit `https://` davor — **keine** `file://`-Pfade
   und **keine** `localhost`/`127.0.0.1`-Adressen, die blockt Kali aus
   Sicherheitsgründen bewusst) und den Scan starten.
7. Die Seite aktualisiert sich automatisch, während Kali die Website
   durchsucht. Nach Abschluss erscheinen die gefundenen Dark Patterns mit
   Rechtsnorm-Zuordnung.
8. "PDF-Report herunterladen" klicken, um den gerichtsfesten Bericht zu
   erzeugen (funktioniert auch ohne WeasyPrint/GTK-Installation — die
   Anwendung zeigt dann automatisch eine HTML-Ansicht desselben Berichts
   statt eines Fehlers).

**Browser-Erweiterung (optional, zusätzlich zum Backend):**
`chrome://extensions` in Chrome öffnen → oben rechts "Entwicklermodus"
aktivieren → "Entpackte Erweiterung laden" klicken → den Ordner
`vendor/pattern-highlighter/chrome/` auswählen. Danach zeigt das
Erweiterungs-Icon auf jeder besuchten Website live erkannte Dark Patterns
an, unabhängig vom Backend.

### Weg B: Online (Render)

**Backend/Dashboard:** https://kali-dark-pattern-monitor.onrender.com/ —
funktioniert genauso wie Weg A, Schritte 5–8, nur ohne eigene Installation.
Ein "Cold Start" von bis zu ~30 Sekunden beim ersten Aufruf nach längerer
Inaktivität ist normal (kostenlose Render-Instanz).

**Frontend:** https://kali-frontend.onrender.com/ — Stand jetzt liefert
diese URL einen 503-Fehler (kein Cold-Start-Zwischenstand, mehrfach
geprüft). Vor der Vorführung im Render-Dashboard die Build-Logs des
`kali-frontend`-Static-Site-Deploys prüfen. Bis das behoben ist: das
Backend-Dashboard oben (Weg A/B) oder das lokale Frontend (Abschnitt
"Frontend" unten) nutzen.

### Frontend (optional, React/Vite statt der eingebauten Oberfläche)

```bash
cd frontend
npm i
cp .env.example .env
npm run dev
```
Dann `http://localhost:8080/` öffnen, bei laufendem Backend (Schritt 4
oben, Weg A) parallel im Hintergrund.

## Architektur & Sicherheit

- **Strikte Trennung**: Crawler (`app/crawler.py`, `app/site_crawler.py`),
  Erkennungs-Engine (`app/analysis/`), Datenhaltung (`app/db.py`), Reporting
  (`app/reports.py`) sind unabhängige Module ohne Zirkelabhängigkeiten.
- **SSRF-Schutz** (`app/url_safety.py::validate_scan_url`): erlaubt nur
  `http`/`https` (`file://` wird ausnahmslos abgelehnt, für jede URL) und
  blockt private/Loopback-/Link-lokale IPs sowie Cloud-Metadata-Adressen,
  bevor irgendeine URL an Playwright geht. Gilt für die Start-URL und jeden
  vom Crawler entdeckten Link.
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
