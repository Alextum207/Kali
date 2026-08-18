import json
import logging
import os
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

_EXAMPLES_PATH = Path(__file__).resolve().parents[2] / "data" / "mathur_examples.json"

SYSTEM_PROMPT = """Du bist ein Klassifikator für manipulative UX-Texte (Dark Patterns).
Antworte AUSSCHLIESSLICH mit einem JSON-Array. Jedes Element hat die Felder
"pattern_type" (einer aus: Fake Urgency, Fake Scarcity, Fake Social Proof,
Confirm Shaming, Sneaking / Hidden Costs), "confidence_score" (0.0-1.0) und
"quote" (das wörtliche Zitat aus dem Text, das den Fund belegt). Gib ein
leeres Array [] zurück, wenn der Text keine Dark Patterns enthält.

Beispiele:
"""


def _build_system_prompt() -> str:
    examples = json.loads(_EXAMPLES_PATH.read_text(encoding="utf-8"))
    lines = [SYSTEM_PROMPT]
    for ex in examples:
        lines.append(f'- "{ex["text"]}" -> {ex["pattern_type"]}')
    return "\n".join(lines)


def classify_text(text: str, client=None) -> list[dict]:
    if not text.strip():
        return []
    if client is None:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": text}],
    )
    raw = response.content[0].text
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Claude returned non-JSON output, skipping: %r", raw)
        return []

    findings = []
    for item in items:
        findings.append(
            {
                "pattern_type": item["pattern_type"],
                "confidence_score": float(item["confidence_score"]),
                "evidence_data": {"quote": item["quote"]},
            }
        )
    return findings
