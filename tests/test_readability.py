from app.analysis.readability import flag_complex_language, _split_sentences

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


def test_split_sentences_handles_abbreviations():
    """Verify that abbreviations like Art., Nr., bzw., z.B. are not treated as sentence endings."""
    text = "Gemäß Art. 5 Nr. 2 bzw. z.B. hier."
    sentences = _split_sentences(text, split_style="word")
    # Should be 1 sentence, not 4 (Art., Nr., bzw., z.B. each followed by a period).
    assert len(sentences) == 1
    assert sentences[0].strip() == "Gemäß Art. 5 Nr. 2 bzw. z.B. hier"


def test_split_sentences_preserves_actual_sentence_endings():
    """Verify that real sentence endings are still detected correctly."""
    text = "First sentence. Second sentence! Third sentence?"
    sentences = _split_sentences(text, split_style="word")
    assert len(sentences) == 3
    assert sentences[0].strip() == "First sentence"
    assert sentences[1].strip() == "Second sentence"
    assert sentences[2].strip() == "Third sentence"


def test_split_sentences_lookahead_style():
    """Verify lookahead-style split (preserves punctuation)."""
    text = "Gemäß Art. 5 Nr. 2 bzw. z.B. hier. Next sentence."
    sentences = _split_sentences(text, split_style="lookahead")
    # With lookahead, punctuation is preserved; should split into 2 on the final period.
    assert len(sentences) == 2
    # First sentence should include the Art./Nr./bzw./z.B. parts and the first period
    assert "Art." in sentences[0]
    assert "z.B." in sentences[0]
