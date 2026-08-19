import os
import pathlib
import pytest
from playwright.async_api import async_playwright
from app.crawler import crawl_page

FIXTURE_URL = pathlib.Path(__file__).parent.joinpath("fixtures/sample_page.html").as_uri()


@pytest.mark.asyncio
async def test_crawl_page_captures_dom_change_and_button_styles(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        result = await crawl_page(FIXTURE_URL, browser, har_dir=str(tmp_path))
        await browser.close()

    assert "initial" in result["dom_before"]
    assert "changed" in result["dom_after"]
    assert isinstance(result["screenshot"], bytes) and len(result["screenshot"]) > 0
    assert result["button_styles"] is not None
    assert result["button_styles"]["accept"]["width"] == 200
    assert result["button_styles"]["reject"]["width"] == 60

    assert isinstance(result["har_path"], str) and result["har_path"]
    assert os.path.exists(result["har_path"])
