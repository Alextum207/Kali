import pytest
from app.analysis.llm_classify import classify_text


def _tool_use_block(findings):
    return type(
        "Block",
        (),
        {"type": "tool_use", "name": "report_findings", "input": {"findings": findings}},
    )()


def _text_block(text):
    return type("Block", (), {"type": "text", "text": text})()


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, content, exc=None):
        self._content = content
        self._exc = exc
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return _FakeMessage(self._content)


class _FakeClient:
    def __init__(self, content=None, exc=None):
        self.messages = _FakeMessages(content, exc=exc)


@pytest.mark.asyncio
async def test_classify_text_parses_structured_response():
    content = [
        _tool_use_block(
            [{"pattern_type": "Confirm Shaming", "confidence_score": 0.85, "quote": "No thanks, I hate saving money"}]
        )
    ]
    client = _FakeClient(content=content)
    findings = await classify_text("No thanks, I hate saving money", client=client)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Confirm Shaming"
    assert findings[0]["confidence_score"] == 0.85
    assert findings[0]["evidence_data"]["quote"] == "No thanks, I hate saving money"


@pytest.mark.asyncio
async def test_classify_text_returns_empty_list_on_no_findings():
    client = _FakeClient(content=[_tool_use_block([])])
    findings = await classify_text("Welcome to our totally normal store.", client=client)
    assert findings == []


@pytest.mark.asyncio
async def test_classify_text_skips_text_preamble_before_tool_use():
    """A text block can precede the tool_use block even with tool_choice
    forcing the tool — must not assume content[0] is the tool_use block."""
    content = [
        _text_block("Sicher, hier ist meine Analyse:"),
        _tool_use_block(
            [{"pattern_type": "Nagging", "confidence_score": 0.6, "quote": "Jetzt upgraden!"}]
        ),
    ]
    client = _FakeClient(content=content)
    findings = await classify_text("Jetzt upgraden!", client=client)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Nagging"


@pytest.mark.asyncio
async def test_classify_text_clamps_out_of_range_confidence():
    content = [
        _tool_use_block(
            [
                {"pattern_type": "Nagging", "confidence_score": 1.5, "quote": "a"},
                {"pattern_type": "Roach Motel", "confidence_score": -0.2, "quote": "b"},
            ]
        )
    ]
    client = _FakeClient(content=content)
    findings = await classify_text("some text", client=client)
    assert findings[0]["confidence_score"] == 1.0
    assert findings[1]["confidence_score"] == 0.0


@pytest.mark.asyncio
async def test_classify_text_retries_once_then_succeeds():
    good_content = [
        _tool_use_block([{"pattern_type": "Fake Urgency", "confidence_score": 0.5, "quote": "x"}])
    ]

    class _FlakyMessages:
        def __init__(self):
            self.calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient API error")
            return _FakeMessage(good_content)

    class _FlakyClient:
        def __init__(self):
            self.messages = _FlakyMessages()

    client = _FlakyClient()
    findings = await classify_text("some text", client=client)
    assert client.messages.calls == 2
    assert findings[0]["pattern_type"] == "Fake Urgency"


@pytest.mark.asyncio
async def test_classify_text_returns_empty_list_after_two_failed_attempts():
    client = _FakeClient(exc=RuntimeError("still broken"))
    findings = await classify_text("some text", client=client)
    assert findings == []
    assert client.messages.calls == 2
