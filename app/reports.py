import os
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

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
    html_content = template.render(url=url, findings=findings)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    HTML(string=html_content).write_pdf(out_path)
    return out_path
