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
  fixer Seitenzahl pro Kategorie, Notbremse `MAX_FLOW_STEPS`). Alle
  LLM-Aufrufe im Crawl-Pfad sind echt async (`AsyncAnthropic`, kein
  blockierender Call mehr im Event-Loop); `classify_page_category`
  (Routing-Entscheidung, nicht die Findings selbst) ist Content-Hash-
  gecacht (`_CATEGORY_CACHE`, TTL via `CATEGORY_CACHE_TTL_SECONDS`) — siehe
  `docs/superpowers/plans/2026-08-20-...-lighthouse.md`-Pendant unter
  `~/.claude/plans/` für den Speed/Qualitäts-Umbau, aktuell in Arbeit auf
  `feat/speed-quality-overhaul`. `app/url_safety.py` validiert jede
  Scan-Ziel-URL serverseitig gegen SSRF (private IPs, Cloud-Metadata,
  `file://`) bevor sie an Playwright geht.
- **Modul B – Visuelle/Layout-Analyse** (`app/analysis/visual.py`,
  `app/analysis/heuristics.py`): Kontrastberechnung, Button-Style-Vergleich,
  Trick-Questions/Autoplay/Low-Contrast-Legal-Text-Heuristiken.
- **Modul C – Beweissicherung** (`app/evidence.py`): Screenshot/DOM-Hashing
  (SHA-256), RFC-3161-Zeitstempel (best-effort), HAR-Aufzeichnung pro Scan.
  Caching ist bewusst nur für Crawl-Routing erlaubt (Modul A), nie für
  Findings — sonst würde ein Report scan-übergreifend veraltete Daten als
  "gefunden am Datum X" ausgeben.
- **Modul D – Compliance-Engine & Reports** (`app/compliance.py`,
  `app/reports.py`): Fund → Rechtsnorm-Mapping (`NORM_MAP`), Anbindung an
  `legal-text-mcp-de`, PDF-Report via WeasyPrint (braucht GTK — auf Windows
  ohne GTK fällt die Testsuite auf einen Mock zurück, siehe
  `tests/conftest.py`). Report hat eine gerichtsfeste Deckblatt-Seite
  (Risk-Score/-Badge, Norm-Zusammenfassung) vor der Fund-Tabelle.
- Dazu: `app/analysis/llm_classify.py` (Claude-Textklassifikator für
  Dark-Pattern-Sprache), `app/analysis/pipeline.py` (`run_analysis`,
  bündelt alle Erkennungsstufen inkl. Confidence-Boost bei Mehrfachfunden),
  `app/llm_utils.py` (`extract_text` — robustes Auslesen des ersten
  Text-Blocks einer Messages-API-Response, ThinkingBlock-sicher), `app/db.py`
  (SQLite-Schema: `scans`, `pages`, `findings`), `app/main.py` (FastAPI:
  Dashboard = Scan-Übersicht mit Risk-Badges (`aggregate_risk_score`,
  `list_scans`), Scan-Detail mit serverseitigen Fund-Filtern, Page-Detail,
  `POST /scans` startet Site-Scan, PDF-Report-Route). Web-App-first
  (Chrome-Extension wurde entfernt, siehe Kontext oben) mit gemeinsamem
  Design-System (`static/style.css` + `app/templates/base.html`, von allen
  Templates geteilt).

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

**Abgeschlossener Umbau (Stand 2026-08-21):** Speed/Qualitäts-Überholung
des Crawlers/der Analyse — alle 5 Phasen (Async-LLM, Time-Budget im
Flow-Walk, Routing-Cache, Erkennungsqualitäts-Fixes inkl. Schema-Zwang für
`pattern_type`, Doku/Kalibrierung) fertig auf `feat/speed-quality-overhaul`
(Worktree `.worktrees/speed-quality-overhaul`), ausgeführt per
`superpowers:subagent-driven-development` gegen den Plan unter
`~/.claude/plans/funktioniert-es-jetzt-besser-replicated-lighthouse.md`
(nicht im Repo). 7 Tasks + finale Whole-Branch-Review + 1 Fix-Runde, alle
sauber. Vollständiges Ledger:
`.superpowers/sdd/funktioniert-es-jetzt-besser-replicated-lighthouse/progress.md`
in diesem Worktree (git-ignored, wird nach dem Mergen gelöscht — Git-
History ist dann die Aufzeichnung). Test-Stand: 134 passed, 1 skipped
(GTK). **Offen, vor dem Mergen vom Nutzer selbst zu prüfen:** ein echter
Scan gegen eine reale Seite, `master`/Vorgänger-Branch vs. diesem Branch
verglichen (Fund-Anzahl, Wanduhrzeit) — die finale Review fand vier
unabhängige, je für sich plausible Recall-Erweiterungen (Negations-
Keywords, Legal-Keywords, Countdown-Hints, Pflicht-Checkbox-Handling), die
zusammen die Präzision spürbar senken könnten; zwei konkrete
Substring-Fehltreffer ("ohne" in "Wohnadresse", "ablauf" in
"Bestellablauf") wurden bereits gefixt, der Rest ist nur per echtem Scan
zu beurteilen (braucht Live-Netzwerk + Anthropic-API-Guthaben, deshalb
nicht automatisiert gelaufen).
