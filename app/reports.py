import base64
import os
from collections import Counter

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.compliance import EVIDENCE_HINTS, aggregate_risk_score

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR))

# Embedded as a data URI (not a relative path) so the PDF renders correctly
# regardless of working directory/base_url — WeasyPrint is given raw HTML
# via HTML(string=...) below, not a file path, so a relative <img src> would
# never resolve.
_LOGO_PATH = os.path.join(os.path.dirname(__file__), "static", "kali-logo.png")
with open(_LOGO_PATH, "rb") as _f:
    LOGO_DATA_URI = "data:image/png;base64," + base64.b64encode(_f.read()).decode("ascii")


def _embed_screenshot(finding: dict) -> dict:
    """Returns a shallow copy of `finding` with evidence_data augmented by a
    base64 `screenshot_data_uri`, read from evidence_data["screenshot_path"]
    (the real file on disk saved by app/evidence.py) — so the PDF embeds
    the actual evidence image inline instead of just printing its path/URL
    as text. Never mutates the caller's finding/evidence_data dicts (the
    same findings list is also used to render scan_detail.html). Best-effort:
    a missing/unreadable file must never block the rest of the report."""
    evidence = dict(finding.get("evidence_data") or {})
    path = evidence.get("screenshot_path")
    if path and os.path.isfile(path):
        try:
            with open(path, "rb") as f:
                evidence["screenshot_data_uri"] = "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
        except OSError:
            pass
    new_finding = dict(finding)
    new_finding["evidence_data"] = evidence
    return new_finding


def generate_pdf_report(url: str, findings: list[dict], out_path: str) -> str:
    """Generate a PDF report from findings.

    Args:
        url: The website URL that was scanned.
        findings: List of finding dicts with pattern_type, target_norm, confidence_score, evidence_data.
        out_path: Path to write the PDF file to.

    Returns:
        The out_path (for convenience).
    """
    template = _env.get_template("report.html")
    risk = aggregate_risk_score(findings)
    by_norm = dict(Counter(f["target_norm"] for f in findings))
    findings_with_screenshots = [_embed_screenshot(f) for f in findings]
    html_content = template.render(
        url=url, findings=findings_with_screenshots, risk=risk, by_norm=by_norm, logo=LOGO_DATA_URI,
        evidence_hints=EVIDENCE_HINTS,
    )
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    HTML(string=html_content).write_pdf(out_path)
    return out_path
