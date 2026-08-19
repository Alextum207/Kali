"""Pytest configuration and fixtures."""
import sys
from unittest.mock import MagicMock
import pytest


# Mock WeasyPrint to avoid GTK dependency on Windows during testing
class MockHTML:
    """Mock WeasyPrint HTML class that writes a minimal PDF."""

    def __init__(self, string=None, **kwargs):
        self.string = string
        self.kwargs = kwargs

    def write_pdf(self, filename):
        """Write a minimal valid PDF file."""
        # Minimal PDF structure that validates as PDF
        minimal_pdf = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT
/F1 12 Tf
100 700 Td
(Mock PDF) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000203 00000 n
trailer
<< /Size 5 /Root 1 0 R >>
startxref
296
%%EOF
"""
        with open(filename, "wb") as f:
            f.write(minimal_pdf)


# Conditionally mock weasyprint only if the real import fails (GTK unavailable).
# This allows environments with proper WeasyPrint to use the real library.
# Comment explains: mock exists because Windows lacks GTK runtime; future envs
# with proper WeasyPrint/GTK will test the real library.
if "weasyprint" not in sys.modules:
    try:
        import weasyprint as _real_weasyprint  # noqa: F401
    except (ImportError, OSError):
        # GTK dependency missing (e.g., Windows without GTK runtime)
        mock_weasyprint = MagicMock()
        mock_weasyprint.HTML = MockHTML
        sys.modules["weasyprint"] = mock_weasyprint
