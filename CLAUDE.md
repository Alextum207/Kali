# Kali – Dark-Pattern-Erkennungs-Monitor

## Kontext
Projekt für den **Legal Loves Tech Hackathon 2026**, Challenge der **Verbraucherzentrale**.
Ziel: ein automatisierter Webseiten-/Design-Monitor, der digitale Oberflächen auf
manipulative Gestaltung (Dark Patterns) untersucht — als skalierbares
Marktbeobachtungs-Tool, nicht als reine Browser-Extension. Das System soll
Funde zeithistorisch dokumentieren, gerichtsfest als Beweismittel sichern und
rechtlich eingeordnet für Prüfprozesse (Verbraucherzentralen, Aufsichtsbehörden)
aufbereiten.

Projektname: **Kali** (Logo: `logo.jpg`).

Stand: **funktionierender Prototyp**, lokal lauffähig
(`uvicorn app.main:app --reload`, siehe `README.md`). Tech-Stack ist
entschieden (Python, FastAPI, Playwright, SQLite, WeasyPrint, Anthropic
Claude). Git-Repo: https://github.com/Alextum207/Kali (privat).

## Relevante Rechtsnormen (Tatbestands-Mapping)
- **UWG §§ 5, 5a; Anhang zu § 3 Abs. 3** — Irreführung: Fake Urgency, Fake Scarcity, Fake Social Proof, versteckte Entgelte
- **BGB § 312j Abs. 3, 4; EGBGB Art. 246a** — Button-Lösung, Transparenz kostenpflichtiger Verträge/Zusatzoptionen
- **DSA Art. 25** — Verbot manipulativer Online-Schnittstellen (visuelle Button-Asymmetrie, erschwerte Kündigung/Opt-out, Confirm Shaming)
- **DSGVO Art. 4 Nr. 11, Art. 7 Abs. 4** — Einwilligung: Pre-ticked Boxes, Kopplungsverbot, Cookie-Banner/CMPs
- **PAngV** — Preistransparenz, nachträgliche Preisaufschläge

Jeder Fund soll folgende Datenstruktur haben: `pattern_type`, `target_norm`,
`confidence_score` (0.0–1.0), `evidence_data` (Screenshot/DOM/HAR/Zeitstempel).

## Kernmodule (implementiert)
- **Modul A – Crawling & Orchestrierung** (`app/crawler.py`, `app/site_crawler.py`):
  Playwright-Headless-Crawl, Cookie-Banner-Handling (`apply_consent_rules`,
  `data/consent_rules/` — Consent-O-Matic-Regeln), DOM-Snapshots
  (`_snapshot_page`). Site-weiter BFS-Crawler (`crawl_site`) mit
  kategorie-fokussierter Queue-Priorisierung (Zielkategorien
  `checkout_payment`, `account_subscription`, `product_category` werden vor
  generischen Seiten besucht) und flow-getriebenem Mehrschritt-Walk
  (`_walk_category_flow`, LLM-gesteuertes Durchklicken bis Flow-Ende statt
  fixer Seitenzahl pro Kategorie, Notbremse `MAX_FLOW_STEPS`).
- **Modul B – Visuelle/Layout-Analyse** (`app/analysis/visual.py`,
  `app/analysis/heuristics.py`): Kontrastberechnung, Button-Style-Vergleich,
  Trick-Questions/Autoplay/Low-Contrast-Legal-Text-Heuristiken.
- **Modul C – Beweissicherung** (`app/evidence.py`): Screenshot/DOM-Hashing
  (SHA-256), RFC-3161-Zeitstempel (best-effort), HAR-Aufzeichnung pro Scan.
- **Modul D – Compliance-Engine & Reports** (`app/compliance.py`,
  `app/reports.py`): Fund → Rechtsnorm-Mapping (`NORM_MAP`), Anbindung an
  `legal-text-mcp-de`, PDF-Report via WeasyPrint (braucht GTK — auf Windows
  ohne GTK fällt die Testsuite auf einen Mock zurück, siehe
  `tests/conftest.py`).
- Dazu: `app/analysis/llm_classify.py` (Claude-Textklassifikator für
  Dark-Pattern-Sprache), `app/analysis/pipeline.py` (`run_analysis`,
  bündelt alle Erkennungsstufen inkl. Confidence-Boost bei Mehrfachfunden),
  `app/db.py` (SQLite-Schema: `scans`, `pages`, `findings`), `app/main.py`
  (FastAPI: Dashboard, `POST /scans` startet Site-Scan, PDF-Report-Route).

Architektur-Leitplanke laut Vorgabe: strikte Entkopplung von
Scraper/Analyse-Engine/DB/Reporting; robuste Erkennung über berechnete visuelle
Eigenschaften statt hartcodierter CSS-Klassen. Beides eingehalten (siehe
Modul-Aufteilung oben).

## Vorhandene Open-Source-Bausteine als Referenz
Details in `Bestehende Dark-Pattern-Erkennungs-Projekte.md`. Kurzüberblick:
- **Dapde Pattern-Highlighter** – clientseitig, zeitversetzter DOM-Vergleich (Countdowns, Scarcity)
- **Consent-O-Matic** – CMP-/Cookie-Banner-Erkennung via JSON-Regeln + CSS-Selektoren
- **OpenWPM / "Dark Patterns at Scale"** (Princeton) – serverseitiger Crawler, große Skalierung, Vorbild für Modul A
- **Kachastepien NLP-Classifier** – TF-IDF + Logistic Regression für manipulative Texte
- **dark-pattern-detector (Niranjan4560)**, **PatternShield** – LLM-gestützt (Gemini/Claude), PDF-Reports
- **UIGuard** – Computer Vision + NLP für visuelle Layout-Manipulation (Vorbild für Modul B)

## Dateien in diesem Ordner
- `PROJECT_CONTEXT.txt` — Kernbrief (Ziel, Rechtsrahmen, Module, Implementierungsvorgaben)
- `Bestehende Dark-Pattern-Erkennungs-Projekte.md` — Markt-/Literaturübersicht bestehender Tools
- `Challenge Verbraucherzentrale (III).pdf` — Original-Challenge-Dokument (Quelle für beide obigen Dateien)
- `logo.jpg` — Projekt-Logo ("Kali – Dark Pattern Detector")
- `docs/superpowers/specs/` — Design-Specs (z.B. Site-Crawl-Kategorie-Agenten),
  `docs/superpowers/plans/` — zugehörige Implementierungspläne
- `app/`, `tests/` — Implementierung (siehe Kernmodule oben) und Testsuite
- `data/consent_rules/` — Consent-O-Matic-Cookie-Banner-Regeln (Referenzdaten)
- `datasets/` — externer CSV-Trainingsdatensatz (nicht projekteigen, per
  `.gitignore` vom Repo ausgeschlossen)

## Hinweis für zukünftige Sessions
Tech-Stack ist entschieden, siehe `README.md` für Setup/Run/Tests. Offene
Punkte eher im Detail (z.B. Feintuning der kategorie-fokussierten
Crawl-Priorisierung, WeasyPrint/GTK unter Windows) als im Grundgerüst — vor
größeren Architekturänderungen trotzdem kurz mit dem Nutzer abstimmen
(siehe `superpowers:brainstorming`-Workflow, wurde bisher für Feature-Design
genutzt, z.B. `docs/superpowers/specs/2026-08-19-site-crawl-category-agents-design.md`).
