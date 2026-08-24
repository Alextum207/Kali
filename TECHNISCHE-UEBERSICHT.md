# Kali — Technische Statusübersicht

Stand: 2026-08-24

## 1. Was in der Extension noch fehlt

| Lücke | Status/Grund |
|---|---|
| **PDF-Report erfasst nur den Top-Frame** | `getReportData` ist jetzt bewusst mit `{frameId: 0}` gescoped. Funde aus iframes werden auf der Seite korrekt umrandet und im Popup-Zähler mitgezählt, tauchen aber **nicht** im PDF auf. Um das zu schließen bräuchte es die Permission `webNavigation` (`chrome.webNavigation.getAllFrames`) oder `scripting`, um alle Frame-IDs eines Tabs abzufragen und `getReportData` gezielt an jede zu schicken — bewusst nicht gemacht, da das eine sichtbare neue Berechtigung beim Extension-Install wäre. |
| **Kein automatisiertes JS-Test-Setup** | Alles bisher nur manuell verifiziert (`chrome://extensions` neu laden) oder über isolierte Node-Skripte während der Entwicklung. Kein CI, kein Headless-Browser-Test-Runner für die Extension. |
| **Kein Rate-Limiting beim Redo/MutationObserver** | Bei sehr dynamischen Seiten (viele DOM-Änderungen/Sekunde) kann `patternHighlighting()` sehr häufig neu triggern — es gibt eine 2s-Wartezeit nach einer Observer-Änderung, aber keinen harten Cooldown/Debounce-Cap. |
| **Kein Login/Session-Handling** | Die Extension scannt nur, was gerade sichtbar im Tab ist — kein Problem, da sie im echten Nutzer-Kontext läuft (Nutzer ist ja eingeloggt), aber es gibt keine Möglichkeit, gezielt "nach dem Login" oder "nach 3 Klicks" automatisch nachzuscannen; jeder Schritt braucht manuelles Neu-Triggern (Redo-Button oder MutationObserver-Zufallstreffer). |
| **Fake-Timer-Reset nicht erkannt** | Ein Scarcity-Countdown, der bei jedem Seiten-Reload wieder auf denselben Wert zurückspringt (klassischer Fake-Countdown-Tell), wird nicht erkannt — die Erkennung prüft nur, ob der Timer *innerhalb eines Ladevorgangs* runterzählt, nicht den Wert *über mehrere Besuche hinweg* (bräuchte `chrome.storage.local`-Historie pro Domain, nicht gebaut). |

## 2. Anforderungen an den Web-Scraper (URL rein → Seite + Unterseiten durchsuchen)

**Bereits erfüllt** (`app/site_crawler.py::crawl_site`):
- Eine Start-URL reicht — BFS/priorisierter Crawl folgt `<a href>`-Links automatisch, bleibt auf Host + Subdomains
- Kategorie-Priorisierung: Checkout/Konto/Produkt-Seiten werden vor generischen Seiten besucht (`TARGET_CATEGORIES`, `_predict_category_from_url`)
- Mehrstufiger Flow-Walk: klickt sich LLM-gesteuert durch echte Abläufe durch (z.B. bis zum letzten Checkout-Schritt vor Zahlung, oder sucht einen Kündigungslink) statt nur einzelne Seiten zu laden
- Zeit-Budget (`SCAN_TIME_BUDGET_SECONDS`) + `max_pages`-Deckel als Notbremsen
- SSRF-Schutz (`app/url_safety.py`): blockt private IPs, Cloud-Metadata, `file://` etc.
- CAPTCHA-Erkennung mit sauberem Abbruch (`CaptchaRequiredError`)
- Cookie-Consent wird vor jedem Snapshot automatisiert behandelt (Consent-O-Matic-Regeln)

**Fehlende Anforderungen für einen vollständigeren Scraper:**

| Fehlt | Warum das relevant wäre |
|---|---|
| **Kein `robots.txt`-Respekt** | Aktuell wird jede erlaubte URL gecrawlt, unabhängig von `Disallow`-Regeln — rechtlich/ethisch für einen produktiven Marktbeobachtungs-Crawler eigentlich Pflicht. |
| **Kein Rate-Limiting/Crawl-Delay** | Der Crawler feuert Requests so schnell wie Playwright sie abarbeitet, ohne Pause zwischen Seiten — Risiko, als Angriffs-Traffic geblockt zu werden oder eine kleine Seite zu überlasten. |
| **Kein Login/Auth-Flow** | Viele Dark Patterns (echte Kündigungs-Flows, personalisierte Rabatt-Timer, Account-Löschung) liegen hinter einem Login — der Crawler kommt nur an öffentlich erreichbare Seiten. Bräuchte Credential-Handling + Playwright `storage_state` (Session-Cookies vorab injizieren). |
| **Keine `sitemap.xml`-Nutzung** | Nur `<a href>`-Links werden gefunden — Seiten, die nur über eine Sitemap oder JS-generierte Navigation (ohne echte `<a>`-Tags, z.B. reine `onClick`-Router-Links in SPAs) erreichbar sind, werden übersehen. |
| **Keine Pagination-Erkennung** | Ein "Nächste Seite"-Button in einer Produktliste wird wie jeder andere Link behandelt (nicht priorisiert/spezialbehandelt) — bei sehr langen Katalogen kann das Budget vor relevanten Unterseiten aufgebraucht sein. |
| **Kein Resume/Checkpointing** | Bricht ein Scan (Timeout, Absturz) mitten im Crawl ab, ist der Fortschritt weg — kein persistenter Warteschlangen-State, der einen Scan fortsetzen könnte. |
| **Kein Multi-Domain-Following** | Bewusste Scope-Grenze (nur Start-Host + Subdomains) — für Fälle, wo der eigentliche Checkout auf einer *anderen* Domain läuft (z.B. Payment-Provider), folgt der Crawler dem nicht. |

## 3. Nicht erkennbare Dark Patterns — Extension vs. Programm

| Pattern | Extension | Programm (Python) | Warum nicht |
|---|---|---|---|
| **Confirm Shaming** | ❌ | ✅ (LLM) | Reine Tonalität/Wortwahl ("Nein, ich hasse es zu sparen") — keine feste Regex möglich, braucht Sprachverständnis. Extension macht bewusst keine LLM-/Backend-Calls, bleibt offline-fähig. |
| **Sneaking / Hidden Costs** | ❌ | ✅ (LLM) | Kontextabhängig: eine Gebühr ist nur "versteckt", wenn sie *unerwartet spät* auftaucht — das ist eine Bewertung, kein Textmuster. |
| **Nagging** | ❌ | ✅ (LLM) | Braucht wiederholte Aufforderungen *über mehrere Interaktionen/Sitzungen hinweg* — ein Einzel-Snapshot (Extension) oder Einzel-Scan (Programm) sieht das nur, wenn die LLM-Klassifikation die Sprache eines einzelnen Popups als "nagging-artig" erkennt; echte Wiederholung über Zeit wird von keinem der beiden Systeme getrackt. |
| **Roach Motel** | ❌ | ✅ (LLM) | Bräuchte den *kompletten* Kündigungs-Flow bis zum Ende, um "leicht rein, schwer raus" zu beweisen — das Programm kommt über den Flow-Walk zumindest bis zum Kündigungslink, bewertet die *Schwierigkeit* aber nur sprachlich (LLM), nicht durch tatsächliches Durchklicken bis zum Abschluss. |
| **Forced Path** | ❌ | ✅ (LLM) | Unnötige Zwischenschritte erkennen heißt bewerten, was "unnötig" ist — subjektiv, nur LLM-fähig. |
| **Nagging/nicht-strukturelle Decoy Pricing** | ❌ | ✅ (LLM, zusätzlich zur strukturellen Heuristik) | Decoy Pricing hat zwar auch eine deterministische Heuristik (`find_decoy_pricing`, Preiskarten-Vergleich), aber nur für Karten mit `<ul>/<ol>`-Value-Liste nebeneinander; textlich/anders layoutete Varianten laufen nur über die LLM-Erkennung. |
| **Cookie Wall** (Inhalt komplett hinter Consent gesperrt) | ❌ | ✅ (seit 2026-08-24, `app/crawler.py::_detect_cookie_wall`) | Python prüft jetzt zusätzlich zum fehlenden Reject-Button, ob `overflow: hidden` auf `body`/`html` gesetzt ist, während ein Consent-Banner sichtbar ist — getrennter Pattern-Typ `Cookie Wall`, rein passiv (keine automatische Zustimmung/Ablehnung). Nur ein einfacher CSS-Check, keine Blur-/Scroll-Höhen-Analyse. Extension-Pendant noch nicht gebaut (Submission-Safe-Scope, Python-only). |
| **Bait-and-Switch** (Werbepreis ≠ tatsächlicher Preis nach Klick) | ❌ | ❌ | Braucht einen Vergleich zwischen einer *externen* Quelle (Anzeige, Google-Suchergebnis) und der tatsächlichen Zielseite — außerhalb dessen, was ein Crawl einer einzelnen Domain oder eine Extension auf einer offenen Seite sehen kann. |
| **Allgemeine Misdirection** (visuell untergeordnete wichtige Info, außerhalb von Cookie-Banner/Rechtstext) | ❌ | ⚠️ nur 2 Spezialfälle | Nur für Cookie-Banner-Buttons (Visuelle Asymmetrie) und Rechtstext-Kontrast (Visuelle Tarnung) implementiert — ein generischer "ist irgendwo auf der Seite eine wichtige Ablehn-Option klein/grau versteckt"-Check existiert nicht, das wäre ein Full-Page-Salienz-Vergleich, nicht gebaut. |
| **Privacy Zuckering** (Bündel-Consent über eine einzige "Alles akzeptieren"-UI ohne Checkbox-Granularität) | ❌ | ❌ | Überschneidet sich konzeptionell mit Pre-ticked Box, aber wenn die Bündelung *keine* Checkbox nutzt (z.B. ein einziger großer Toggle für mehrere Datennutzungszwecke), gibt es kein Element, das die bestehende Checkbox-Heuristik greifen könnte. |
| **Fake-Timer-Reset zwischen Besuchen** | ❌ | ❌ | Siehe Abschnitt 1 — beide Systeme sehen nur den Countdown *innerhalb eines* Ladevorgangs, nicht über mehrere Besuche/Scans hinweg. |
| **Drip Pricing über den ganzen Checkout-Flow** (Preis wird erst im letzten Schritt sichtbar erhöht) | ❌ | ⚠️ nur indirekt über Sneaking/Hidden-Costs (LLM) | Keine dedizierte Heuristik, die den beworbenen Startpreis mit dem tatsächlichen Endpreis am Checkout-Ende strukturell vergleicht — nur die generische LLM-Textklassifikation kann das zufällig auffangen, wenn die Formulierung eindeutig genug ist. |

**Kurzfassung des Kernmusters:** Alles, was **reine Tonalität, mehrseitige/mehrsitzungs-Historie oder subjektive Bewertung** braucht, läuft ausschließlich über die LLM-Klassifikation im Python-Programm — und ist damit in der Extension **grundsätzlich und bewusst** nicht erreichbar (kein Backend-Call gewollt). Alles, was **strukturell/visuell in einem einzelnen DOM-Snapshot** erkennbar ist, haben beide Systeme parallel (Extension: 10 Typen rein clientseitig; Programm: 18 Typen, davon 12 deterministisch/heuristisch + 6 nur LLM).
