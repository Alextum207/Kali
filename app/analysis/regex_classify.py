"""Regex-basierte Erkennung für 4 Dark-Pattern-Typen, portiert aus
github.com/Dapde/Pattern-Highlighter (MIT-lizenziert), dessen
`chrome/scripts/constants.js` dieselben DE/EN-Regex-Paare für eine
Browser-Extension nutzt. Ersetzt für diese 4 Typen die LLM-Klassifikation
(app/analysis/llm_classify.py) — deterministisch, kein API-Call, schneller.
"""

import logging
import re

logger = logging.getLogger(__name__)

_META_CONTEXT_RE = re.compile(
    r"\b(?:z\.\s*b\.|zum\s+beispiel|beispiel|example|e\.g\.|regex|detektor|detector|"
    r"dark\s+patterns?|patterns?|dokumentation|documentation|dom(?:\s+tree)?|render-tree|"
    r"report|funde?|scannt|erkennung|erkennen|klassifizier(?:t|ung)?)\b",
    re.IGNORECASE,
)


def _is_meta_context(text: str, start: int, end: int) -> bool:
    prefix = text[max(0, start - 140):start]
    if _META_CONTEXT_RE.search(prefix):
        return True

    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    return bool(re.search(r"\b(?:const|let|var|function|regex|example|beispiel)\b|[<>{};=]", line, re.IGNORECASE))


def _is_seller_attribution(text: str, match: re.Match) -> bool:
    matched = match.group(0).lower()
    suffix = text[match.end():match.end() + 16].lower()
    if not re.search(r"\b(?:sold|verkauft)\b", matched):
        return False
    return bool(re.match(r"[ \t]*(?:by|von)\b", suffix))


def _is_compact_hash_like_urgency(match: re.Match) -> bool:
    quote = match.group(0).strip()
    # Precision guard from the live benchmark: package/version hashes such as
    # "98d6d" look like "98 d 6 d" to the static regex. A real visible
    # countdown should contain separators or word units ("2 days 3 hours").
    return bool(re.fullmatch(r"(?:\d{1,2}[dhms]){2,4}", quote, re.IGNORECASE))


def _should_skip_match(pattern_type: str, text: str, match: re.Match) -> bool:
    if _is_meta_context(text, match.start(), match.end()):
        return True
    if pattern_type == "Fake Urgency" and _is_compact_hash_like_urgency(match):
        return True
    return pattern_type == "Fake Scarcity" and _is_seller_attribution(text, match)


# (pattern_type, compiled_regex, confidence) je Sprachvariante. Werte
# wortwörtlich aus dem Quell-Repo übernommen, nur nach Python `re` übersetzt.
_PATTERNS = [
    (
        "Fake Urgency",
        re.compile(
            # ponytail: the source repo's colon-format alternative
            # ("(?:\d{1,2}\s*:\s*){1,3}\d{1,2}") is dropped here — in
            # constants.js it only ever fires after a live DOM diff confirms
            # the number is actually decreasing between two page states; on
            # static extracted text there's no time axis to check that, so
            # it matched any HH:MM-shaped substring unconditionally (a
            # store's "Mo-Fr 9:00 - 18:00 Uhr" opening hours, a phone
            # number, ...). The verified DOM-countdown path already exists
            # separately (app/crawler.py::find_countdown_elements +
            # verify_countdown_reset, Playwright Clock API) — this regex
            # keeps only the verbal "N days/hours/minutes" phrasing, which
            # doesn't need a live DOM to be a real urgency claim.
            r"(?:\d{1,2}\s*(?:days?|d|hours?|hrs?|h|minutes?|mins?|min|seconds?|secs?|s|tage?|stunden?|std\.?|minuten?|sekunden?)(?:\s*und)?\s*){2,4}",
            re.IGNORECASE,
        ),
        0.85,
    ),
    (
        "Fake Scarcity",
        re.compile(
            # \d+(?:[.,]\d+)? and the optional Tsd./Mio./K magnitude group:
            # a plain \d+ missed thousands-shorthand badges like "14 Tsd.
            # verkauft" or "1.2K sold" — the magnitude word sat between the
            # number and the verb, outside the old optional-unit group. Real
            # bug report from a live Amazon listing page (mistakes/scarcity
            # nicht alles erkannt.png).
            r"\d+(?:[.,]\d+)?[ \t]*[Kk]?\+?[ \t]*(?:\%|pieces?|pcs\.?|pc\.?|ct\.?|items?)?[ \t]*(?:available|sold|claimed|redeemed)"
            r"|(?:last|final)[ \t]*(?:article|item)"
            r"|\d+(?:[.,]\d+)?[ \t]*(?:Tsd\.?|Mio\.?)?[ \t]*(?:\%|stücke?|stk\.?)?[ \t]*(?:verfügbar|verkauft|eingelöst)"
            r"|letzter[ \t]*Artikel",
            re.IGNORECASE,
        ),
        0.85,
    ),
    (
        "Fake Social Proof",
        re.compile(
            r"\d+[ \t]*(?:other)?[ \t]*(?:customers?|clients?|buyers?|users?|shoppers?|purchasers?|people)"
            r"[ \t]*(?:have[ \t]+)?[ \t]*(?:(?:also[ \t]*)?(?:bought|purchased|ordered)|(?:rated|reviewed))"
            r"|\d+[ \t]*(?:andere)?[ \t]*(?:Kunden?|Käufer|Besteller|Nutzer|Leute)"
            r"[ \t]*(?:haben[ \t]+)?[ \t]*(?:(?:auch[ \t]*)?(?:gekauft|bestellt)|(?:bewertet|rezensiert))",
            re.IGNORECASE,
        ),
        0.85,
    ),
    (
        "Forced Continuity",
        re.compile(
            r"(?:€|EUR|GBP|£|\$|USD)[ \t]*\d+(?:\.\d{2})?[ \t]*(?:after|from[ \t]*month)"
            r"|\d+(?:,\d{2})?[ \t]*(?:Euro|€)[ \t]*(?:ab[ \t]*dem[ \t]*\d+\.[ \t]*Monat|nach)"
            # The two alternatives above are the original (narrower) port;
            # constants.js's Forced Continuity has since grown 6 more EN/DE
            # phrasings this file never picked up (code review 2026-08-25) —
            # ported below so the compliance PDF report doesn't miss what
            # the extension already catches. PRICE fragment repeated inline
            # (like the JS source) rather than factored out, to keep each
            # alternative comparable line-by-line against its constants.js
            # counterpart.
            r"|(?:(?:€|EUR|GBP|£|\$|USD)[ \t]*\d+(?:\.\d{2})?|\d+(?:\.\d{2})?[ \t]*(?:euros?|€|EUR|GBP|£|pounds?(?:[ \t]*sterling)?|\$|USD|dollars?))"
            r"[ \t]*(?:(?:(?:per|/|a)[ \t]*month)|(?:p|/)m)[ \t]*(?:after|from[ \t]*(?:month|day)[ \t]*\d+)"
            r"|(?:(?:€|EUR|GBP|£|\$|USD)[ \t]*\d+(?:\.\d{2})?|\d+(?:\.\d{2})?[ \t]*(?:euros?|€|EUR|GBP|£|pounds?(?:[ \t]*sterling)?|\$|USD|dollars?))"
            r"[ \t]*(?:after[ \t]*(?:the)?[ \t]*\d+(?:st|nd|rd|th)?[ \t]*(?:months?|days?)|from[ \t]*(?:month|day)[ \t]*\d+)"
            r"|(?:after[ \t]*that|then|afterwards|subsequently)[ \t]*"
            r"(?:(?:€|EUR|GBP|£|\$|USD)[ \t]*\d+(?:\.\d{2})?|\d+(?:\.\d{2})?[ \t]*(?:euros?|€|EUR|GBP|£|pounds?(?:[ \t]*sterling)?|\$|USD|dollars?))"
            r"[ \t]*(?:(?:(?:per|/|a)[ \t]*month)|(?:p|/)m)"
            r"|after[ \t]*(?:the)?[ \t]*\d+(?:st|nd|rd|th)?[ \t]*months?[ \t]*(?:only|just)?[ \t]*"
            r"(?:(?:€|EUR|GBP|£|\$|USD)[ \t]*\d+(?:\.\d{2})?|\d+(?:\.\d{2})?[ \t]*(?:euros?|€|EUR|GBP|£|pounds?(?:[ \t]*sterling)?|\$|USD|dollars?))"
            r"|\d+(?:,\d{2})?[ \t]*(?:Euro|€)[ \t]*(?:(?:pro|im|/)[ \t]*Monat)?[ \t]*"
            r"(?:ab[ \t]*(?:dem)?[ \t]*\d+\.[ \t]*Monat|nach[ \t]*\d+[ \t]*(?:Monaten|Tagen)|nach[ \t]*(?:einem|1)[ \t]*Monat)"
            r"|(?:anschließend|danach)[ \t]*\d+(?:,\d{2})?[ \t]*(?:Euro|€)[ \t]*(?:pro|im|/)[ \t]*Monat"
            r"|\d+(?:,\d{2})?[ \t]*(?:Euro|€)[ \t]*(?:pro|im|/)[ \t]*Monat[ \t]*(?:anschließend|danach)"
            r"|ab(?:[ \t]*dem)?[ \t]*\d+\.[ \t]*Monat(?:[ \t]*nur)?[ \t]*\d+(?:,\d{2})?[ \t]*(?:Euro|€)",
            re.IGNORECASE,
        ),
        0.85,
    ),
]


def find_regex_patterns(main_text: str) -> list[dict]:
    findings = []
    for pattern_type, regex, confidence in _PATTERNS:
        for match in regex.finditer(main_text):
            if _should_skip_match(pattern_type, main_text, match):
                continue
            findings.append(
                {
                    "pattern_type": pattern_type,
                    "confidence_score": confidence,
                    "evidence_data": {"quote": match.group(0)},
                }
            )
    # ponytail: temporary unconditional diagnostic (remove once the live
    # "Fake Urgency" mystery is settled) -- logs every regex-produced finding
    # plus a text length/repr sample, so a live log grep proves whether this
    # function is the source and what input text it actually received.
    logger.warning(
        "find_regex_patterns: text_len=%d text_head=%r findings=%r",
        len(main_text), main_text[:300], findings,
    )
    return findings
