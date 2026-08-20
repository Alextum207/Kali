import re

from app.crawler import LEGAL_TEXT_KEYWORDS as _LEGAL_KEYWORDS

# flag_complex_language contrasts legal-sentence readability against the
# surrounding marketing copy's readability — it needs a *narrow*, precise
# legal-sentence bucket, unlike find_low_contrast_legal_text (which uses the
# wider _LEGAL_KEYWORDS/LEGAL_TEXT_KEYWORDS for recall). Pulling generic
# commercial terms like "preis"/"kosten"/"laufzeit" into this bucket lets
# ordinary marketing sentences ("Bester Preis!") count as "legal", raising
# the legal bucket's average readability and shrinking the delta this
# heuristic depends on. Keep this list to the original, narrower terms.
_COMPLEX_LANGUAGE_KEYWORDS = ("kündigung", "widerruf", "gebühr", "vertragslaufzeit", "agb", "schiedsgericht")


def _count_syllables(word: str) -> int:
    groups = re.findall(r"[aeiouyäöü]+", word.lower())
    return max(1, len(groups))


def _split_sentences(text: str, split_style: str = "word") -> list[str]:
    r"""Split text into sentences, handling abbreviations like 'Art.', 'Nr.', 'bzw.', 'z.B.'.

    Args:
        text: Input text to split.
        split_style: 'word' (default) for `[.!?]+` split; 'lookahead' for `(?<=[.!?])\s+` split.

    Returns:
        List of non-empty, stripped sentences.
    """
    # Protect common abbreviations by replacing all their dots with placeholders
    protected = text
    # Replace "Art." (and similar)
    protected = re.sub(r"\bArt\.", "Art<DOT>", protected)
    protected = re.sub(r"\bNr\.", "Nr<DOT>", protected)
    protected = re.sub(r"\bbzw\.", "bzw<DOT>", protected)
    # Replace "z.B." — must handle the dot in the middle and at the end
    protected = re.sub(r"z\.B\.", "z<DOT>B<DOT>", protected)

    if split_style == "lookahead":
        # Split on whitespace following sentence-ending punctuation (preserves punctuation)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", protected) if s.strip()]
    else:
        # Default: split on sequence of sentence-ending punctuation (removes punctuation)
        sentences = [s.strip() for s in re.split(r"[.!?]+", protected) if s.strip()]

    # Restore placeholders to dots
    return [s.replace("<DOT>", ".") for s in sentences]


def _readability_score(text: str) -> float:
    """A simplified Flesch Reading Ease score. Higher = easier to read.
    Not a precise linguistic instrument — used only as a relative
    comparison between two excerpts of the same page, not an absolute
    grade level."""
    sentences = _split_sentences(text, split_style="word")
    words = re.findall(r"[A-Za-zÄÖÜäöüß]+", text)
    if not sentences or not words:
        return 100.0
    syllables = sum(_count_syllables(w) for w in words)
    avg_sentence_len = len(words) / len(sentences)
    avg_syllables = syllables / len(words)
    return 206.835 - 1.015 * avg_sentence_len - 84.6 * avg_syllables


def flag_complex_language(text: str) -> dict | None:
    """Compares the readability of legally-relevant sentences (containing
    keywords like "Kündigung"/"Widerruf") against the rest of the page's
    text. A legal excerpt that's meaningfully harder to read than the
    surrounding marketing copy is a comprehension-barrier signal — the
    reader isn't struggling with the whole page, just the part that
    matters legally."""
    sentences = _split_sentences(text, split_style="lookahead")
    legal_sentences = [s for s in sentences if any(kw in s.lower() for kw in _COMPLEX_LANGUAGE_KEYWORDS)]
    other_sentences = [s for s in sentences if s not in legal_sentences]
    if not legal_sentences or not other_sentences:
        return None

    legal_score = _readability_score(" ".join(legal_sentences))
    other_score = _readability_score(" ".join(other_sentences))

    # ponytail: 15-point Flesch-Delta cutoff is arbitrary, tuned by empirical
    # observation of false-positive rates on real dark-pattern sites. No recalibration
    # attempted in this pass.
    if legal_score < other_score - 15:
        return {
            "pattern_type": "Verständnis-Barriere (Sprachkomplexität)",
            "confidence_score": 0.55,
            "evidence_data": {
                "legal_readability_score": round(legal_score, 1),
                "page_readability_score": round(other_score, 1),
                "excerpt": legal_sentences[0][:200],
            },
        }
    return None
