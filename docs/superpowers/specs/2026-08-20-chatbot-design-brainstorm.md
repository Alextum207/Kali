# Brainstorm: Findings-Chatbot auf Basis von Crawl-Ergebnissen + Rechtsdatenbank

Status: **Brainstorm, Kernentscheidungen getroffen (siehe Abschnitt 6).** Ziel
war eine Entscheidungsgrundlage, keine Implementierung — das ist weiterhin
kein Umsetzungsplan.

## 1. Nutzenversprechen

Primäre Nutzer: **Verbraucherzentrale-Sachbearbeiter:innen** und ggf.
**Aufsichtsbehörden**, die einen abgeschlossenen Scan prüfen und die Funde für
ein Prüfverfahren einordnen müssen. Kein Endverbraucher-Chatbot.

Typische Fragen, die der Chatbot beantworten soll:
- "Warum ist X (Finding #12) ein Dark Pattern?" — Erklärung anhand von
  `pattern_type` + `evidence_data`.
- "Welche Norm greift hier?" — Auflösung über `target_norm` /
  `NORM_MAP` + Volltext aus `legal-text-mcp-de`.
- "Zeig mir alle Fake-Urgency-Funde bei diesem Scan." — Filter/Aggregation
  über `findings`.
- "Wie sicher ist der Fund?" — `confidence_score` einordnen, ggf. Warum
  (Co-occurrence-Boost, Quelle: Heuristik vs. LLM-Klassifikator).
- Vergleichsfragen über mehrere Scans hinweg ("Hat sich seit dem letzten Scan
  etwas geändert?") — nur relevant, falls Scope über einen einzelnen Scan
  hinausgeht (siehe offene Frage 5.1).

Der Chatbot ersetzt keine juristische Bewertung, sondern liefert
**Orientierung + Nachvollziehbarkeit** für Menschen, die den PDF-Report/die
Rohdaten ohnehin vor sich haben.

## 2. Datenquellen

Aus `app/db.py`:
- `scans` (id, url, started_at) — Scope-Anker für eine Konversation.
- `pages` (id, scan_id, url, category, crawled_at) — Kontext, auf welcher
  Unterseite ein Finding auftrat (`category` z.B. `checkout_payment`,
  `account_subscription`).
- `findings` (id, scan_id, page_id, pattern_type, target_norm,
  confidence_score, evidence_json, created_at) — die Kernentität für
  Chat-Antworten. `evidence_json` enthält je nach Erkennungsstufe
  unterschiedliche Felder (z.B. `quote` bei LLM-Funden aus
  `llm_classify.py`, Screenshot-Hashes/Farbwerte bei visuellen Heuristiken).

Normtexte: `app/compliance.py` bietet bereits `map_to_norm()` (statisches
`NORM_MAP`) und `fetch_citation(norm, base_url)` gegen `legal-text-mcp-de`
(`/search`-Endpoint, liefert `results[0].norm.text`). Der Chatbot könnte
denselben Client wiederverwenden, um bei Bedarf den vollen Gesetzestext
nachzuladen, statt nur den Normverweis zu zitieren.

Zwei Kontext-Ebenen, die sich klar trennen lassen:
1. **Strukturierte Fakten** (DB-Rows) — exakt, keine Halluzinationsgefahr,
   sollte immer als Tool-Ergebnis/Prompt-Fakt eingespeist werden statt vom
   Modell "erinnert".
2. **Normtext-Erklärung** — Freitext aus `legal-text-mcp-de`, ggf. lang;
   eignet sich für Embedding/RAG, muss aber nicht, da der Normkatalog klein
   und über `NORM_MAP` bereits vorstrukturiert ist (aktuell 8 distincte
   Normen für alle `pattern_type`).

## 3. Architekturoptionen

### a) Tool-Use / Function-Calling gegen bestehende DB-Queries
Claude bekommt Function-Definitionen wie `get_findings(scan_id, pattern_type=None)`,
`get_page_findings(page_id)`, `fetch_citation(norm)` — direkte Wrapper um
bestehende `app/db.py`- und `app/compliance.py`-Funktionen. Keine neue
Persistenzschicht.

- Vor: Kleinster Diff, nutzt 1:1 vorhandenen Code, immer aktuelle Daten,
  keine Sync-Probleme, gut nachvollziehbar (jede Antwort lässt sich auf einen
  konkreten Tool-Call zurückführen — wichtig für Beweisfestigkeit).
- Nach: Bei sehr vielen Findings/Scans mehrere Tool-Roundtrips nötig,
  Modell muss "wissen", wonach es fragen soll (Prompt-Engineering-Aufwand
  für gute Function-Auswahl); kein Volltext-Fuzzy-Match über Evidence-Text.

### b) RAG über Findings + Normtexte mit Embeddings/Vektor-Store
Alle Findings (inkl. `evidence_data`) und Normtexte werden vorab embedded und
in einem Vektor-Store abgelegt; Chat-Anfragen holen sich per Similarity-Search
relevante Snippets.

- Vor: Skaliert auf viele Scans/Findings, erlaubt unscharfe/semantische
  Fragen ("Seiten mit ähnlichen Mustern wie ..."), Normtext-Suche über
  Bedeutung statt nur `pattern_type`-Mapping.
- Nach: Neue Infrastruktur (Vektor-DB, Embedding-Pipeline, Reindexierung bei
  neuen Scans), Overkill für die aktuelle Datenmenge (Findings pro Scan
  vermutlich niedrig zweistellig), zusätzliche Fehlerquelle/Wartungslast in
  einem Hackathon-/Prototyp-Kontext.

### c) Reiner Prompt-Ansatz (kompletter Scan-Kontext im Prompt)
Alle `pages` + `findings` eines Scans werden als strukturierter Text/JSON in
den System- oder User-Prompt gepackt, keine Tool-Calls, kein Retrieval.

- Vor: Keinerlei Zusatzinfrastruktur, einfachste Umsetzung, funktioniert gut
  für einen einzelnen, überschaubaren Scan (analog zu `classify_text` in
  `llm_classify.py`, das auch nur Text direkt in den Prompt gibt).
- Nach: Skaliert nicht über mehrere/große Scans (Kontextfenster-Limit,
  Kosten pro Nachricht steigen mit Scan-Größe), kein sauberer Weg für
  Cross-Scan-Fragen, Normtext-Volltext müsste ebenfalls komplett mitgegeben
  werden statt gezielt nachgeladen zu werden.

Zwischenform denkbar: (c) als Startpunkt, (a) als Fallback-Tool für
"hol mir mehr Details/den Normtext", falls der initiale Prompt-Kontext nicht
reicht — vermeidet Vektor-Store, bleibt aber flexibel.

## 4. UI-Integration (Idee, keine Implementierung)

- `app/main.py` hat bereits `GET /scans/{scan_id}` (`scan_detail.html`) und
  `GET /scans/{scan_id}/pages/{page_id}` (`page_detail.html`) — natürliche
  Stellen für ein Chat-Widget mit `scan_id`/`page_id` als impliziten
  Kontext-Filter.
- Denkbar: neue Route `POST /scans/{scan_id}/chat` (oder WebSocket für
  Streaming), die serverseitig den gewählten Architektur-Ansatz (a/b/c)
  kapselt und in `scan_detail.html`/`page_detail.html` per einfachem
  JS-Fetch angebunden wird — kein neues Frontend-Framework nötig, passt zum
  bestehenden Jinja2/FastAPI-Stack.
- Alternativ ein eigenständiger Chat-Tab pro Scan statt eines Sidebar-Widgets,
  falls Konversationen länger werden sollen.

## 5. Offene Fragen für den Nutzer

1. **Scope**: Chat nur pro Einzel-Scan (Kontext = ein `scan_id`) oder auch
   scan-übergreifend/historisch (z.B. "wie hat sich Anbieter X über Zeit
   entwickelt")? Bestimmt maßgeblich, ob Option (c) reicht oder (a)/(b)
   nötig wird.
2. **Live-API-Calls pro Chat-Nachricht ok?** Kosten/Latenz-Implikation, vor
   allem falls pro Nachricht auch `fetch_citation()`-Nachschlagen gegen
   `legal-text-mcp-de` läuft. Caching der Normtexte sinnvoll?
3. **Rechtsberatungs-Grenze**: Chatbot darf keine Rechtsberatung im
   rechtlichen Sinne leisten, nur Einordnung/Hinweise liefern — braucht es
   einen expliziten Disclaimer im System-Prompt und/oder UI-Hinweis? Wer
   verantwortet die Formulierung (Rechtsteam einbinden)?
4. **Antwort-Vertrauenswürdigkeit/Beweisfestigkeit**: Da Kali Funde
   "gerichtsfest" dokumentieren soll — muss jede Chat-Antwort ihre Quelle
   (welches Finding/welcher Normtext) explizit zitieren, damit sie selbst
   nicht als unbelegte Behauptung im Verfahren auffällt?
5. **Persistenz von Chat-Verläufen**: Werden Konversationen gespeichert (neue
   Tabelle?) oder sind sie rein session-/anfragebasiert und verschwinden nach
   Seitenwechsel?

## 6. Entscheidungen (2026-08-20)

1. **Scope: nur ein Scan, kein Cross-Scan/Historie.** Kontext-Anker ist immer
   genau die `scan_id` des gerade abgeschlossenen Scans, auf dessen
   Detailseite der Nutzer ohnehin landet. Cross-Scan-Vergleiche (Frage 5.1,
   letzter Punkt in Abschnitt 1) sind explizit "später, wenn der Kern läuft".
   → Reduziert den Kontextumfang genug, dass Option (c) (reiner Prompt-Ansatz,
   kompletter Scan-Kontext im Prompt) als Startpunkt ausreicht; Option (a)
   als Fallback-Tool für "hol mir mehr Details" bleibt sinnvoll, (b) RAG ist
   damit vom Tisch.
2. **Live-API-Calls pro Nachricht: ja, aber mit Zitat-Cache.** Normzitate, die
   während des Scans bereits über `fetch_citation()` geholt wurden, liegen
   schon in `evidence_data` der Findings und werden **wiederverwendet statt
   pro Chat-Nachricht neu von `legal-text-mcp-de` geholt**. Ein frischer Call
   gegen `legal-text-mcp-de` passiert nur **on-demand**, wenn der Nutzer
   explizit nach einer Norm fragt, die noch nicht im Kontext vorhanden ist —
   kein pauschaler Call bei jeder Nachricht.
3. **Disclaimer ist Pflicht, nicht optional**, und gehört **fest in den
   System-Prompt**, nicht nur als UI-Text (der wegscrollt/ignoriert werden
   kann). Begründung: Kali richtet sich an Verbraucherzentralen/
   Aufsichtsbehörden — ein Chatbot, der wie Rechtsberatung wirkt, ist ein
   Reputations- und ggf. Rechtsrisiko (RDG). Formulierungsrichtung: Bot
   ordnet nur ein ("erkanntes Muster X, zugeordnet zu Norm Y") und verweist
   explizit auf "keine Rechtsberatung, für eine rechtsverbindliche
   Einschätzung an Verbraucherzentrale/Anwalt wenden".

4. **Quellenpflicht: ja.** Jede Chat-Antwort muss das konkrete Finding
   (Finding-ID) und/oder den Normtext benennen, aus dem sie stammt — passt
   zum "gerichtsfest"-Anspruch von Kali; eine unbelegte Antwort wäre selbst
   eine Behauptung ohne Beleg. Praktisch: die Function-Call-Ergebnisse
   (Option a) liefern Finding-IDs/Normverweise, die das Modell im Antworttext
   zitieren muss (System-Prompt-Anforderung, analog zum Disclaimer in Punkt 3).
5. **Persistenz: keine (MVP).** Chat-Verläufe sind rein session-/
   anfragebasiert, keine neue DB-Tabelle — verschwinden bei Seitenwechsel/
   Reload. Aufrüstbar später, falls Nutzer:innen das brauchen.

Status: **alle offenen Fragen entschieden, bereit für Umsetzungsplan.**
