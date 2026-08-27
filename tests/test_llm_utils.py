from app.llm_utils import extract_text, strip_json_fence


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


def test_strip_json_fence_removes_json_labeled_fence():
    # Confirmed live (temu.com scan): the model sometimes answers
    # '```json\n{"type": "none"}\n```' despite being told to answer with
    # ONLY a JSON object — json.loads on the raw text raised "Expecting
    # value: line 1 column 1 (char 0)" since a backtick isn't a valid JSON
    # start character.
    assert strip_json_fence('```json\n{"type": "none"}\n```') == '{"type": "none"}'


def test_strip_json_fence_removes_unlabeled_fence():
    assert strip_json_fence('```\n{"type": "none"}\n```') == '{"type": "none"}'


def test_strip_json_fence_passes_through_plain_json_unchanged():
    assert strip_json_fence('{"type": "none"}') == '{"type": "none"}'
