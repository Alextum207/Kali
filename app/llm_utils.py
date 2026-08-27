"""Small shared helpers for working with Anthropic Messages API responses."""

import re

_JSON_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\n?|\n?```\s*$")


def extract_text(response) -> str:
    """Returns the first text block's content from a Messages API response.

    response.content[0] is NOT reliably a text block — a ThinkingBlock (or
    other non-text block) can come first, so blind index-0 access crashes
    with AttributeError ('ThinkingBlock' object has no attribute 'text').
    Returns "" if no text block is present at all."""
    return next((b.text for b in response.content if b.type == "text"), "")


def strip_json_fence(text: str) -> str:
    """Strips a Markdown code fence (```json ... ``` or ``` ... ```) wrapped
    around an LLM's JSON answer. Confirmed live (app/site_crawler.py's
    decide_next_interaction, temu.com scan): despite an explicit "answer
    with ONLY a JSON object" instruction, the model sometimes wraps its
    answer in a fence anyway (raw text
    '```json\\n{"type": "none"}\\n```') — json.loads on that raises
    "Expecting value: line 1 column 1 (char 0)" since a backtick isn't a
    valid JSON start character. A plain (unfenced) JSON string passes
    through unchanged."""
    return _JSON_FENCE_RE.sub("", text.strip()).strip()
