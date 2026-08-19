# Site-weiter Multi-Page-Crawl mit Kategorie-Strategien — Design

## Kontext & Ziel

Der bestehende Dark-Pattern-Monitor scannt genau eine URL pro Scan
(`app/scan.py:run_scan`). Dieses Feature erweitert ihn zu einem **site-weiten
Crawler**, der ausgehend von einer Start-URL (z.B. `www.adidas.de`) selbständig
durch die Seite navigiert — ähnlich einem Puppeteer/Playwright-Testlauf, der
echte Nutzerflüsse durchspielt (Warenkorb, Checkout, Kündigung, Cookie-Banner)
statt nur passiv Links zu sammeln.

Grundlage ist eine Buchzusammenfassung zu Dark-Pattern-Taxonomie
(`Recherche/buch zusammenfassung.pdf`, Auszug aus einem Fachbuch zu
"Deceptive Patterns", vermutlich Brignull). Das Buch liefert die
Kategorie-Strategien, neue Pattern-Typen, Rechtsbezüge und Konfidenz-Referenzwerte,
die in diesem Design direkt verwertet werden.

**Zielabdeckung:** Von den 8 im Buch beschriebenen fundamentalen
Manipulations-Strategien adressiert dieses Feature alle 8 technisch (siehe
"Abdeckungs-Matrix" unten) — jeweils als Nachweis der **Präsenz eines
manipulativen Mechanismus** (z.B. Autoplay-Attribut vorhanden, Kontrast unter
Schwellwert, Klick-Tiefe X). Was strukturell außerhalb der Reichweite bleibt,
ist ein *Wirksamkeitsnachweis* — dass ein Mechanismus reale Nutzer über Zeit
tatsächlich beeinflusst (siehe "Explizit außerhalb des Scopes").

## Architektur-Überblick

```
run_site_scan(start_url, conn, evidence_dir, browser, max_pages=?, llm_client=None)
  │
  ├─ 1x Playwright BrowserContext für die ganze Site (→ 1 HAR-Datei/Site)
  │
  └─ BFS-Loop über app/site_crawler.py:
       für jede Seite in der Queue (bis max_pages erreicht):
         a) navigieren, apply_consent_rules() (bestehend, unverändert)
         b) Seiten-Snapshot: DOM, Screenshot, button_styles (bestehende Logik aus crawl_page,
            faktorisiert in eine wiederverwendbare Funktion)
         c) classify_page_category() → eine von 5 Kategorien (Heuristik, LLM-Fallback)
         d) run_analysis() auf dieser Seite (bestehende Pipeline + neue Stufen, s.u.)
         e) decide_next_interaction() → LLM entscheidet nächsten Klick (kategoriebewusst)
         f) falls Klick-Ziel vorhanden: klicken, sonst zur nächsten Queue-URL
         g) neue <a href>-Links extrahieren, per validate_scan_url() filtern, in Queue einreihen
```

**Ein LLM-Call-Budget pro Seite:** bis zu 3 (Kategorie-Fallback, Interaktionsentscheidung,
Text-Klassifikation `classify_text`) × `max_pages`. Der bestehende
Fehler-Isolations-Fix (`classify_text`-Fehler bricht nicht den ganzen Scan ab,
siehe `app/analysis/pipeline.py`) gilt unverändert und ist hier besonders wichtig.

## Neue/geänderte Module

### `app/site_crawler.py` (neu)

- `discover_links(dom_html: str, base_url: str, allowed_hosts: set[str]) -> list[str]`
  — extrahiert `<a href>` aus dem DOM (BeautifulSoup, wie `app/analysis/heuristics.py`
  bereits tut), normalisiert relative URLs gegen `base_url`, filtert auf
  `allowed_hosts` (exakte Domain + Subdomains — `hostname == host or
  hostname.endswith("." + host)`).
- `classify_page_category(url: str, dom_html: str, llm_client=None) -> str`
  — gibt einen von `PAGE_CATEGORIES` zurück: `cookie_consent`,
  `checkout_payment`, `product_category`, `account_subscription`,
  `popup_leadform`, `other`. Erst URL-Regex + Überschrift-Keyword-Heuristik
  (siehe Tabelle unten), nur bei Uneindeutigkeit ein LLM-Fallback-Call.
- `decide_next_interaction(category: str, clickable_elements: list[dict], llm_client=None) -> dict | None`
  — `clickable_elements` ist eine kompakte Liste `{text, selector}` aller
  Buttons/Links auf der Seite (kein voller DOM/Screenshot, um Tokens zu sparen).
  Ein LLM-Call pro Seite, kategoriebewusster Prompt (siehe "Kategorie-Prompts"
  unten). Rückgabe `{"type": "click", "target": "<selector>"}` oder `None`.
- `crawl_site(start_url: str, browser, max_pages: int, har_dir: str, llm_client=None) -> dict`
  — der BFS-Orchestrator. Gibt zurück:
  `{"pages": [{"url", "category", "dom_after", "screenshot", "button_styles"}, ...], "har_path": str}`.
  Wiederverwendet die Snapshot-Logik aus `app/crawler.py:crawl_page`
  (Doppel-Snapshot, `_read_style`, `apply_consent_rules`) — bestehende
  Helfer werden nicht dupliziert, sondern aus `app/crawler.py` importiert bzw.
  in eine gemeinsame `_snapshot_page(page)`-Hilfsfunktion extrahiert, die
  sowohl `crawl_page` (Einzelseiten-Scan, bleibt als Legacy-Pfad bestehen)
  als auch `crawl_site` nutzen.

### `app/analysis/heuristics.py` (erweitert)

Neue Funktionen, gleiches Muster wie bestehende (`find_preticked_checkboxes`,
`find_countdown_elements`):

- `find_trick_questions(dom_html: str) -> list[dict]` — findet Checkbox-Paare/-Listen,
  deren benachbarter Label-Text sich in der Opt-in/Opt-out-Logik widerspricht
  (Heuristik: zwei `<input type="checkbox">` mit Labels, die je ein Negations-Keyword
  enthalten wie "nicht"/"kein"/"not" in unterschiedlicher Polarität). Pattern-Typ:
  `"Trick Questions"`.
- `find_autoplay_media(dom_html: str) -> list[dict]` — `<video autoplay>` /
  `<audio autoplay>`. Pattern-Typ: `"Exploiting Addiction (Autoplay)"`.
- `find_low_contrast_legal_text(dom_html: str, page) -> list[dict]` —
  **Verallgemeinerung** von `app/analysis/visual.py:compute_button_asymmetry`:
  statt nur `#accept`/`#reject` werden alle Textelemente durchsucht, deren
  Text eines der Keywords enthält (`Kündigung`, `Widerruf`, `Gebühr`,
  Vertragslaufzeit`, `AGB`, `Schiedsgericht`), computed style gelesen (analog
  `app/crawler.py:_read_style`), und gegen den Seiten-Median-Kontrast/-Schriftgröße
  verglichen. Läuft im Crawler (braucht `page`-Objekt für `getComputedStyle`),
  nicht im reinen DOM-String — Signatur weicht daher von den anderen
  `find_*`-Funktionen ab (async, nimmt `page`). Pattern-Typ:
  `"Visuelle Tarnung (Kontrast)"`.

Diese müssen aus `app/analysis/pipeline.py:run_analysis` heraus aufgerufen
werden — `find_low_contrast_legal_text` speziell nur, wenn `run_analysis`
zusätzlich das `page`-Objekt bekommt (Signaturänderung, s.u.).

### `app/analysis/llm_classify.py` (erweitert)

- `SYSTEM_PROMPT`-Enum erweitert um: `Forced Continuity`, `Decoy Pricing`,
  `Nagging`, `Roach Motel`, `Forced Path`. **Wichtig:** jeder neue Eintrag
  bekommt sofort einen `NORM_MAP`-Eintrag in derselben Task, plus einen
  Eintrag im bereits existierenden Kontrakt-Test
  (`tests/test_compliance.py`, der prüft, dass jeder Prompt-Pattern-Typ einen
  Norm-Treffer hat — siehe Ledger der letzten Runde, dort wurde der erste
  Vokabular-Drift-Bug gefixt).
- `data/mathur_examples.json` bekommt Few-Shot-Beispiele für die neuen Typen
  aus den wörtlichen Zitaten der Buchzusammenfassung (Abschnitt "Wörtliche
  Text-Signale" der Zusammenfassung — z.B. Confirmshaming-Variationen,
  Trick-Question-Beispielsätze).
- Neuer, optionaler Parameter `readability_check: bool` oder eigene Funktion
  `flag_complex_language(text: str) -> dict | None` — Flesch-Kincaid-artige
  Formel **selbst implementiert** (Silbenzählung via Vokal-Gruppen-Heuristik,
  keine neue Dependency), vergleicht Lesbarkeits-Score von rechtsrelevanten
  Textabschnitten (Kündigungsklausel etc., per Keyword-Suche gefunden) gegen
  den Median-Score der übrigen Seite. Pattern-Typ:
  `"Verständnis-Barriere (Sprachkomplexität)"`.

### `app/analysis/pipeline.py` (geändert)

`run_analysis` bekommt einen neuen optionalen Parameter für die
Interaktions-/Struktur-Metadaten der Site-Crawl-Version (Klick-Tiefe zur
Kategorie-Zielhandlung, Kategorie der Seite) und ruft die neuen
Heuristik-/Klassifikations-Funktionen zusätzlich auf. Rückwärtskompatibel:
bestehende Aufrufer (`app/scan.py:run_scan`, Einzelseiten-Pfad) funktionieren
unverändert, neue Parameter sind optional mit sinnvollem Default.

**Confidence-Boost ("Double Shot", aus der Buchzusammenfassung):** Wenn auf
derselben Seite mehrere unterschiedliche `pattern_type`s gefunden werden,
wird für jedes zusätzliche Pattern über dem ersten der `confidence_score`
um einen festen Faktor angehoben (z.B. `+0.05`, gedeckelt bei `1.0`) — die
Logik gehört in `run_analysis`, nachdem alle Stufen gesammelt wurden, vor
der `map_to_norm`-Schleife.

### `app/compliance.py` (erweitert)

Neue `NORM_MAP`-Einträge (Zuordnung gemäß Buchzusammenfassung + bestehender
`CLAUDE.md`-Norm-Tabelle):

| Pattern-Typ | Norm |
|---|---|
| `Trick Questions` | `Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO` |
| `Forced Continuity` | `§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB` |
| `Decoy Pricing` | `UWG §§ 5, 5a; Anhang zu § 3 Abs. 3` |
| `Nagging` | `Art. 25 DSA` |
| `Roach Motel` | `Art. 25 DSA` |
| `Forced Path` | `Art. 25 DSA` |
| `Exploiting Addiction (Autoplay)` | `Art. 25 DSA` |
| `Visuelle Tarnung (Kontrast)` | `Art. 25 DSA` |
| `Verständnis-Barriere (Sprachkomplexität)` | `UWG §§ 5, 5a; Anhang zu § 3 Abs. 3` |

### `app/url_safety.py` (unverändert, wiederverwendet)

Jeder von `discover_links` gefundene Link läuft vor dem Navigieren durch das
bestehende `validate_scan_url` (SSRF-Schutz aus der letzten Runde) — keine
neue Sicherheitslogik nötig, nur ein zusätzlicher Aufrufer.

## Datenmodell (`app/db.py`)

Neue Tabelle zwischen `scans` und `findings`:

```sql
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL REFERENCES scans(id),
    url TEXT NOT NULL,
    category TEXT NOT NULL,
    crawled_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

`findings` bekommt eine neue Spalte `page_id INTEGER REFERENCES pages(id)`
(nullable, für Rückwärtskompatibilität mit dem alten Einzelseiten-Pfad, der
weiterhin `scan_id` direkt setzt und `page_id` NULL lässt). Neue Funktionen:

- `insert_page(conn, scan_id: int, url: str, category: str) -> int`
- `get_pages(conn, scan_id: int) -> list[dict]`
- `get_page_findings(conn, page_id: int) -> list[dict]` (Analog zu
  `get_findings`, aber nach `page_id` statt `scan_id` gefiltert)

`get_findings(conn, scan_id)` bleibt unverändert nutzbar (liefert weiterhin
alle Findings eines Scans über alle Seiten, da `findings.scan_id` bei jedem
Insert weiterhin gesetzt wird — denormalisiert, kein Join nötig für die
bestehende PDF-Report-Logik).

## `app/scan.py` — `run_site_scan` (neue Funktion, `run_scan` bleibt bestehen)

```python
async def run_site_scan(
    start_url: str, conn, evidence_dir: str, browser,
    max_pages: int | None = None, llm_client=None,
) -> int:
```

- `max_pages` Default kommt aus `os.environ.get("MAX_PAGES_PER_SCAN", "15")`
  (Parameter überschreibt Env-Var, wie bei `DB_PATH`/`EVIDENCE_DIR`).
- Ruft `crawl_site(...)` auf, legt für jede zurückgegebene Seite eine
  `pages`-Zeile an, führt `run_analysis` pro Seite aus, verknüpft Findings mit
  `page_id` **und** `scan_id`.
- Evidence-Handling analog zu `run_scan`: ein Screenshot pro Seite (Pfad
  enthält `page_id`), **eine** HAR-Datei für die ganze Site (von
  `crawl_site` zurückgegeben), SHA256-Hashes für beide Artefakttypen wie
  bisher, `fetch_citation` pro Finding wie bisher (ein gemeinsamer
  `httpx.AsyncClient` über den ganzen Site-Scan hinweg, nicht pro Seite neu
  öffnen).

## `app/main.py` — Route-Änderung

`POST /scans` ruft künftig `run_site_scan` statt `run_scan` auf (der alte
`run_scan`-Pfad bleibt im Modul bestehen, aber ungenutzt von der Route — falls
später ein "nur diese eine Seite scannen"-Modus gewünscht wird, ist er
weiterhin verfügbar). `max_pages` optional als Formularfeld
(`max_pages: int | None = Form(None)`), bei `None` greift der Env-Var-Default.

## Dashboard

`scan_detail.html` zeigt künftig eine Liste der gecrawlten Seiten
(URL + Kategorie + Finding-Anzahl), jede Zeile verlinkt auf eine neue Route
`GET /scans/{scan_id}/pages/{page_id}` (neues Template `page_detail.html`,
zeigt die Findings dieser einen Seite — gleiche Tabellenstruktur wie bisher
`scan_detail.html`, nur gefiltert). Der bestehende PDF-Report
(`app/reports.py`) bleibt unverändert auf `scan_id`-Ebene (alle Findings
eines Scans, seitenübergreifend) — kein Änderungsbedarf dort.

## Kategorie-Strategien im Detail

| Kategorie | URL/Keyword-Signale (Heuristik) | Interaktionsziel (LLM-Prompt-Kontext) | Zusätzliche Prüfungen |
|---|---|---|---|
| `cookie_consent` | (via `apply_consent_rules`, unverändert) | — | — |
| `checkout_payment` | URL enthält `checkout`/`kasse`/`warenkorb`/`cart`; Überschrift "Zur Kasse"/"Bestellübersicht" | Bis zum letzten Schritt vor Zahlung durchklicken, ohne echte Zahlung auszulösen | `find_trick_questions`, Preisänderung zwischen Schritten vergleichen (Snapshot-Diff der Preisanzeige) |
| `account_subscription` | URL enthält `account`/`konto`/`abo`/`subscription`/`kündig`; Überschrift "Mein Konto" | Kündigungs-/Löschpfad suchen und bis zur Bestätigung (ohne zu bestätigen) durchklicken, Klicks zählen | `Roach Motel`/`Forced Path`-Heuristik: Klick-Tiefe Anmeldung vs. Kündigung vergleichen; Medienbruch-Erkennung (Text "anrufen"/"telefonisch") |
| `product_category` | URL enthält `product`/`produkt`/`p/`/Kategorie-Pfadmuster | Zu einem Produkt navigieren, "In den Warenkorb" klicken | Scarcity-Text über wiederholten Seitenaufruf vergleichen (nur bei erneutem Besuch derselben URL innerhalb der Session) |
| `popup_leadform` | (erkannt durch neu erscheinendes Overlay-Element nach Seitenaufruf, nicht per URL) | X-Button klicken, danach prüfen ob Overlay erneut erscheint | `find_autoplay_media`, Nagging-Zähler (Wiedererscheinen innerhalb der Session) |
| `other` | Fallback | Keine gezielte Aktion, nur `discover_links` | Alle generischen Checks (`find_low_contrast_legal_text`, `flag_complex_language`) laufen hier immer |

## Abdeckungs-Matrix (Buch-Kategorien → Umsetzung)

| # | Buch-Kategorie | Nach diesem Feature |
|---|---|---|
| 1 | Perzeptuelle Schwachstellen | `find_low_contrast_legal_text` (generischer Kontrast-Scan) |
| 2 | Verständnis-Schwachstellen | `flag_complex_language` (Lesbarkeits-Score) |
| 3 | Entscheidungs-Biases | bestehend (Urgency/Scarcity/Social Proof) + `Decoy Pricing` neu |
| 4 | Erwartungs-Bruch | Popup-Kategorie: X-Button-Funktionstest |
| 5 | Ressourcen-Erschöpfung | Klick-Tiefe-Zählung (Cookie, Kündigung) |
| 6 | Erzwingen/Blockieren | `Forced Path`, `Forced Continuity`, `Roach Motel` |
| 7 | Emotionale Schwachstellen | bestehend (`Confirm Shaming`) |
| 8 | Sucht-Ausnutzung | `find_autoplay_media` + Infinite-Scroll-Check (s.u.) |

**Infinite-Scroll-Check:** Teil von `crawl_site`'s Snapshot-Schritt für Seiten
der Kategorie `product_category`/`other`: Seite 3x scrollen (Playwright
`page.mouse.wheel` oder `page.evaluate("window.scrollBy(...)")`), je 500ms
warten, `document.body.scrollHeight` vor/nach vergleichen. Wächst die Höhe bei
jedem Scroll weiter ohne Ende-Indikator (kein "Keine weiteren Ergebnisse"-Text
o.ä.), Finding `"Exploiting Addiction (Infinite Scroll)"`.

## Explizit außerhalb des Scopes

- **Longitudinale/Multi-Session-Effekte** (kommt der Banner nach Tagen
  wieder, sinkt die Klickrate über Zeit): bräuchte wiederholte Scans über
  Tage/Wochen — eigenes zukünftiges Feature (geplanter Re-Crawl + Diff),
  nicht Teil dieses Plans.
- **Kausaler Wirksamkeitsnachweis** (dass ein Pattern die Konversion um X%
  steigert): nicht durch einen Crawler beweisbar. Das System zitiert
  stattdessen die im Buch genannten Studien (Nouwens et al., SERNAC,
  TurboTax-0,55%-Fall) als unterstützende Evidenz im Report-Text — das ist
  bereits durch `fetch_citation`/den PDF-Report abgedeckt, keine neue Arbeit.
- **Geschäftsabsicht/Intent** (wusste der Product Manager davon): nicht aus
  dem Artefakt ableitbar, bleibt Report-Prosa.
- **Login-gated Content** (Kündigungsstrecken hinter echtem Login): der
  Crawler erreicht nur den unauthentifizierten Kündigungs-Einstiegspunkt.
  Test-Credentials sind ein mögliches späteres Feature, nicht Teil dieses Plans.
- **Buch-Teil-3-Typen** (Privacy Zuckering, Friend Spam, weitere Roach-Motel-
  Subtypen): nicht im vorliegenden Buchauszug enthalten (Free Sample endet
  nach Kapitel 7), daher keine Grundlage für Prompts/Few-Shots — spätere
  Ergänzung möglich, wenn mehr Buchmaterial vorliegt.
- **Decoy Pricing als Preisvergleichs-Heuristik**: nur einfache
  Strukturextraktion (Anzahl Preis-/Plan-Elemente + LLM-Bewertung, ob eine
  Option eine andere dominiert) — keine echte ökonomische Modellierung.

## Kosten & Sicherheit

- `max_pages` konfigurierbar, Default 15 (Env-Var `MAX_PAGES_PER_SCAN`).
- Bis zu 3 LLM-Calls/Seite × `max_pages` — bei Default bis zu 45 Calls/Scan.
- Jeder entdeckte Link läuft durch `validate_scan_url` vor dem Navigieren.
- Ein Site-Scan blockiert weiterhin die anfragende HTTP-Verbindung
  (`await run_site_scan(...)` in der Route) — bereits bekannte, ungelöste
  Einschränkung aus der letzten Review (kein Hintergrund-Job-System). Bei
  `max_pages=15` und mehreren LLM-Calls/Seite kann ein Scan mehrere Minuten
  dauern; das ist für den Hackathon-Rahmen akzeptiert, aber hier explizit
  benannt statt stillschweigend vorausgesetzt.

## Tests

Neue Mehrseiten-Fixture unter `tests/fixtures/` (analog zu
`tests/fixtures/sample_page.html`): ein minimaler Fake-Shop mit Startseite,
Produktseite, Warenkorb, Checkout (2 Schritte, mit Trick-Question-Checkbox-
Paar und einem Preis, der sich zwischen den Schritten ändert), Account-Seite
mit vergrabenem Kündigungslink (3 Klicks tief, ein Schritt mit Nagging-Dialog),
und einem Popup mit funktionslosem X-Button. Alle als lokale `data:`/`file://`-
URLs, keine echten Sites in Tests (bestehendes Muster).

Jede neue Funktion (`discover_links`, `classify_page_category`,
`find_trick_questions`, `find_autoplay_media`,
`find_low_contrast_legal_text`, `flag_complex_language`) bekommt eigene
Unit-Tests nach TDD, wie der Rest der Codebase. `crawl_site`/`run_site_scan`
bekommen Integrationstests gegen die Mehrseiten-Fixture (echter Playwright-
Browser, wie `tests/test_crawler.py` es bereits tut).

## Migrations-Hinweis

Kein SQLite-Migrationssystem vorhanden (Vor-Produktions-Stand, siehe
bestehende `CREATE TABLE IF NOT EXISTS`-Konvention). Die neue `pages`-Tabelle
und `findings.page_id`-Spalte werden über `ALTER TABLE findings ADD COLUMN
page_id INTEGER REFERENCES pages(id)` im bestehenden `SCHEMA`-String in
`app/db.py` ergänzt — `ALTER TABLE ADD COLUMN` ist in SQLite idempotent-sicher
zu handhaben, solange geprüft wird, ob die Spalte schon existiert (z.B. via
`PRAGMA table_info`), da `ALTER TABLE ... ADD COLUMN` bei erneutem Ausführen
sonst einen Fehler wirft (anders als `CREATE TABLE IF NOT EXISTS`). Für
lokale Entwicklungs-DBs reicht alternativ: alte `data/monitor.db` löschen,
Schema läuft beim nächsten Start frisch durch — im Hackathon-Kontext
ausreichend, aber die idempotente Variante ist die sauberere Wahl für
`app/db.py:SCHEMA`/`init_db`.
