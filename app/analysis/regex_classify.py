"""Regex-basierte Erkennung für 4 Dark-Pattern-Typen, portiert aus
github.com/Dapde/Pattern-Highlighter (MIT-lizenziert), dessen
`chrome/scripts/constants.js` dieselben DE/EN-Regex-Paare für eine
Browser-Extension nutzt. Ersetzt für diese 4 Typen die LLM-Klassifikation
(app/analysis/llm_classify.py) — deterministisch, kein API-Call, schneller.
"""

import re

# (pattern_type, compiled_regex, confidence) je Sprachvariante. Werte
# wortwörtlich aus dem Quell-Repo übernommen, nur nach Python `re` übersetzt.
_PATTERNS = [
    (
        "Fake Urgency",
        re.compile(
            r"(?:\d{1,2}\s*:\s*){1,3}\d{1,2}"
            r"|(?:\d{1,2}\s*(?:days?|hours?|minutes?|seconds?|tage?|stunden?|minuten?|sekunden?|[a-zA-Z]{1,3}\.?)(?:\s*und)?\s*){2,4}",
            re.IGNORECASE,
        ),
        0.85,
    ),
    (
        "Fake Scarcity",
        re.compile(
            r"\d+\s*(?:\%|pieces?|pcs\.?|pc\.?|ct\.?|items?)?\s*(?:available|sold|claimed|redeemed)"
            r"|(?:last|final)\s*(?:article|item)"
            r"|\d+\s*(?:\%|stücke?|stk\.?)?\s*(?:verfügbar|verkauft|eingelöst)"
            r"|letzter\s*Artikel",
            re.IGNORECASE,
        ),
        0.85,
    ),
    (
        "Fake Social Proof",
        re.compile(
            r"\d+\s*(?:other)?\s*(?:customers?|clients?|buyers?|users?|shoppers?|purchasers?|people)"
            r"\s*(?:have\s+)?\s*(?:(?:also\s*)?(?:bought|purchased|ordered)|(?:rated|reviewed))"
            r"|\d+\s*(?:andere)?\s*(?:Kunden?|Käufer|Besteller|Nutzer|Leute)"
            r"\s*(?:haben\s+)?\s*(?:(?:auch\s*)?(?:gekauft|bestellt)|(?:bewertet|rezensiert))",
            re.IGNORECASE,
        ),
        0.85,
    ),
    (
        "Forced Continuity",
        re.compile(
            r"(?:€|EUR|GBP|£|\$|USD)\s*\d+(?:\.\d{2})?\s*(?:after|from\s*month)"
            r"|\d+(?:,\d{2})?\s*(?:Euro|€)\s*(?:ab\s*dem\s*\d+\.\s*Monat|nach)",
            re.IGNORECASE,
        ),
        0.85,
    ),
]


def find_regex_patterns(main_text: str) -> list[dict]:
    findings = []
    for pattern_type, regex, confidence in _PATTERNS:
        for match in regex.finditer(main_text):
            findings.append(
                {
                    "pattern_type": pattern_type,
                    "confidence_score": confidence,
                    "evidence_data": {"quote": match.group(0)},
                }
            )
    return findings
