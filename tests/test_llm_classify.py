import json
import pytest
from app.analysis.llm_classify import classify_text


class _FakeMessage:
    def __init__(self, text):
        self.content = [type("Block", (), {"text": text, "type": "text"})]


class _FakeMessages:
    def __init__(self, response_text):
        self._response_text = response_text

    async def create(self, **kwargs):
        return _FakeMessage(self._response_text)


class _FakeClient:
    def __init__(self, response_text):
        self.messages = _FakeMessages(response_text)


@pytest.mark.asyncio
async def test_classify_text_parses_structured_response():
    fake_response = json.dumps([
        {"pattern_type": "Confirm Shaming", "confidence_score": 0.85, "quote": "No thanks, I hate saving money"}
    ])
    client = _FakeClient(fake_response)
    findings = await classify_text("No thanks, I hate saving money", client=client)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Confirm Shaming"
    assert findings[0]["confidence_score"] == 0.85
    assert findings[0]["evidence_data"]["quote"] == "No thanks, I hate saving money"


@pytest.mark.asyncio
async def test_classify_text_returns_empty_list_on_no_findings():
    client = _FakeClient("[]")
    findings = await classify_text("Welcome to our totally normal store.", client=client)
    assert findings == []
