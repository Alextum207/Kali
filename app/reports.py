import os
from collections import Counter

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.compliance import aggregate_risk_score

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR))


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
    html_content = template.render(url=url, findings=findings, risk=risk, by_norm=by_norm)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    HTML(string=html_content).write_pdf(out_path)
    return out_path
