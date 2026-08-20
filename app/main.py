import os
import sqlite3
from contextlib import asynccontextmanager

import anthropic
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright

from app.db import init_db, get_scan, get_findings, get_pages, get_page_findings
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


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html")


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

    scan_id = await run_site_scan(
        url,
        conn,
        EVIDENCE_DIR,
        browser=request.app.state.browser,
        max_pages=max_pages,
        llm_client=_LLM_CLIENT,
    )
    return RedirectResponse(url=f"/scans/{scan_id}", status_code=303)


@app.get("/scans/{scan_id}", response_class=HTMLResponse)
def scan_detail(request: Request, scan_id: int, conn: sqlite3.Connection = Depends(_get_conn)):
    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    pages = get_pages(conn, scan_id)
    findings = get_findings(conn, scan_id)
    return templates.TemplateResponse(
        request, "scan_detail.html", {"scan": scan, "pages": pages, "findings": findings}
    )


@app.get("/scans/{scan_id}/pages/{page_id}", response_class=HTMLResponse)
def page_detail(request: Request, scan_id: int, page_id: int, conn: sqlite3.Connection = Depends(_get_conn)):
    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    findings = get_page_findings(conn, page_id)
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
    findings = get_findings(conn, scan_id)
    out_path = os.path.join(EVIDENCE_DIR, f"scan_{scan_id}_report.pdf")
    generate_pdf_report(scan["url"], findings, out_path)
    return FileResponse(out_path, media_type="application/pdf")
