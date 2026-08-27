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
  Trick-Questions/Autoplay/Low-Contrast-Legal-Text-/Decoy-Pricing-
  Heuristiken (`find_decoy_pricing` — strukturelle Preistabellen-Erkennung,
  Geschwister-Preiskarten mit `<ul>/<ol>`, flag bei ≤15% Preisunterschied
  und ≥3× Value-Verhältnis; deutsche Preisformate only, siehe
  `# ponytail:`-Kommentar davor für die dokumentierte Erkennungsgrenze).
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
  Dark-Pattern-Sprache, `PATTERN_TYPES` nur noch 6 Typen: Confirm Shaming,
  Sneaking/Hidden Costs, Decoy Pricing, Nagging, Roach Motel, Forced Path),
  `app/analysis/regex_classify.py` (`find_regex_patterns` — deterministische
  DE/EN-Regex-Erkennung für die restlichen 4 Typen: Fake Urgency, Fake
  Scarcity, Fake Social Proof, Forced Continuity; portiert aus
  `vendor/pattern-highlighter/chrome/scripts/constants.js`, MIT-lizenziert,
  ersetzt dafür den LLM-Call — schneller, deterministisch, kein API-Call),
  `app/analysis/pipeline.py` (`run_analysis`,
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

## Kategorie-Scoping der Fund-Erkennung
Site-Crawl-Seiten werden in eine von 5 Kategorien eingeordnet
(`classify_page_category`, `app/site_crawler.py::PAGE_CATEGORIES`) plus
Fallback `other`. `run_analysis` (`app/analysis/pipeline.py`) sucht seit
2026-08-25 pro Kategorie nur nach den dort inhaltlich plausiblen
Pattern-Typen (`CATEGORY_ALLOWED_PATTERNS`, dort die Quelle der Wahrheit —
dieser Abschnitt beschreibt nur das Warum) — reduziert False Positives wie
"Fake Social Proof" auf einer Checkout-Seite. Gilt nur für den Site-Crawl
(`app/scan.py::_analyze_page`), da dort allein die Kategorie eines Fundes
bekannt ist; der Single-Page-Scan (`run_scan`) bleibt ungefiltert.

- **Cookie- & Consent-Banner** (`cookie_consent`): Pre-ticked Box, Trick
  Questions, Fehlende Reject-Option, Cookie Wall, Visuelle Asymmetrie
  (Button) — die DSGVO-/Consent-typischen Muster.
- **Checkout- & Bezahlprozesse** (`checkout_payment`): Decoy Pricing,
  Hidden/Sneaking Costs, Fake Urgency/Scarcity, Confirm Shaming, Trick
  Questions (z.B. gegenteilig formulierte Zusatzoptions-Checkboxen im
  Checkout), Visuelle Asymmetrie, Sprachkomplexität, Kontrast-Tarnung —
  alles, was Kaufdruck erzeugt oder Kosten/AGB verschleiert.
- **Produktdetail- & Kategorieseiten** (`product_category`): Fake
  Scarcity/Social Proof/Urgency, Decoy Pricing, Autoplay, Infinite Scroll —
  Kaufanreiz- und Bindungs-Muster.
- **Account-Verwaltung & Kündigungsstrecken** (`account_subscription`):
  Roach Motel, Forced Continuity, Nagging, Confirm Shaming, Forced Path,
  Sprachkomplexität, Kontrast-Tarnung — Muster rund um erschwerten Ausstieg.
- **Pop-ups, Overlays & Lead-Formulare** (`popup_leadform`): Nagging, Trick
  Questions, Pre-ticked Box, Confirm Shaming, Forced Path.
- **other**: ungefiltert (kein Recall-Verlust auf nicht klassifizierbaren
  Seiten).

Zusätzlich hat `apply_consent_rules` (`app/crawler.py`) seit demselben Tag
einen generischen text-basierten Fallback-Klick (Suche nach
"ablehnen"/"reject"/… über alle sichtbaren Klick-Elemente), falls keine der
206 vendorten Consent-O-Matic-Regeln (`data/consent_rules/`) den
Banner der jeweiligen Seite matcht — vorher blieb der Banner in diesem Fall
unbemerkt auf der Seite stehen und damit auch auf dem Beweis-Screenshot.

## Vorhandene Open-Source-Bausteine als Referenz
Details in `Bestehende Dark-Pattern-Erkennungs-Projekte.md`. Kurzüberblick:
- **Dapde Pattern-Highlighter** – clientseitig, zeitversetzter DOM-Vergleich (Countdowns, Scarcity);
  komplettes Repo unter `vendor/pattern-highlighter/` vendored, dessen
  DE/EN-Regex-Tabelle zusätzlich handportiert in `app/analysis/regex_classify.py`
  läuft (siehe Kernmodule oben) — kein Import-Pfad aus `app/` zeigt auf
  `vendor/`. Die vendorte Kopie ist inzwischen selbst eine aktive,
  eigenständige Kali-Browser-Extension (nicht mehr nur inertes
  Referenzmaterial): `vendor/pattern-highlighter/chrome/scripts/constants.js`
  wurde um 4 weitere Pattern-Typen erweitert (Pre-ticked Box, Autoplay,
  Trick Questions, Decoy Pricing — JS-Ports derselben Erkennungslogik wie
  `app/analysis/heuristics.py`), rein deklarativ über `patternConfig`
  (`content.js` unverändert, iteriert generisch). Bewusst ohne die 6
  LLM-Typen, damit die Extension komplett lokal bleibt (kein
  Backend-/API-Call). `tagBlacklist` (`constants.js`) enthält kein
  `audio`/`video` mehr (war für Autoplay-Erkennung blockierend). Kein
  automatisiertes JS-Test-Setup vorhanden — Verifikation nur manuell
  (`chrome://extensions` → entpackt laden)
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
- `vendor/pattern-highlighter/` — Fork von Dapde/Pattern-Highlighter (MIT),
  inzwischen aktive Kali-Browser-Extension (8 Pattern-Typen, siehe oben);
  die Regex-Erkennung der ursprünglichen 4 läuft zusätzlich handportiert
  serverseitig in `app/analysis/regex_classify.py`
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

**Regex-Vorklassifizierung (Stand 2026-08-21):** 4 der 10 LLM-klassifizierten
Text-Pattern-Typen (Fake Urgency, Fake Scarcity, Fake Social Proof, Forced
Continuity) laufen jetzt über `app/analysis/regex_classify.py` statt über
`classify_text` — Vorrecherche zu einem ML-Ersatz (externe Repos/Datensätze
für einen selbst-trainierten Klassifikator) ergab, dass keiner der
geprüften Kandidaten (payalsinghcodes/AI-Dark-Patterns-Browser-Detector:
kein trainiertes Modell, kaputte Pipeline; Roboflow-Vision-Modell: nur
binär, veraltet; HuggingFace `asquirous/bert-base-uncased-dark_patterns`:
laut eigenem Model Card bei der Typ-Klassifikation unzuverlässig)
einsatzbereit war — stattdessen der regelbasierte Ansatz aus Dapde/
Pattern-Highlighter übernommen (siehe oben). Ein selbst-trainiertes,
schlankes Modell (TF-IDF+LogReg) für die verbleibenden 6 LLM-Typen ist als
separater, späterer Task angedacht, nicht Teil dieses Changes. Test-Stand:
146 passed, 1 skipped (GTK).

**Decoy-Pricing-Heuristik + erweiterte Extension (Stand 2026-08-21):**
`find_decoy_pricing` (`app/analysis/heuristics.py`) macht Decoy Pricing zum
5. deterministischen Typ (neben den 4 Regex-Typen) — einziger der 6
verbleibenden LLM-Typen, der strukturell statt sprachlich erkennbar ist
(Nagging/Roach Motel/Forced Path bräuchten Mehrseiten-Flow, Confirm
Shaming ist reine Tonalität, Sneaking/Hidden Costs zu kontextabhängig).
Parallel wurde `vendor/pattern-highlighter/` von reinem Referenzmaterial
zur aktiven, eigenständigen Extension ausgebaut (4 zusätzliche Pattern-
Typen, siehe Bausteine-Abschnitt oben) — bewusst nur die deterministischen
Typen, damit die Extension ohne Backend-Verbindung auskommt. Test-Stand:
150 passed, 1 skipped (GTK). Offen: manueller Extension-Smoke-Test
(`chrome://extensions`), noch nicht durchgeführt.

**Lovable-Frontend angebunden (Stand 2026-08-23):** `frontend/` — Vite/
React/shadcn-Frontend (Lovable-generiert, ursprünglich eigenes Repo
`gentle-rework-lab`, jetzt ohne dessen Git-History hier eingebunden, siehe
README "Frontend"-Abschnitt) läuft parallel zur Jinja2-Oberfläche auf
einem eigenen Dev-Server (Port 8080) und spricht ein neues Read-only-
JSON-API (`GET /api/scans`, `/api/scans/{id}`,
`/api/scans/{id}/pages/{id}`, `app/main.py`) über CORS an
(`FRONTEND_ORIGIN`-Env-Var, Default `http://localhost:8080`). Die Routen
sind dünne Wrapper um die bestehenden `app/db.py`-Funktionen inkl.
`_attach_display_fields`. `frontend/src/lib/api.ts` ist der Client dazu.
Stand 2026-08-26: sowohl `CaseAnalysis.tsx` (Scan starten + pollen) als
auch `Dashboard.tsx` (Case-Liste via `getScans()`) laufen auf echten
Daten. Offen bleibt nur das Verdrahten der "Confirm for review"/"Dismiss
finding"-Buttons in `CaseAnalysis.tsx` — der einzige Backend-Endpunkt dafür
(`POST /scans/{id}/findings/{id}/review`) ist Form-encoded/redirect, kein
JSON-Pendant, und der Review-Block müsste zudem pro Finding statt einmalig
platziert werden.
