import os

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates

from app.db import init_db, get_scan, get_findings
from app.scan import run_scan
from app.reports import generate_pdf_report

app = FastAPI(title="Dark-Pattern-Monitor")

DB_PATH = os.environ.get("DB_PATH", "./data/monitor.db")
EVIDENCE_DIR = os.environ.get("EVIDENCE_DIR", "./data/evidence")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def _get_conn():
    return init_db(DB_PATH)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html")


@app.post("/scans")
async def start_scan(url: str = Form(...)):
    conn = _get_conn()
    # ponytail: no persistent Playwright browser is wired up for the FastAPI
    # app (out of scope for this task) — run_scan(..., browser=None) will
    # crash inside crawl_page's browser.new_context() call until a task
    # gives the app a Playwright browser lifecycle. Tests mock run_scan.
    scan_id = await run_scan(url, conn, EVIDENCE_DIR, browser=None)
    return RedirectResponse(url=f"/scans/{scan_id}", status_code=303)


@app.get("/scans/{scan_id}", response_class=HTMLResponse)
def scan_detail(request: Request, scan_id: int):
    conn = _get_conn()
    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    findings = get_findings(conn, scan_id)
    return templates.TemplateResponse(
        request, "scan_detail.html", {"scan": scan, "findings": findings}
    )


@app.get("/scans/{scan_id}/report.pdf")
def scan_report(scan_id: int):
    conn = _get_conn()
    scan = get_scan(conn, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    findings = get_findings(conn, scan_id)
    out_path = os.path.join(EVIDENCE_DIR, f"scan_{scan_id}_report.pdf")
    generate_pdf_report(scan["url"], findings, out_path)
    return FileResponse(out_path, media_type="application/pdf")
