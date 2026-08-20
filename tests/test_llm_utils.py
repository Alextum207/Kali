from app.llm_utils import extract_text


class _Block:
    def __init__(self, type_, text=None):
        self.type = type_
        if text is not None:
            self.text = text


def test_extract_text_returns_text_block_content():
    response = type("Resp", (), {"content": [_Block("text", "hello")]})()
    assert extract_text(response) == "hello"


def test_extract_text_skips_leading_thinking_block():
    """Regression test: a ThinkingBlock (extended thinking output) can come
    before the text block in response.content — response.content[0].text
    crashes with AttributeError in that case ('ThinkingBlock' object has no
    attribute 'text'). extract_text must skip past it."""
    response = type("Resp", (), {"content": [
        _Block("thinking"),  # no .text attribute at all, like a real ThinkingBlock
        _Block("text", "the actual answer"),
    ]})()
    assert extract_text(response) == "the actual answer"


def test_extract_text_returns_empty_string_when_no_text_block():
    response = type("Resp", (), {"content": [_Block("thinking")]})()
    assert extract_text(response) == ""
