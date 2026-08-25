import logging
import os
import sqlite3
import urllib.parse
from contextlib import asynccontextmanager

# Must run before any `app.*` import below — several modules (app.scan,
# app.site_crawler, ...) read os.environ at import time for their own
# defaults (MAX_FLOW_STEPS, LEGAL_TEXT_MCP_BASE_URL, ...). load_dotenv()
# only sets variables not already present in the environment, so an
# explicitly exported/deployment-set env var still wins over .env.
from dotenv import load_dotenv
load_dotenv()

import anthropic
from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright

from app.compliance import EVIDENCE_HINTS, aggregate_risk_score
from app.db import (
    init_db, get_scan, get_findings, get_pages, get_page_findings, list_scans,
    insert_scan, mark_scan_status, set_human_review, list_scans_by_url,
)
from app.robots import RobotsDisallowedError
from app.scan import run_site_scan
from app.url_safety import validate_scan_url

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "./data/monitor.db")
EVIDENCE_DIR = os.environ.get("EVIDENCE_DIR", "./data/evidence")

# Same "construct only if key present" pattern as classify_text's fallback
# in app/analysis/llm_classify.py. None here means local dev/CI without the
# key keeps working exactly as before (category/interaction LLM steps no-op).
_LLM_CLIENT = (
    anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    if os.environ.get("ANTHROPIC_API_KEY")
    else None
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run the schema DDL exactly once at startup, not on every request.
    init_db(DB_PATH).close()

    playwright = await async_playwright().start()
    app.state.playwright = playwright
    app.state.browser = await playwright.chromium.launch()
    try:
        yield
    finally:
        await app.state.browser.close()
        await app.state.playwright.stop()


app = FastAPI(title="Dark-Pattern-Monitor", lifespan=lifespan)

# Read-only JSON API for the separate frontend/ (Vite dev server, default
# port 8080) — the Jinja2 UI above doesn't need this, it's same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:8080")],
    allow_methods=["GET"],
)

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
    name="static",
)


def _get_conn():
    """Per-request DB connection dependency. Opens a fresh lightweight
    connection (no schema re-run) and closes it when the request is done,
    so connections don't leak."""
    # check_same_thread=False: FastAPI may run the sync dependency in a
    # threadpool thread while an async route body executes on the event
    # loop thread — this connection is only ever used within one request.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _attach_display_fields(findings: list[dict], pages: list[dict], scan_url: str) -> list[dict]:
    """Adds page_url (via page_id -> pages.url, falling back to the scan's
    own URL for single-page scans without a page_id) and screenshot_url
    (served through /evidence/<basename>) to each finding, for the
    Link/Screenshot columns in scan_detail.html and report.html."""
    url_by_page_id = {p["id"]: p["url"] for p in pages}
    for f in findings:
        f["page_url"] = url_by_page_id.get(f.get("page_id"), scan_url)
        screenshot_path = f.get("evidence_data", {}).get("screenshot_path")
        f["screenshot_url"] = f"/evidence/{os.path.basename(screenshot_path)}" if screenshot_path else None
    return findings


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, conn: sqlite3.Connection = Depends(_get_conn)):
    scans = list_scans(conn)
    # ponytail: one get_findings() query per scan (N+1) — fine at prototype
    # scale, switch to a single GROUP BY scan_id aggregate query if the scan
    # list grows large enough for this to matter.
    for scan in scans:
        scan["risk"] = aggregate_risk_score(get_findings(conn, scan["id"]))
    return templates.TemplateResponse(request, "dashboard.html", {"scans": scans})


@app.get("/api/scans")
def api_list_scans(conn: sqlite3.Connection = Depends(_get_conn)):
    scans = list_scans(conn)
    for scan in scans:
        scan["risk"] = aggregate_risk_score(get_findings(conn, scan["id"]))
    return scans


@app.get("/api/scans/{scan_id}")
def api_scan_detail(scan_id: int, conn: sqlite3.Connection = Depends(_get_conn)):
    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    pages = get_pages(conn, scan_id)
    findings = _attach_display_fields(get_findings(conn, scan_id), pages, scan["url"])
    scan["risk"] = aggregate_risk_score(findings)
    return {"scan": scan, "pages": pages, "findings": findings}


@app.get("/api/scans/{scan_id}/pages/{page_id}")
def api_page_findings(scan_id: int, page_id: int, conn: sqlite3.Connection = Depends(_get_conn)):
    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    pages = get_pages(conn, scan_id)
    findings = _attach_display_fields(get_page_findings(conn, page_id), pages, scan["url"])
    return {"scan": scan, "findings": findings}


@app.get("/evidence/{filename}")
def evidence_file(filename: str):
    # os.path.basename strips any directory component the client tries to
    # smuggle in (e.g. "../../secret") — only files directly in EVIDENCE_DIR
    # are ever served.
    path = os.path.join(EVIDENCE_DIR, os.path.basename(filename))
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Evidence file not found")
    return FileResponse(path)


async def _run_scan_background(scan_id: int, url: str, max_pages: int | None, browser) -> None:
    """Runs the actual crawl+analysis after the redirect has already been
    sent — uses its own DB connection since the request-scoped one
    (Depends(_get_conn)) is closed once the response is out. Any failure
    (including CaptchaRequiredError, which used to surface as an HTTP 409
    before scanning went async) is recorded as scans.status='done'/'error'
    instead, since there's no request left to answer synchronously."""
    bg_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    bg_conn.row_factory = sqlite3.Row
    try:
        await run_site_scan(
            url,
            bg_conn,
            EVIDENCE_DIR,
            browser=browser,
            max_pages=max_pages,
            llm_client=_LLM_CLIENT,
            scan_id=scan_id,
        )
    except RobotsDisallowedError as exc:
        mark_scan_status(
            bg_conn, scan_id, "error",
            message=(
                f"robots.txt von {exc.url} verbietet automatisiertes Durchsuchen "
                "(Disallow) — Scan sofort abgebrochen, keine Seite wurde besucht."
            ),
        )
    except Exception:
        mark_scan_status(bg_conn, scan_id, "error")
    finally:
        bg_conn.close()


@app.post("/scans")
async def start_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    max_pages: int | None = Form(None),
    conn: sqlite3.Connection = Depends(_get_conn),
):
    url = url.strip()
    if url and urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        # Root cause of "Scan starten hängt": the dashboard's URL field used
        # to be <input type="url">, which the browser silently refuses to
        # submit without a scheme (e.g. "example.com") — no error, just
        # nothing happens. Field is now plain text; normalize here so a
        # bare host works. Checking "scheme not in {http,https}" rather than
        # "not scheme": urlsplit("localhost:8000").scheme == "localhost" per
        # RFC 3986 grammar (no "//" required for a scheme), so a bare
        # "host:port" input would otherwise slip past a falsy-scheme check
        # unnormalized and hit validate_scan_url's confusing scheme-rejected
        # error instead of being treated as a host to prepend https:// to.
        # bare domain still works instead of failing validate_scan_url.
        url = f"https://{url}"
    try:
        validate_scan_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scan_id = insert_scan(conn, url)
    background_tasks.add_task(
        _run_scan_background, scan_id, url, max_pages, request.app.state.browser
    )
    return RedirectResponse(url=f"/scans/{scan_id}", status_code=303)


@app.get("/scans/compare", response_class=HTMLResponse)
def compare_scans(request: Request, scan_a: int, scan_b: int, conn: sqlite3.Connection = Depends(_get_conn)):
    a = get_scan(conn, scan_a)
    b = get_scan(conn, scan_b)
    if a is None or b is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    pages_a = get_pages(conn, scan_a)
    pages_b = get_pages(conn, scan_b)
    findings_a = _attach_display_fields(get_findings(conn, scan_a), pages_a, a["url"])
    findings_b = _attach_display_fields(get_findings(conn, scan_b), pages_b, b["url"])

    def _key(f):
        return (f["pattern_type"], f["target_norm"], f["page_url"])

    keys_a = {_key(f) for f in findings_a}
    keys_b = {_key(f) for f in findings_b}

    new_in_b = sorted(keys_b - keys_a)
    resolved = sorted(keys_a - keys_b)
    unchanged = sorted(keys_a & keys_b)

    return templates.TemplateResponse(
        request, "compare.html",
        {"scan_a": a, "scan_b": b, "new_in_b": new_in_b, "resolved": resolved, "unchanged": unchanged},
    )


@app.get("/scans/{scan_id}", response_class=HTMLResponse)
def scan_detail(
    request: Request,
    scan_id: int,
    pattern_type: str | None = None,
    target_norm: str | None = None,
    min_confidence: str | None = None,
    conn: sqlite3.Connection = Depends(_get_conn),
):
    # min_confidence is str, not float: the filter form is a plain GET form
    # that always submits all three fields, so leaving it empty sends
    # min_confidence="" — a float|None query param can't parse that and
    # FastAPI would 422 instead of treating it as "no filter".
    try:
        min_conf = float(min_confidence) if min_confidence else None
    except ValueError:
        min_conf = None

    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    pages = get_pages(conn, scan_id)
    findings = _attach_display_fields(get_findings(conn, scan_id), pages, scan["url"])
    risk = aggregate_risk_score(findings)

    filtered = findings
    if pattern_type:
        filtered = [f for f in filtered if f["pattern_type"] == pattern_type]
    if target_norm:
        filtered = [f for f in filtered if f["target_norm"] == target_norm]
    if min_conf is not None:
        filtered = [f for f in filtered if f["confidence_score"] >= min_conf]

    other_scans = [s for s in list_scans_by_url(conn, scan["url"]) if s["id"] != scan_id]

    vz_email = os.environ.get("VZ_EMAIL", "beschwerde@verbraucherzentrale.example")
    mailto_subject = urllib.parse.quote(f"Dark-Pattern-Meldung: {scan['url']}")
    mailto_body = urllib.parse.quote(
        f"Automatisiert erkannte Dark Patterns auf {scan['url']} (Kali-Scan #{scan_id}).\n\n"
        "Bitte den heruntergeladenen PDF-Report manuell an diese E-Mail anhängen "
        "(mailto-Links können keine Dateien anhängen)."
    )

    return templates.TemplateResponse(
        request, "scan_detail.html",
        {
            "scan": scan,
            "pages": pages,
            "findings": filtered,
            "risk": risk,
            "pattern_types": sorted({f["pattern_type"] for f in findings}),
            "target_norms": sorted({f["target_norm"] for f in findings}),
            "selected_pattern_type": pattern_type or "",
            "selected_target_norm": target_norm or "",
            "selected_min_confidence": min_conf,
            "vz_email": vz_email,
            "mailto_subject": mailto_subject,
            "mailto_body": mailto_body,
            "other_scans": other_scans,
        },
    )


@app.post("/scans/{scan_id}/findings/{finding_id}/review")
def set_finding_review(
    scan_id: int, finding_id: int, value: str = Form(...), conn: sqlite3.Connection = Depends(_get_conn)
):
    set_human_review(conn, finding_id, value)
    return RedirectResponse(url=f"/scans/{scan_id}", status_code=303)


@app.get("/scans/{scan_id}/pages/{page_id}", response_class=HTMLResponse)
def page_detail(request: Request, scan_id: int, page_id: int, conn: sqlite3.Connection = Depends(_get_conn)):
    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    pages = get_pages(conn, scan_id)
    findings = _attach_display_fields(get_page_findings(conn, page_id), pages, scan["url"])
    return templates.TemplateResponse(
        request, "page_detail.html", {"scan": scan, "page_id": page_id, "findings": findings}
    )


@app.get("/scans/{scan_id}/report.pdf")
def scan_report(scan_id: int, conn: sqlite3.Connection = Depends(_get_conn)):
    # Imported here, not at module level: WeasyPrint (pulled in by
    # app.reports) requires native GTK libraries that aren't installed on
    # every dev machine (e.g. Windows without GTK) — importing it eagerly
    # would crash the whole app at startup just to serve the dashboard.
    from app.reports import generate_pdf_report

    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    pages = get_pages(conn, scan_id)
    findings = _attach_display_fields(get_findings(conn, scan_id), pages, scan["url"])
    out_path = os.path.join(EVIDENCE_DIR, f"scan_{scan_id}_report.pdf")
    try:
        generate_pdf_report(scan["url"], findings, out_path)
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, see below
        # Best-effort fallback: WeasyPrint needs native GTK libraries that
        # aren't installed on every machine (e.g. Windows without GTK) —
        # rather than a raw 500 on "PDF-Report herunterladen", serve the
        # same report content as plain HTML (same template, no PDF engine
        # involved) so the evidence is still reachable.
        from collections import Counter
        logger.warning("scan_report: PDF generation failed, falling back to HTML: %s", exc)
        risk = aggregate_risk_score(findings)
        by_norm = dict(Counter(f["target_norm"] for f in findings))
        html = templates.get_template("report.html").render(
            url=scan["url"], findings=findings, risk=risk, by_norm=by_norm,
            evidence_hints=EVIDENCE_HINTS,
        )
        return HTMLResponse(
            "<p style=\"background:#fdecea;color:#611a15;padding:0.75em 1em;"
            "font-family:sans-serif;\">PDF-Engine nicht verfügbar auf diesem "
            "Rechner — hier die HTML-Ansicht des Reports.</p>" + html
        )
    return FileResponse(out_path, media_type="application/pdf")
