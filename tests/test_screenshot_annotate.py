import io

from PIL import Image

from app.analysis.screenshot_annotate import highlight_quote_in_screenshot


def _make_png(width=400, height=300) -> bytes:
    img = Image.new("RGB", (width, height), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


TEXT_BOXES = [
    {"text": "Willkommen im Shop", "x": 10, "y": 10, "width": 150, "height": 20},
    {"text": "9,99 Euro ab dem 2. Monat", "x": 20, "y": 100, "width": 200, "height": 30},
]


def test_highlight_quote_in_screenshot_finds_exact_match():
    screenshot = _make_png()
    result = highlight_quote_in_screenshot(screenshot, "9,99 Euro ab dem 2. Monat", TEXT_BOXES)

    assert result is not None
    assert isinstance(result, bytes)
    # A red rectangle must actually have been drawn somewhere in the image —
    # a pure-white image (the original, untouched) means nothing was drawn.
    img = Image.open(io.BytesIO(result))
    assert img.getcolors(maxcolors=1) is None or img.getcolors(maxcolors=1)[0][1] != (255, 255, 255)


def test_highlight_quote_in_screenshot_matches_substring_within_longer_box_text():
    screenshot = _make_png()
    result = highlight_quote_in_screenshot(screenshot, "ab dem 2. Monat", TEXT_BOXES)
    assert result is not None


def test_highlight_quote_in_screenshot_returns_none_when_no_box_matches():
    screenshot = _make_png()
    result = highlight_quote_in_screenshot(screenshot, "völlig unbezogener text", TEXT_BOXES)
    assert result is None


def test_highlight_quote_in_screenshot_returns_none_for_empty_boxes():
    screenshot = _make_png()
    result = highlight_quote_in_screenshot(screenshot, "9,99 Euro ab dem 2. Monat", [])
    assert result is None
