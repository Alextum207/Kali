# Kali – Chrome Extension (Prototyp)

Manifest V3, vanilla JS, kein Build-Step. Startet einen Kali-Scan der
aktuell aktiven Tab-URL und übergibt deren Cookies ans Backend
(Cookie-Handoff statt Extension-seitigem Crawl — Design siehe
`docs/superpowers/specs/2026-08-20-chrome-extension-cookie-handoff-design.md`).

## Laden als "Entpackte Erweiterung"

1. Chrome öffnen, `chrome://extensions` aufrufen.
2. "Entwicklermodus" oben rechts aktivieren.
3. "Entpackte Erweiterung laden" klicken und diesen `extension/`-Ordner
   auswählen.
4. Kali-Icon in der Toolbar öffnet das Popup mit "Scan starten".

## Status

- **Backend-Endpoint fehlt noch:** `POST /scans/extension` existiert nicht
  in `app/main.py`. `background.js` ruft aktuell
  `http://localhost:8000/scans/extension` als Platzhalter auf und zeigt im
  Popup einen Fehlerstatus, solange der Endpoint nicht existiert. Siehe
  TODO-Kommentare in `background.js`/`popup.js` für den erwarteten Contract.
- **Icons fehlen:** Das Manifest kommt ohne `icons`-Feld aus, Chrome zeigt
  ein generiertes Platzhalter-Icon. Für ein echtes Icon `icons/`-Ordner mit
  z.B. `icon16.png`/`icon48.png`/`icon128.png` anlegen und im Manifest unter
  `"icons"` sowie `action.default_icon` referenzieren.
