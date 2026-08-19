import re

_LEGAL_KEYWORDS = ("kündigung", "widerruf", "gebühr", "vertragslaufzeit", "agb", "schiedsgericht")


def _count_syllables(word: str) -> int:
    groups = re.findall(r"[aeiouyäöü]+", word.lower())
    return max(1, len(groups))


def _readability_score(text: str) -> float:
    """A simplified Flesch Reading Ease score. Higher = easier to read.
    Not a precise linguistic instrument — used only as a relative
    comparison between two excerpts of the same page, not an absolute
    grade level."""
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
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
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    legal_sentences = [s for s in sentences if any(kw in s.lower() for kw in _LEGAL_KEYWORDS)]
    other_sentences = [s for s in sentences if s not in legal_sentences]
    if not legal_sentences or not other_sentences:
        return None

    legal_score = _readability_score(" ".join(legal_sentences))
    other_score = _readability_score(" ".join(other_sentences))

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
