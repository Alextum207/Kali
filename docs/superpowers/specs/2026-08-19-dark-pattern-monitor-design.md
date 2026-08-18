# Dark-Pattern-Monitor — Design Spec

Datum: 2026-08-19
Kontext: Legal Loves Tech Hackathon 2026, Challenge der Verbraucherzentrale.
Zeitrahmen: 1 Woche, Solo-Entwicklung.

## 1. Ziel

Automatisierter Webseiten-/Design-Monitor, der digitale Oberflächen auf
manipulative Gestaltung (Dark Patterns) untersucht, Funde zeithistorisch
dokumentiert, gerichtsfest als Beweismittel sichert und den einschlägigen
Rechtsnormen zuordnet. Anders als eine Browser-Extension: ein skalierbares
Marktbeobachtungswerkzeug für Verbraucherzentralen und Aufsichtsbehörden.

## 2. Rechtlicher Rahmen (Tatbestands-Mapping)

- **UWG §§ 5, 5a; Anhang zu § 3 Abs. 3** — Fake Urgency, Fake Scarcity, Fake Social Proof, versteckte Entgelte
- **BGB § 312j Abs. 3, 4; EGBGB Art. 246a** — Button-Lösung, Transparenz von Zusatzoptionen
- **DSA Art. 25** — manipulative Online-Schnittstellen (Button-Asymmetrie, Obstruction, Confirm Shaming)
- **DSGVO Art. 4 Nr. 11, Art. 7 Abs. 4** — Pre-ticked Boxes, Kopplungsverbot, Cookie-Banner
- **PAngV** — Preistransparenz, nachträgliche Preisaufschläge

Jeder Fund erhält die Datenstruktur:
```
pattern_type: str        # z.B. "Fake Urgency", "Confirm Shaming"
target_norm: str         # z.B. "Art. 25 DSA", "§ 5a UWG"
confidence_score: float  # 0.0–1.0
evidence_data: {
  screenshot_path, dom_snapshot_path, har_path,
  timestamp, sha256, rfc3161_token
}
```

## 3. Ziel-Seiten für die Demo

booking.com, ryanair.com, aliexpress.com, wish.com, justfab.com — bekannt für
Cookie-Banner-Tricks, Fake Urgency/Scarcity, Checkout-Zusatzoptionen.

## 4. Architektur

Ein Python-Monolith (ein Prozess, `uvicorn`), fünf Komponenten:

```
Dashboard (FastAPI + Jinja2)
   │  Scan-Trigger
   ▼
Crawler (Modul A, Playwright)
   │  Rohdaten: DOM×2, Screenshots, HAR, Computed Styles
   ▼
Analyse-Engine (Modul B)
   │  Findings: pattern_type, confidence_score
   ▼
Evidence Store (Modul C, SQLite + Dateisystem)
   │
   ▼
Compliance-Engine (Modul D)
   │  + target_norm, Gesetzeszitat
   ▼
Dashboard zeigt Funde / WeasyPrint → PDF-Report
```

### 4.1 Modul A — Crawler & Orchestrierung

- **Playwright (Python)** steuert Zielseiten: Seitenaufruf, Cookie-Banner
  öffnen, Warenkorb-Interaktion, Checkout-Schritte soweit möglich.
- Cookie-Banner-Erkennung nutzt **importierte Consent-O-Matic-JSON-Regeln**
  (CSS-Selektoren pro CMP-Anbieter) statt eigener Selektor-Pflege.
- **Dapde-Prinzip**: zwei DOM-Snapshots im Abstand von 1,5s pro Seite, um
  skriptbasierte Änderungen (Countdown-Timer, Live-Bestandsanzeigen) zu
  erfassen.
- Sammelt pro Seite: DOM-Snapshots (t0, t0+1,5s), Screenshot, HAR-Datei,
  Computed Styles der relevanten Elemente (Buttons, Preise).
- Fehlerbehandlung: Seite schlägt fehl → loggen, ein Retry, Batch läuft
  weiter.

### 4.2 Modul B — Analyse-Engine

Zweistufige, kaskadierte Pipeline:

1. **Vorprüfung (billig, lokal)**: Regex/DOM-Heuristiken für offensichtliche
   Muster (Pre-ticked Checkboxen, Countdown-Elemente per Selektor).
2. **Textvorverarbeitung**: **trafilatura** extrahiert den Hauptinhalt und
   filtert Navigation/Footer/Werbe-Boilerplate heraus, bevor Text analysiert
   wird — reduziert Fehlalarme und LLM-Tokenkosten.
3. **LLM-Klassifikation**: **Anthropic Claude API** für mehrdeutige/textuelle
   Fälle (Confirm Shaming, rhetorischer Dringlichkeitsdruck), few-shot
   promptet mit gelabelten Beispielen aus dem **Mathur-Datensatz**
   ("Dark Patterns at Scale", Princeton).
4. **Visuelle Analyse**: Asymmetrie-Berechnung (Größen-/Kontrastverhältnis)
   zwischen z.B. „Akzeptieren"- und „Ablehnen"-Buttons aus Computed Styles.

Fehlerbehandlung: Claude-API nicht erreichbar → nur Heuristik-Funde mit
niedrigerem `confidence_score`, kein Abbruch.

### 4.3 Modul C — Beweissicherung & Historisierung

- **SQLite** für strukturierte Funde (ein Findings-Table + ein Scans-Table).
- Rohbeweise (Screenshots, DOM, HAR) im Dateisystem, referenziert über Pfade
  in SQLite.
- Pro Beweisdatei: SHA256-Hash + lokaler Zeitstempel, zusätzlich ein
  **amtlicher RFC3161-Zeitstempel** via **rfc3161ng** gegen einen freien TSA
  (freeTSA.org) — stärkt die "gerichtsfeste" Dokumentation über simples
  Hashing hinaus.
- Historisierung: mehrere Scans derselben URL bleiben alle erhalten, keine
  Überschreibung — ermöglicht Vergleich über Zeit.

### 4.4 Modul D — Compliance-Engine & Reports

- Jeder Fund wird per Regelwerk (`pattern_type` → `target_norm`) einer Norm
  zugeordnet.
- Der zitierfähige Gesetzestext wird zur Laufzeit über den
  **`legal-text-mcp-de`**-Server (BGB, UWG, DSGVO, EU-Recht inkl. DSA)
  geholt und im Report zitiert — kein manuelles Abschreiben von
  Gesetzestexten, bleibt aktuell.
  - Fällt der MCP-Server aus: Norm-Name wird trotzdem gesetzt, nur ohne
    Live-Zitat (kein Blocker).
- **WeasyPrint** rendert dieselben Jinja2-Templates wie das Dashboard zu
  PDF-Prüfberichten.
- *Stretch-Goal* (nur falls Zeit übrig): ergänzende Urteils-Zitate über
  `rechtsinformationen-bund-de-mcp` (BGH/BVerfG-Rechtsprechung) für mehr
  juristische Tiefe im Report. Kein MVP-Bestandteil.

### 4.5 Dashboard

- FastAPI-Routen + Jinja2-Templates (kein separates Frontend-Framework).
- Funktionen: Scan starten (URL-Liste), laufende/abgeschlossene Scans
  einsehen, Funde pro Scan anzeigen, PDF-Report herunterladen.

## 5. Tech-Stack & Abhängigkeiten

| Zweck | Wahl | Bemerkung |
|---|---|---|
| Crawling | Playwright (Python) | microsoft/playwright-python |
| Textextraktion | trafilatura | Apache 2.0, filtert Boilerplate |
| LLM | Anthropic SDK / Claude API | Klassifikation, few-shot |
| Zeitstempel | rfc3161ng + freeTSA.org | amtlicher RFC3161-Stempel |
| Cookie-Banner-Regeln | Consent-O-Matic JSON-Regeln (importiert) | CMP-Selektoren |
| Few-Shot/Test-Daten | Mathur-Datensatz (Princeton) | gelabelte Dark-Pattern-Instanzen |
| Backend/Dashboard | FastAPI + Jinja2 | ein Prozess, kein SPA |
| DB | SQLite | Findings + Scans |
| PDF-Report | WeasyPrint | HTML-Templates → PDF |
| Rechtstext-Zugriff | legal-text-mcp-de (MCP) | BGB/UWG/DSGVO/EU-Recht, Volltext |

**Bewusst nicht eingebunden**: changedetection.io (nur Vorbild fürs
Monitoring-Konzept), pywb (WARC unnötig für MVP, `wget --warc` reicht bei
Bedarf), Legal-Text-Analytics (reine Linksammlung), claude-fuer-deutsches-recht
(zu breiter Scope, generische Anwaltspraxis statt UWG/DSA-Fokus).

## 6. Testing

Kein volles E2E-Setup (zu fragil für eine Woche Solo-Zeit). Ein
`test_analysis.py`: lässt die Analyse-Engine gegen eine Handvoll gelabelter
Mathur-Beispiele laufen und prüft per `assert`, dass erwartete
`pattern_type`s mit plausiblem `confidence_score` erkannt werden — genug
Sicherheit vor der Live-Demo.

## 7. Out of Scope (Post-Hackathon)

- Periodisches Re-Crawling / Monitoring über Zeit (changedetection.io-Stil)
- WARC-Vollarchivierung
- Eigenes ML-Modell / Fine-Tuning statt LLM-API
- Urteils-Integration (rechtsinformationen-bund-de-mcp) — nur falls Zeit
  übrig bleibt
