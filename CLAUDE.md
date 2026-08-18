# Legal Tech – Dark-Pattern-Erkennungs-Monitor

## Kontext
Projekt für den **Legal Loves Tech Hackathon 2026**, Challenge der **Verbraucherzentrale**.
Ziel: ein automatisierter Webseiten-/Design-Monitor, der digitale Oberflächen auf
manipulative Gestaltung (Dark Patterns) untersucht — als skalierbares
Marktbeobachtungs-Tool, nicht als reine Browser-Extension. Das System soll
Funde zeithistorisch dokumentieren, gerichtsfest als Beweismittel sichern und
rechtlich eingeordnet für Prüfprozesse (Verbraucherzentralen, Aufsichtsbehörden)
aufbereiten.

Stand: **reine Konzept-/Recherchephase** — noch kein Code, kein Git-Repo.

## Relevante Rechtsnormen (Tatbestands-Mapping)
- **UWG §§ 5, 5a; Anhang zu § 3 Abs. 3** — Irreführung: Fake Urgency, Fake Scarcity, Fake Social Proof, versteckte Entgelte
- **BGB § 312j Abs. 3, 4; EGBGB Art. 246a** — Button-Lösung, Transparenz kostenpflichtiger Verträge/Zusatzoptionen
- **DSA Art. 25** — Verbot manipulativer Online-Schnittstellen (visuelle Button-Asymmetrie, erschwerte Kündigung/Opt-out, Confirm Shaming)
- **DSGVO Art. 4 Nr. 11, Art. 7 Abs. 4** — Einwilligung: Pre-ticked Boxes, Kopplungsverbot, Cookie-Banner/CMPs
- **PAngV** — Preistransparenz, nachträgliche Preisaufschläge

Jeder Fund soll folgende Datenstruktur haben: `pattern_type`, `target_norm`,
`confidence_score` (0.0–1.0), `evidence_data` (Screenshot/DOM/HAR/Zeitstempel).

## Geplante Kernmodule (~50–60 % Eigenleistung)
- **Modul A** – Crawling & Task-Orchestrierung (Headless-Browser, Interaktionen wie Warenkorb/Cookie-Banner, DOM-Snapshots)
- **Modul B** – Visuelle/Layout-Analyse (Computed Styles, Kontrast-/Größenverhältnisse Buttons, DSA Art. 25)
- **Modul C** – Gerichtsfeste Beweissicherung & Historisierung (zeitgestempelte Snapshots, HAR-Dateien, Screenshots)
- **Modul D** – Compliance-Engine & PDF/JSON-Report-Generator (Fund → Rechtsnorm-Zuordnung)

Architektur-Leitplanke laut Vorgabe: strikte Entkopplung von
Scraper/Analyse-Engine/DB/Reporting; robuste Erkennung über berechnete visuelle
Eigenschaften statt hartcodierter CSS-Klassen.

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

## Hinweis für zukünftige Sessions
Noch keine Tech-Stack-Entscheidung getroffen (Python/Playwright wird in
PROJECT_CONTEXT.txt nur als Beispiel genannt, nicht als Festlegung). Vor
Implementierungsbeginn: Tech-Stack, Datenhaltung und Scope mit dem Nutzer klären.
