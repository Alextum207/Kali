"""Small shared helpers for working with Anthropic Messages API responses."""


def extract_text(response) -> str:
    """Returns the first text block's content from a Messages API response.

    response.content[0] is NOT reliably a text block — a ThinkingBlock (or
    other non-text block) can come first, so blind index-0 access crashes
    with AttributeError ('ThinkingBlock' object has no attribute 'text').
    Returns "" if no text block is present at all."""
    return next((b.text for b in response.content if b.type == "text"), "")
