from app.analysis.text_extract import extract_main_text

SAMPLE_HTML = """
<html><body>
<nav>Home | Products | About Navigation Link Menu</nav>
<main><p>Only 2 items left in stock! Order now before it's too late.</p></main>
<footer>Copyright 2026 Footer Legal Links Imprint</footer>
</body></html>
"""

def test_extract_main_text_drops_boilerplate():
    text = extract_main_text(SAMPLE_HTML)
    assert "Only 2 items left in stock" in text
    assert "Navigation Link Menu" not in text
    assert "Footer Legal Links Imprint" not in text
