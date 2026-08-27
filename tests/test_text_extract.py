from app.analysis.text_extract import extract_main_text

SAMPLE_HTML = """
<html><body>
<nav>Home | Products | About Navigation Link Menu</nav>
<main><p>Only 2 items left in stock! Order now before it's too late. Act fast
to secure your discount before the offer disappears forever. Many other
customers are looking at this exact same product right now, so don't wait
too long or you might miss out on this incredible deal entirely.</p></main>
<footer>Copyright 2026 Footer Legal Links Imprint</footer>
</body></html>
"""

def test_extract_main_text_drops_boilerplate():
    text = extract_main_text(SAMPLE_HTML)
    assert "Only 2 items left in stock" in text
    assert "Navigation Link Menu" not in text
    assert "Footer Legal Links Imprint" not in text


TINY_NAG_BANNER_HTML = """
<html><body>
<div class="nag-banner">Nur noch heute!</div>
</body></html>
"""


def test_extract_main_text_falls_back_to_recall_for_short_precise_result(monkeypatch):
    """favor_precision can decide a tiny nag-banner page has no "main
    content" at all (None/very short) — the favor_recall fallback should
    still surface the micro-copy instead of returning empty text."""
    import app.analysis.text_extract as text_extract_module

    calls = []

    def fake_extract(html, favor_precision=False, favor_recall=False):
        calls.append((favor_precision, favor_recall))
        if favor_precision:
            return None
        return "Nur noch heute!"

    monkeypatch.setattr(text_extract_module.trafilatura, "extract", fake_extract)

    text = text_extract_module.extract_main_text(TINY_NAG_BANNER_HTML)

    assert text == "Nur noch heute!"
    assert calls == [(True, False), (False, True)]
