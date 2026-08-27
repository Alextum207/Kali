# Chrome-Extension mit Cookie-Handoff — Design

## Kontext & Ziel

Der Server-Crawler (`app/site_crawler.py`) scannt öffentlich erreichbare
Seiten mit einem frischen, nicht eingeloggten Playwright-Context. Viele
relevante Dark Patterns tauchen aber erst hinter Login/Consent auf
(Kündigungs-Flows im Kundenkonto, personalisierte Preise, bereits gesetzter
Cookie-Consent). Eine Chrome-Extension, die im Browser des Nutzers läuft, hat
Zugriff auf genau diesen Zustand — die aktuell aktive Tab-Session inkl.
Cookies.

**Entscheidung:** Die Extension crawlt nicht selbst. Sie liest nur die
Cookies der aktiven Site aus und übergibt sie an das bestehende Backend, das
den eigentlichen Scan mit dem bestehenden `app/scan.py`/`app/site_crawler.py`
weiterhin server-seitig per Playwright durchführt — nur eben mit einem
Browser-Context, dem die übergebenen Cookies injiziert wurden
(`context.add_cookies(...)`, Playwright-API, hier nicht implementiert, siehe
Offene Punkte). Das hält die Kernbausteine (Scraper/Analyse/DB/Reporting)
unangetastet und entkoppelt — die Extension ist nur ein zusätzlicher
Cookie-Lieferant vor der bestehenden Pipeline, kein zweiter Crawler.

## Message-Flow

```
┌─────────────┐   1. "Scan starten" Klick    ┌──────────────────────┐
│  popup.html/ │ ────────────────────────────▶│  background.js       │
│  popup.js    │  chrome.runtime.sendMessage   │  (Service Worker)    │
│              │  { type: "START_SCAN",        │                      │
│              │    url: <aktive Tab-URL> }    │                      │
└──────────────┘                               └──────────┬───────────┘
       ▲                                                   │
       │ 4. Status-Update                                  │ 2. chrome.cookies.getAll
       │ (chrome.storage.onChanged                         │    ({ url: <Tab-URL> })
       │  oder direkte Response)                            ▼
       │                                        ┌──────────────────────┐
       │                                        │ Cookies der aktiven  │
       │                                        │ Tab-Domain           │
       │                                        └──────────┬───────────┘
       │                                                   │ 3. fetch()
       │                                                   ▼
       │                                        ┌──────────────────────┐
       └────────────────────────────────────────│ POST /scans/extension│
                                                  │ (TODO: existiert     │
                                                  │  noch nicht)         │
                                                  │ Body: { url,         │
                                                  │  cookies: [...] }    │
                                                  └──────────────────────┘
```

1. Popup liest `chrome.tabs.query({active, currentWindow: true})` für die
   aktuelle Tab-URL und schickt `START_SCAN` per `chrome.runtime.sendMessage`
   an den Background-Service-Worker.
2. Background liest per `chrome.cookies.getAll({ url })` alle Cookies der
   aktiven Site (erfordert `cookies`-Permission + passende
   `host_permissions`).
3. Background schickt `url` + `cookies` per `fetch()` an
   `POST /scans/extension` (Platzhalter-Endpoint, existiert serverseitig noch
   nicht — siehe Offene Punkte). Erwartete Response: `{ scan_id }` analog zum
   bestehenden `POST /scans`-Flow in `app/main.py`.
4. Background hält den Scan-Status (`idle` / `running` / `done` / `error`,
   plus `scan_id`/`resultUrl` sobald vorhanden) in `chrome.storage.local`.
   Popup liest diesen Status beim Öffnen und abonniert
   `chrome.storage.onChanged`, um den Fortschritt live anzuzeigen, inkl.
   Link zu `/scans/{scan_id}` sobald der Scan gestartet wurde.

## Warum Cookie-Handoff statt Extension-seitigem Crawl

- Der gesamte Analyse-Stack (Modul B/C/D: Visual-Heuristiken,
  Evidence-Hashing, RFC-3161-Zeitstempel, Compliance-Mapping, PDF-Reports)
  ist an den Playwright-Server-Crawler gekoppelt und für gerichtsfeste
  Beweissicherung ausgelegt. Ein zweiter, extension-seitiger Analyse-Pfad
  würde diese Garantien nicht erben und Logik duplizieren.
- Die Extension bleibt dadurch bewusst dünn (nur Cookie-Lesen + HTTP-Call),
  keine Playwright/DOM-Analyse-Logik im Browser nötig.

## Offene Punkte (bewusst nicht Teil dieses Designs)

- **`POST /scans/extension`** existiert noch nicht in `app/main.py`. Muss
  Cookies serverseitig via `context.add_cookies()` in den Playwright-Context
  injizieren, bevor `run_site_scan` läuft. Nicht implementiert, da
  `app/main.py`/`app/scan.py`/`app/site_crawler.py` aktuell parallel für
  Performance-Änderungen bearbeitet werden.
- **Icons** fehlen (nur Platzhalter-Hinweis in `extension/README.md`),
  Manifest kommt ohne `icons`-Feld aus.
- **Auth/CORS** zwischen Extension und Backend ist nicht spezifiziert
  (lokaler Prototyp, kein Deployment-Härtungsschritt in diesem Design).
