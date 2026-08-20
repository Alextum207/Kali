# FairPatterns-artiges Web-App-Redesign + Report — Design Spec

**Datum:** 2026-08-20
**Status:** Approved (Brainstorming abgeschlossen)

## Kontext & Ziel

Kali hat einen funktionierenden Erkennungs-Backend (Crawler, Heuristiken,
LLM-Klassifikator, Compliance-Norm-Mapping, Evidence-Hashing), aber eine
minimale Web-Oberfläche (4 Templates, 115 Zeilen gesamt) und einen
rudimentären PDF-Report. Vorbild für die neue Präsentationsschicht ist
[fairpatterns.ai](https://www.fairpatterns.ai/) — eine Dark-Pattern-
Compliance-Plattform mit professionellem, minimalistischem Look und
"litigation-grade" Reports.

**Explizit kein 1:1-Klon:** Es wird kein Wortlaut, keine Markenelemente,
keine Copy von FairPatterns übernommen. Übernommen wird das *Konzept*
(Web-App mit Risiko-Score-Übersicht, professionelles Compliance-Report-
Layout), nicht Text oder Branding.

**Scope laut Brainstorming-Entscheidung:** Nur App/Tool + Report (keine
Marketing-Landingpage, kein Pricing, keine Research-Labs, kein
Figma-Plugin — das bildet den Kern von FairPatterns' Angebot außerhalb des
reinen Scan-Tools ab und ist für den Hackathon-Demozweck nicht relevant).

## Bestandsaufnahme (bereits geprüft)

- `app/main.py` (FastAPI-Routen), `app/reports.py` (WeasyPrint-PDF) —
  Ziel dieses Rewrites.
- Backend-Module (`crawler.py` 325, `site_crawler.py` 432, `scan.py` 187,
  `compliance.py` 120, `analysis/*` ~350, `evidence.py` 30, `db.py` 113,
  `llm_utils.py` 11 Zeilen) sind bereits schlank, klar getrennte
  Zuständigkeiten (Einzelseiten-Crawl vs. Site-BFS+Flow), **keine
  Rewrite-Kandidaten** — nur ein kurzer Audit-Task (siehe unten).
- `extension/` (186 Zeilen: `background.js`, `popup.js`, `popup.html`,
  `manifest.json`) + `POST /scans/extension` in `main.py` (inkl.
  `ExtensionScanRequest`, `cookies`-Parameter durch `run_site_scan` bis
  `crawler.py`) — wird **entfernt** (Entscheidung: passt nicht zum
  Web-App-first-Produktbild aus `CLAUDE.md`).

## Informationsarchitektur (Web-App)

Vier Seiten, gemeinsames `base.html`-Layout (Nav: "Dashboard" /
"Neuer Scan"):

1. **`GET /` — Dashboard = Scan-Übersicht.** Liste aller bisherigen Scans
   (URL, Datum, Status, aggregierter Risiko-Score als Badge) + Formular
   "Neuer Scan" (URL-Eingabe, optional `max_pages`) — ersetzt die
   aktuelle leere Landingpage. Braucht eine neue DB-Abfrage `list_scans()`
   in `app/db.py` (aktuell gibt es nur `get_scan()` für eine ID).
2. **`GET /scans/{id}` — Scan-Detail.** Risk-Summary-Header (aggregierter
   Score, Anzahl Findings je Pattern-Kategorie) oben, darunter
   Findings-Tabelle mit clientseitigen Filtern (Pattern-Type, Norm,
   Confidence-Schwelle — reines HTML/CSS `<select>` + kleines Vanilla-JS,
   kein Framework) statt der aktuellen ungefilterten Liste.
3. **`GET /scans/{id}/pages/{page_id}` — Page-Detail.** Bleibt inhaltlich
   wie jetzt (Screenshot + Findings der Unterseite), nur im neuen visuellen
   System.
4. **`GET /scans/{id}/report.pdf` — Report.** Bleibt als Route/Funktions-
   signatur (`generate_pdf_report(url, findings, out_path)`), Template
   und Inhalt werden neu gestaltet (siehe unten).

Bestehende Routen (`POST /scans`, `GET /evidence/{filename}`) bleiben
unverändert. `POST /scans/extension` wird gelöscht.

## Risiko-Score

Eine neue Funktion `aggregate_risk_score(findings: list[dict]) -> dict` in
`app/compliance.py` (thematisch verwandt mit dem dortigen
Norm-Mapping/Konfidenz-Handling). Wird an drei Stellen gebraucht:
Dashboard-Scan-Liste, Scan-Detail-Header, Report-Deckblatt.

Berechnung (einfache, nachvollziehbare Heuristik statt Blackbox-Index):

```python
def aggregate_risk_score(findings: list[dict]) -> dict:
    """Returns {"score": float 0.0-1.0, "level": "niedrig"|"mittel"|"hoch",
    "by_category": {pattern_type: count}}.
    score = mean(confidence_score) over findings, weighted by count
    (mehr Funde bei gleicher Konfidenz = höheres Risiko: score wird um
    einen kleinen Volumen-Faktor angehoben, gedeckelt bei 1.0).
    level: score < 0.34 -> "niedrig", < 0.67 -> "mittel", sonst "hoch".
    Leere findings-Liste -> {"score": 0.0, "level": "niedrig", "by_category": {}}.
    """
```

Level-Grenzen (0.34 / 0.67) sind eine bewusste einfache Heuristik ohne
tieferen empirischen Unterbau — für die Hackathon-Demo ausreichend,
markiert im Code als bewusste Vereinfachung.

## Visuelles Design-System

Ein neues `app/static/style.css` (FastAPI liefert `static/` per
`StaticFiles`-Mount aus, muss in `main.py` ergänzt werden), CSS-Variablen
für Design-Tokens:

- Farben: `--color-bg`, `--color-text`, `--color-border` (Schwarz/Weiß-
  Basis), plus 3 Risiko-Farben (`--color-risk-low` grün,
  `--color-risk-medium` orange, `--color-risk-high` rot) für Score-Badges
  und Confidence-Anzeigen.
- Typo: System-Font-Stack (`-apple-system, "Segoe UI", sans-serif`, kein
  Font-Download), klare Type-Scale (`--font-size-sm/base/lg/xl`).
- Spacing-Scale (`--space-1` … `--space-6`) für konsistente Abstände.

Kein CSS-Framework, kein Build-Step — eine handgeschriebene Stylesheet-
Datei, in `base.html` per `<link>` eingebunden. Layout: viel Weißraum,
Karten/Tabellen statt verschachtelter Widgets, reduzierte Nav-Leiste.

## Report-Redesign (`app/templates/report.html`)

Bleibt WeasyPrint-basiert (`generate_pdf_report()`-Signatur unverändert:
`url, findings, out_path`), aber neu strukturiert:

1. **Deckblatt:** Kali-Logo (`logo.jpg`, als `file://`-Pfad oder Base64
   für WeasyPrint eingebettet), gescannte URL, Scan-Datum, aggregierter
   Risiko-Score (aus `aggregate_risk_score()`).
2. **Executive Summary:** Tabelle "Anzahl Findings je Rechtsnorm" (aus
   `by_category`/`target_norm`), keine JS-Charts (WeasyPrint rendert kein
   JS) — reine HTML/CSS-Balken (`<div>`-Breite via `style="width: X%"`)
   oder Zahlen-Tabelle, je nachdem was in Task-Umsetzung sauberer aussieht.
3. **Pro Finding ein Evidence-Block:** Pattern-Type, Norm-Zitat (aus
   `compliance.NORM_MAP`), Confidence-Badge (farbcodiert wie im Web-UI),
   Screenshot (eingebettet), Zeitstempel + Hash aus `evidence_data`
   (SHA-256, RFC-3161 falls vorhanden).

`generate_pdf_report()` in `app/reports.py` übergibt zusätzlich
`risk=aggregate_risk_score(findings)` an den Jinja-Kontext.

## Backend-Audit-Task (kompakt, kein Rewrite-Programm)

Ein Task im Implementierungsplan führt einen gezielten Scan über
`app/*.py` (außer den bereits oben geprüften/für den Rewrite ohnehin
angefassten Dateien) durch, mit Fokus auf:
- `app/llm_utils.py` (11 Zeilen) — prüfen ob eigenständiges Modul
  gerechtfertigt ist oder Inline-Kandidat.
- Tote Importe/Funktionen, die durch die Extension-Entfernung entstehen
  (`cookies`-Parameter-Kette durch `scan.py` → `site_crawler.py` →
  `crawler.py`, falls dort nur für den Extension-Pfad gebraucht —
  **muss geprüft werden**, ob `cookies` auch für normale Scans relevant
  ist, bevor die Parameter gestrichen werden).

Ergebnis wird als Findings-Liste im Task dokumentiert, offensichtliche
Streichungen werden im selben Task umgesetzt (kein separater Plan nötig
für so einen kleinen Scope).

## Tests

- `tests/test_main.py`: neue/angepasste Tests für Dashboard-Scan-Liste
  (`GET /` zeigt vorhandene Scans), entfernte `/scans/extension`-Route
  (404 erwartet), `static/style.css` wird ausgeliefert.
- `tests/test_compliance.py`: neue Tests für `aggregate_risk_score()`
  (leere Liste, einzelner Fund, mehrere Funde/Kategorien, Level-Grenzen).
- Report-Test (WeasyPrint, ggf. gemockt wie in `tests/conftest.py`):
  prüft dass `risk`-Kontext ins Template übergeben wird.
- Extension-Tests (`tests/test_*.py`, falls vorhanden für die Extension-
  Route) werden gelöscht statt angepasst.

## Out of Scope

- Marketing-Landingpage, Pricing, Research-Labs, Figma-Plugin (siehe
  Scope-Entscheidung oben).
- Multi-User/Auth (nicht Teil des aktuellen Produkts).
- Charting-Library für den Report (WeasyPrint + reines CSS reicht für den
  Demozweck).
