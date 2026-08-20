import os
import sqlite3
from contextlib import asynccontextmanager

# Must run before any `app.*` import below — several modules (app.scan,
# app.site_crawler, ...) read os.environ at import time for their own
# defaults (MAX_FLOW_STEPS, LEGAL_TEXT_MCP_BASE_URL, ...). load_dotenv()
# only sets variables not already present in the environment, so an
# explicitly exported/deployment-set env var still wins over .env.
from dotenv import load_dotenv
load_dotenv()

import anthropic
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright
from pydantic import BaseModel

from app.compliance import aggregate_risk_score
from app.crawler import CaptchaRequiredError
from app.db import init_db, get_scan, get_findings, get_pages, get_page_findings, list_scans
from app.scan import run_site_scan
from app.url_safety import validate_scan_url

DB_PATH = os.environ.get("DB_PATH", "./data/monitor.db")
EVIDENCE_DIR = os.environ.get("EVIDENCE_DIR", "./data/evidence")

# Same "construct only if key present" pattern as classify_text's fallback
# in app/analysis/llm_classify.py. None here means local dev/CI without the
# key keeps working exactly as before (category/interaction LLM steps no-op).
_LLM_CLIENT = (
    anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
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
    for scan in scans:
        scan["risk"] = aggregate_risk_score(get_findings(conn, scan["id"]))
    return templates.TemplateResponse(request, "dashboard.html", {"scans": scans})


@app.get("/evidence/{filename}")
def evidence_file(filename: str):
    # os.path.basename strips any directory component the client tries to
    # smuggle in (e.g. "../../secret") — only files directly in EVIDENCE_DIR
    # are ever served.
    path = os.path.join(EVIDENCE_DIR, os.path.basename(filename))
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Evidence file not found")
    return FileResponse(path)


@app.post("/scans")
async def start_scan(
    request: Request,
    url: str = Form(...),
    max_pages: int | None = Form(None),
    conn: sqlite3.Connection = Depends(_get_conn),
):
    try:
        validate_scan_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        scan_id = await run_site_scan(
            url,
            conn,
            EVIDENCE_DIR,
            browser=request.app.state.browser,
            max_pages=max_pages,
            llm_client=_LLM_CLIENT,
        )
    except CaptchaRequiredError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Captcha erkannt auf {exc.url} — bitte manuell lösen und Scan erneut starten.",
        ) from exc
    return RedirectResponse(url=f"/scans/{scan_id}", status_code=303)


class ExtensionScanRequest(BaseModel):
    url: str
    cookies: list[dict] = []


@app.post("/scans/extension")
async def start_scan_from_extension(
    request: Request,
    body: ExtensionScanRequest,
    conn: sqlite3.Connection = Depends(_get_conn),
):
    """Chrome-Extension cookie-handoff entrypoint — see
    docs/superpowers/specs/2026-08-20-chrome-extension-cookie-handoff-design.md.
    Same validation/pipeline as POST /scans, plus cookies (chrome.cookies.
    getAll() shape) injected into the Playwright context before the crawl,
    so it continues with the tab's already-authenticated/consent-resolved
    session. Returns JSON (not a redirect) — the extension's service worker
    opens the result tab itself."""
    try:
        validate_scan_url(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        scan_id = await run_site_scan(
            body.url,
            conn,
            EVIDENCE_DIR,
            browser=request.app.state.browser,
            llm_client=_LLM_CLIENT,
            cookies=body.cookies,
        )
    except CaptchaRequiredError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "captcha_required", "url": exc.url},
        ) from exc
    return JSONResponse({"scan_id": scan_id})


@app.get("/scans/{scan_id}", response_class=HTMLResponse)
def scan_detail(
    request: Request,
    scan_id: int,
    pattern_type: str | None = None,
    target_norm: str | None = None,
    min_confidence: float | None = None,
    conn: sqlite3.Connection = Depends(_get_conn),
):
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
    if min_confidence is not None:
        filtered = [f for f in filtered if f["confidence_score"] >= min_confidence]

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
            "selected_min_confidence": min_confidence,
        },
    )


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
    generate_pdf_report(scan["url"], findings, out_path)
    return FileResponse(out_path, media_type="application/pdf")
