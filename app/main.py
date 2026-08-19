import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright

from app.db import init_db, get_scan, get_findings
from app.scan import run_scan
from app.reports import generate_pdf_report
from app.url_safety import validate_scan_url

DB_PATH = os.environ.get("DB_PATH", "./data/monitor.db")
EVIDENCE_DIR = os.environ.get("EVIDENCE_DIR", "./data/evidence")


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
    request: Request, url: str = Form(...), conn: sqlite3.Connection = Depends(_get_conn)
):
    try:
        validate_scan_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scan_id = await run_scan(url, conn, EVIDENCE_DIR, browser=request.app.state.browser)
    return RedirectResponse(url=f"/scans/{scan_id}", status_code=303)


@app.get("/scans/{scan_id}", response_class=HTMLResponse)
def scan_detail(request: Request, scan_id: int, conn: sqlite3.Connection = Depends(_get_conn)):
    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    findings = get_findings(conn, scan_id)
    return templates.TemplateResponse(
        request, "scan_detail.html", {"scan": scan, "findings": findings}
    )


@app.get("/scans/{scan_id}/report.pdf")
def scan_report(scan_id: int, conn: sqlite3.Connection = Depends(_get_conn)):
    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    findings = get_findings(conn, scan_id)
    out_path = os.path.join(EVIDENCE_DIR, f"scan_{scan_id}_report.pdf")
    generate_pdf_report(scan["url"], findings, out_path)
    return FileResponse(out_path, media_type="application/pdf")
