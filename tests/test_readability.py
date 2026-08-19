from app.analysis.readability import flag_complex_language

COMPLEX_LEGAL_TEXT = (
    "Willkommen in unserem Shop! Wir freuen uns, dass Sie da sind. "
    "Schauen Sie sich gerne um und entdecken Sie unsere neuen Produkte. "
    "Unbeschadet der Bestimmungen des vorstehenden Absatzes bleibt "
    "die außerordentliche Kündigung aus wichtigem Grund unter "
    "gleichzeitiger Wahrung sämtlicher hierin nicht explizit "
    "ausgeschlossener gesetzlicher Widerrufsmöglichkeiten unberührt, "
    "sofern nicht anderweitig vertraglich disponiert wurde."
)

SIMPLE_TEXT = (
    "Willkommen in unserem Shop! Wir freuen uns, dass Sie da sind. "
    "Schauen Sie sich gerne um. Sie können jederzeit kündigen. "
    "Schreiben Sie uns einfach eine E-Mail."
)


def test_flag_complex_language_detects_dense_legal_sentence():
    result = flag_complex_language(COMPLEX_LEGAL_TEXT)
    assert result is not None
    assert result["pattern_type"] == "Verständnis-Barriere (Sprachkomplexität)"
    assert 0.0 <= result["confidence_score"] <= 1.0
    assert "kündigung" in result["evidence_data"]["excerpt"].lower()


def test_flag_complex_language_returns_none_for_uniformly_simple_text():
    assert flag_complex_language(SIMPLE_TEXT) is None


def test_flag_complex_language_returns_none_without_legal_keywords():
    assert flag_complex_language("Ein ganz normaler Text ohne besondere Begriffe.") is None
