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

- **Backend-Endpoint vorhanden:** `POST /scans/extension` existiert jetzt
  in `app/main.py`.
