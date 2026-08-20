import json
import logging
import os
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

_EXAMPLES_PATH = Path(__file__).resolve().parents[2] / "data" / "mathur_examples.json"

# The 10 pattern_type values the LLM path can produce (enforced via the
# report_findings tool schema below). The rest of app.compliance.NORM_MAP's
# entries are either produced only by heuristics (app/analysis/heuristics.py,
# app/analysis/readability.py, app/analysis/visual.py, app/crawler.py,
# app/scan.py) or are unused dead entries — never sent through this enum.
PATTERN_TYPES = [
    "Fake Urgency",
    "Fake Scarcity",
    "Fake Social Proof",
    "Confirm Shaming",
    "Sneaking / Hidden Costs",
    "Forced Continuity",
    "Decoy Pricing",
    "Nagging",
    "Roach Motel",
    "Forced Path",
]

SYSTEM_PROMPT = """Du bist ein Klassifikator für manipulative UX-Texte (Dark Patterns).
Nutze das Tool "report_findings", um jeden gefundenen Dark Pattern im Text zu
melden. Melde eine leere findings-Liste, wenn der Text keine Dark Patterns
enthält.

Beispiele:
"""

_TOOL_SCHEMA = {
    "name": "report_findings",
    "description": "Meldet die im Text gefundenen Dark Patterns.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "pattern_type": {"type": "string", "enum": PATTERN_TYPES},
                        "confidence_score": {"type": "number"},
                        "quote": {
                            "type": "string",
                            "description": "Wörtliches Zitat aus dem Text, das den Fund belegt.",
                        },
                    },
                    "required": ["pattern_type", "confidence_score", "quote"],
                },
            }
        },
        "required": ["findings"],
    },
}


def _build_system_prompt() -> str:
    examples = json.loads(_EXAMPLES_PATH.read_text(encoding="utf-8"))
    lines = [SYSTEM_PROMPT]
    for ex in examples:
        lines.append(f'- "{ex["text"]}" -> {ex["pattern_type"]}')
    return "\n".join(lines)


def _extract_findings(response) -> list[dict]:
    """Pulls the report_findings tool_use block's input out of a Messages
    API response. Iterates response.content defensively instead of
    assuming content[0] is it — even with tool_choice forcing this tool, a
    text preamble block can precede it."""
    for block in response.content:
        if block.type == "tool_use" and block.name == "report_findings":
            items = block.input.get("findings", [])
            return [
                {
                    "pattern_type": item["pattern_type"],
                    "confidence_score": max(0.0, min(1.0, float(item["confidence_score"]))),
                    "evidence_data": {"quote": item["quote"]},
                }
                for item in items
            ]
    raise ValueError("no report_findings tool_use block in response")


async def classify_text(text: str, client=None) -> list[dict]:
    if not text.strip():
        return []
    if client is None:
        client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    system_prompt = _build_system_prompt()
    for attempt in range(2):
        try:
            response = await client.messages.create(
                model="claude-sonnet-5",
                max_tokens=1024,
                system=system_prompt,
                tools=[_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": "report_findings"},
                messages=[{"role": "user", "content": text}],
            )
            return _extract_findings(response)
        except Exception as exc:  # noqa: BLE001 - transient API/parse error, retried once
            logger.warning("classify_text attempt %d failed: %s", attempt + 1, exc)
    return []
