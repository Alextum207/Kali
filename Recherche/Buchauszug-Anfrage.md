# Anfrage: Buchauszug für Kategorie-Strategien (Ansatz A)

## Kontext

Der Dark-Pattern-Monitor bekommt einen Site-weiten Crawler, der jede besuchte
Seite einer von 5 Kategorien zuordnet und je Kategorie eine eigene
Interaktions- und Erkennungs-Strategie fährt (siehe Brainstorming-Verlauf,
Ansatz A):

1. Cookie- & Consent-Banner
2. Checkout- & Bezahlprozesse (E-Commerce)
3. Produktdetail- & Kategorieseiten
4. Account-Verwaltung & Kündigungsstrecken (Subscriptions)
5. Pop-ups, Overlays & Lead-Formulare

Diese Datei listet **exakt**, welche Informationen aus dem Buch pro Kategorie
gebraucht werden, damit daraus (a) die LLM-Prompts für den
Interaktions-Agenten, (b) neue/erweiterte Einträge in `NORM_MAP`
(`app/compliance.py`) und (c) Few-Shot-Beispiele (wie `data/mathur_examples.json`)
gebaut werden können. Bitte pro Kategorie in der unten stehenden Struktur
zusammenfassen — je konkreter (wörtliche Beispielformulierungen, konkrete
UI-Beschreibungen), desto direkter verwertbar.

## Bereits im System vorhandene Pattern-Typen (zur Einordnung, nicht duplizieren)

Diese existieren schon und brauchen aus dem Buch nur dann etwas, wenn das
Buch eine **abweichende Definition, neue Sub-Varianten oder bessere
Erkennungssignale** dafür liefert:

- Fake Urgency / Fake Scarcity / Fake Social Proof
- Confirm Shaming
- Sneaking / Hidden Costs
- Pre-ticked Box
- Visuelle Asymmetrie (Button-Kontrast/-Größe)

Alles, was im Buch als **eigenständiger, hier noch nicht abgedeckter
Pattern-Typ** auftaucht (z.B. "Roach Motel", "Forced Continuity", "Trick
Questions", "Nagging", "Obstruction", "Privacy Zuckering", o.ä. — je nachdem
welche Taxonomie das Buch verwendet), bitte **explizit als neuen Typ**
aufführen, nicht unter eine bestehende Kategorie zwängen.

---

## Pro Kategorie benötigt: diese 6 Punkte

Für **jede** der 5 Kategorien oben, bitte getrennt beantworten:

### 1. Pattern-Taxonomie
Welche im Buch benannten Dark-Pattern-Typen kommen in dieser Kategorie
typischerweise vor? Name (Original-Begriff des Buchs + ggf. deutsche
Entsprechung) + 1-2 Satz Definition.

### 2. Konkrete Erkennungssignale
Wie erkennt man das Pattern in der Praxis? Bitte so konkret wie möglich:
- **Text-Signale:** wörtliche Beispielformulierungen aus dem Buch (Zitate,
  auch übersetzt/paraphrasiert wenn nötig) — diese werden direkt als
  Few-Shot-Beispiele fürs LLM verwendet, ähnlich wie:
  `{"text": "Only 2 items left in stock, order now!", "pattern_type": "Fake Urgency"}`
- **UI/Visuelle Signale:** beschreibt das Buch visuelle Merkmale (Button-Größe,
  Farbkontrast, Platzierung, Countdown-Timer, versteckte/kleine Schrift,
  vorausgewählte Optionen)?
- **Struktur-/Flow-Signale:** braucht es mehrere Schritte, um das Pattern zu
  erkennen (z.B. "Preis ändert sich erst im letzten Checkout-Schritt", "Kündigen
  erfordert Anruf statt Self-Service-Button")?

### 3. Navigations-/Interaktionsziel
Was muss der Crawler auf einer Seite dieser Kategorie tun, um das Pattern
überhaupt sichtbar zu machen? (Beispiel: Um versteckte Kosten zu finden, muss
man bis zum letzten Checkout-Schritt vor der Zahlung durchklicken, nicht bloß
die Produktseite ansehen.) Beschreibt das Buch typische Nutzer-Journeys, in
denen die jeweiligen Patterns auftreten?

### 4. Schweregrad / Rechtlicher Bezug
Ordnet das Buch die Patterns nach Schweregrad ein (z.B. "aggressiv" vs.
"grenzwertig")? Nennt es Rechtsrahmen oder Regulierungsbezüge (auch
nicht-deutsche wie GDPR/CCPA/FTC-Fälle) — auch wenn es keine deutschen
Normen sind, hilft das bei der Einordnung, welche der bestehenden Normen
(UWG, BGB §312j, DSA Art. 25, DSGVO, PAngV — siehe `app/compliance.py`)
am besten passen, bzw. ob eine Ergänzung nötig ist.

### 5. Bekannte Beispiele / Fallstudien
Nennt das Buch konkrete Firmen/Screenshots/Fallstudien für diese Kategorie
(auch wenn die Firma nicht direkt mit unseren Test-Sites übereinstimmt)?
Diese helfen, die Erkennungs-Prompts realitätsnah zu kalibrieren.

### 6. Confidence-Hinweise
Gibt das Buch Hinweise, wann ein Pattern eindeutig vs. mehrdeutig ist (z.B.
"ein einzelner vorausgewählter Haken ist meist harmlos, drei+ sind
verdächtig")? Das fließt in `confidence_score` (0.0–1.0) ein.

---

## Zusätzlich (kategorie-übergreifend, einmalig)

- **Allgemeine Taxonomie-Übersicht:** Falls das Buch ein Gesamtschema hat
  (z.B. Brignull'sche Kategorien: Sneaking, Urgency, Misdirection, Social
  Proof, Scarcity, Obstruction, Forced Action, Nagging) — bitte als Liste
  mit Kurzdefinition, unabhängig von den 5 Site-Kategorien oben. Das dient
  als Vokabular-Referenz, damit LLM-Prompt-Enum und `NORM_MAP`-Keys
  konsistent benannt werden (siehe bereits behobener Bug: LLM-Prompt nutzte
  `"Sneaking / Hidden Costs"`, `NORM_MAP` hatte nur `"Hidden Costs"` — genau
  solche Namensabweichungen sollen mit klarer Taxonomie vermieden werden).
- **Erkennungs-/Automatisierungs-Hinweise:** Erwähnt das Buch irgendetwas zu
  automatisierter/technischer Erkennung von Dark Patterns (auch nur am
  Rande)? Falls ja, bitte zitieren — auch wenn es nur ein Nebensatz ist.
- **Abgrenzung "Dark Pattern" vs. "guter Verkaufstrick":** Zieht das Buch
  eine Grenze, ab wann eine UX-Entscheidung manipulativ statt nur clever ist?
  Diese Grenze bestimmt direkt, wie aggressiv/vorsichtig der Erkennungs-Prompt
  kalibriert werden sollte (zu aggressiv = viele False Positives, was für ein
  Tool mit Rechtsanspruch riskant ist).

## Format der Antwort

Bitte pro Kategorie einen eigenen Abschnitt (`## 1. Cookie- & Consent-Banner`
usw.), darin die 6 Punkte als Unterüberschriften. Muss keine Fließtext-Prosa
sein — Stichpunkte/Listen sind bevorzugt, da das direkt in Prompts und
JSON-Beispieldaten übersetzt wird. Wörtliche Zitate bitte in Anführungszeichen
kennzeichnen (Original-Formulierung wichtiger als elegante Paraphrase).
