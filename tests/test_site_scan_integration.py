import pathlib

import pytest
from playwright.async_api import async_playwright

from app.db import init_db, get_pages, get_findings
from app.scan import run_site_scan

FAKE_SHOP_URL = pathlib.Path(__file__).parent.joinpath("fixtures/fake_shop/index.html").as_uri()


class _FakeBlock:
    def __init__(self, text):
        self.text = text
        self.type = "text"


class _FakeToolUseBlock:
    """Mimics an Anthropic tool_use content block, shaped like what
    llm_classify._extract_findings expects (block.type/name/input)."""

    def __init__(self, name, input_):
        self.type = "tool_use"
        self.name = name
        self.input = input_


class _FakeMessage:
    def __init__(self, content):
        # Accept either a single text block (str) or a list of pre-built
        # content blocks (e.g. a tool_use block).
        self.content = [_FakeBlock(content)] if isinstance(content, str) else content


class _StubLLMClient:
    """Deterministic stand-in for the Anthropic client: always says "no
    dark patterns" for text classification (via a real report_findings
    tool_use block, matching the schema-enforced contract), and always
    declines to interact further (so the crawl stays within the 5 fixture
    pages)."""

    class messages:
        @staticmethod
        async def create(**kwargs):
            prompt_text = str(kwargs.get("messages", [{}])[0].get("content", ""))
            if "AUSSCHLIESSLICH mit einem JSON-Objekt" in prompt_text:
                return _FakeMessage('{"type": "none"}')
            tools = kwargs.get("tools") or []
            if tools and tools[0].get("name") == "report_findings":
                return _FakeMessage(
                    [_FakeToolUseBlock("report_findings", {"findings": []})]
                )
            return _FakeMessage("[]")


@pytest.mark.asyncio
async def test_site_scan_end_to_end_across_fake_shop(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        conn = init_db(":memory:")

        scan_id = await run_site_scan(
            FAKE_SHOP_URL, conn, str(tmp_path), browser,
            max_pages=10, llm_client=_StubLLMClient(),
            url_validator=lambda url: None,  # file:// fixtures aren't http(s); bypass SSRF check for this local test
        )

        await browser.close()

    pages = get_pages(conn, scan_id)
    urls = {p["url"] for p in pages}
    assert FAKE_SHOP_URL in urls
    assert any("product.html" in u for u in urls)
    assert any("account.html" in u for u in urls)

    all_findings = get_findings(conn, scan_id)
    pattern_types = {f["pattern_type"] for f in all_findings}

    # Fake Urgency from product.html's countdown-timer class (heuristic, no LLM needed)
    assert "Fake Urgency" in pattern_types
    # Trick Questions from checkout.html's opposite-polarity checkboxes
    assert "Trick Questions" in pattern_types
    # Visuelle Tarnung from account.html's low-contrast cancellation clause
    assert "Visuelle Tarnung (Kontrast)" in pattern_types

    for f in all_findings:
        assert f["target_norm"] != "Unbekannt"
