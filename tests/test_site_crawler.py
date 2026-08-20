import pytest

from app.site_crawler import discover_links

DOM_WITH_LINKS = """
<html><body>
<a href="/products">Produkte</a>
<a href="https://checkout.example.com/pay">Zur Kasse</a>
<a href="https://external-tracker.com/pixel">Tracking</a>
<a href="#section">Anker</a>
<a href="mailto:info@example.com">Mail</a>
<a href="/products">Duplikat</a>
</body></html>
"""


def test_discover_links_filters_to_allowed_domain_and_subdomains():
    links = discover_links(DOM_WITH_LINKS, "https://www.example.com/", {"example.com"})
    assert "https://www.example.com/products" in links
    assert "https://checkout.example.com/pay" in links
    assert not any("external-tracker.com" in l for l in links)
    assert not any(l.startswith("#") for l in links)
    assert not any(l.startswith("mailto:") for l in links)


def test_discover_links_dedupes():
    links = discover_links(DOM_WITH_LINKS, "https://www.example.com/", {"example.com"})
    assert links.count("https://www.example.com/products") == 1


from app.site_crawler import classify_page_category


@pytest.mark.asyncio
async def test_classify_page_category_by_url_keyword():
    assert await classify_page_category("https://shop.example.com/checkout", "<h1>Kasse</h1>") == "checkout_payment"
    assert await classify_page_category("https://shop.example.com/konto/abo", "<h1>Mein Abo</h1>") == "account_subscription"
    assert await classify_page_category("https://shop.example.com/p/sneaker-123", "<h1>Sneaker</h1>") == "product_category"


@pytest.mark.asyncio
async def test_classify_page_category_falls_back_to_other_without_llm():
    assert await classify_page_category("https://shop.example.com/about-us", "<h1>Über uns</h1>") == "other"


class _FakeBlock:
    def __init__(self, text):
        self.text = text
        self.type = "text"


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, response_text):
        self._response_text = response_text

    async def create(self, **kwargs):
        return _FakeMessage(self._response_text)


class _FakeClient:
    def __init__(self, response_text):
        self.messages = _FakeMessages(response_text)


@pytest.mark.asyncio
async def test_classify_page_category_uses_llm_fallback_for_ambiguous_pages():
    client = _FakeClient("popup_leadform")
    result = await classify_page_category("https://shop.example.com/about-us", "<h1>Über uns</h1>", llm_client=client)
    assert result == "popup_leadform"


@pytest.mark.asyncio
async def test_classify_page_category_llm_failure_falls_back_to_other():
    class _BrokenClient:
        class messages:
            @staticmethod
            async def create(**kwargs):
                raise RuntimeError("API down")

    result = await classify_page_category("https://shop.example.com/about-us", "<h1>Über uns</h1>", llm_client=_BrokenClient())
    assert result == "other"


from app.site_crawler import decide_next_interaction

CLICKABLE_ELEMENTS = [
    {"text": "Startseite", "selector": "nav a#home"},
    {"text": "In den Warenkorb", "selector": "button#add-to-cart"},
    {"text": "Impressum", "selector": "footer a#imprint"},
]


@pytest.mark.asyncio
async def test_decide_next_interaction_returns_llm_choice_for_relevant_category():
    client = _FakeClient('{"type": "click", "target": "button#add-to-cart"}')
    result = await decide_next_interaction("product_category", CLICKABLE_ELEMENTS, llm_client=client)
    assert result == {"type": "click", "target": "button#add-to-cart"}


@pytest.mark.asyncio
async def test_decide_next_interaction_returns_none_when_llm_says_none():
    client = _FakeClient('{"type": "none"}')
    result = await decide_next_interaction("product_category", CLICKABLE_ELEMENTS, llm_client=client)
    assert result is None


@pytest.mark.asyncio
async def test_decide_next_interaction_returns_none_without_llm_client():
    assert await decide_next_interaction("product_category", CLICKABLE_ELEMENTS, llm_client=None) is None


@pytest.mark.asyncio
async def test_decide_next_interaction_returns_none_for_categories_without_a_goal():
    client = _FakeClient('{"type": "click", "target": "button#add-to-cart"}')
    assert await decide_next_interaction("cookie_consent", CLICKABLE_ELEMENTS, llm_client=client) is None
    assert await decide_next_interaction("other", CLICKABLE_ELEMENTS, llm_client=client) is None


@pytest.mark.asyncio
async def test_decide_next_interaction_returns_none_on_llm_failure():
    class _BrokenClient:
        class messages:
            @staticmethod
            async def create(**kwargs):
                raise RuntimeError("API down")

    result = await decide_next_interaction("product_category", CLICKABLE_ELEMENTS, llm_client=_BrokenClient())
    assert result is None


import pathlib
from playwright.async_api import async_playwright
from app.crawler import CaptchaRequiredError
from app.site_crawler import crawl_site

CAPTCHA_START_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/site_captcha_start/index.html"
).as_uri()
CAPTCHA_SUBPAGE_START_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/site_captcha_subpage/index.html"
).as_uri()


@pytest.mark.asyncio
async def test_crawl_site_raises_when_start_page_looks_like_captcha(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            with pytest.raises(CaptchaRequiredError) as exc_info:
                await crawl_site(
                    CAPTCHA_START_URL, browser, max_pages=5, har_dir=str(tmp_path),
                    url_validator=lambda url: None,
                )
        finally:
            await browser.close()

    assert exc_info.value.url == CAPTCHA_START_URL


@pytest.mark.asyncio
async def test_crawl_site_ignores_captcha_marker_on_a_subpage(tmp_path):
    """Only the start page is checked — a captcha marker discovered deeper
    in the crawl doesn't abort the whole scan (that page just fails to load
    meaningfully like any other unusual page, same as today)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        result = await crawl_site(
            CAPTCHA_SUBPAGE_START_URL, browser, max_pages=5, har_dir=str(tmp_path),
            url_validator=lambda url: None,
        )
        await browser.close()

    urls = {p["url"] for p in result["pages"]}
    assert CAPTCHA_SUBPAGE_START_URL in urls
    assert any("page2.html" in u for u in urls)


TWO_PAGE_SITE_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/site_two_pages/index.html"
).as_uri()


@pytest.mark.asyncio
async def test_crawl_site_follows_same_directory_links_up_to_max_pages(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        result = await crawl_site(
            TWO_PAGE_SITE_URL, browser, max_pages=5, har_dir=str(tmp_path),
            url_validator=lambda url: None,  # file:// fixtures aren't http(s); bypass SSRF check for this local test
        )
        await browser.close()

    urls = {p["url"] for p in result["pages"]}
    assert TWO_PAGE_SITE_URL in urls
    assert any("page2.html" in u for u in urls)
    assert len(result["pages"]) <= 5
    assert result["har_path"].endswith(".har")
    assert all("category" in p for p in result["pages"])


@pytest.mark.asyncio
async def test_crawl_site_respects_max_pages_limit(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        result = await crawl_site(
            TWO_PAGE_SITE_URL, browser, max_pages=1, har_dir=str(tmp_path),
            url_validator=lambda url: None,
        )
        await browser.close()

    assert len(result["pages"]) == 1
    assert result["pages"][0]["url"] == TWO_PAGE_SITE_URL


@pytest.mark.asyncio
async def test_crawl_site_stops_discovering_when_time_budget_exceeded(tmp_path):
    # 1.0s is comfortably longer than browser/context startup (so the start
    # page is still visited) but shorter than that one page's own processing
    # time (_snapshot_page's fixed 1.5s dom-diff sleep alone exceeds it), so
    # the budget check at the top of the *next* iteration stops the crawl.
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        result = await crawl_site(
            TWO_PAGE_SITE_URL, browser, max_pages=20, har_dir=str(tmp_path),
            url_validator=lambda url: None, time_budget_seconds=1.0,
        )
        await browser.close()

    assert len(result["pages"]) == 1  # only the start page — budget exhausted before discovering more


@pytest.mark.asyncio
async def test_crawl_site_default_validator_rejects_unsafe_discovered_links(tmp_path, monkeypatch):
    def fake_discover_links(dom_html, base_url, allowed_hosts):
        return ["http://127.0.0.1:9/internal"]  # loopback — must be rejected

    monkeypatch.setattr("app.site_crawler.discover_links", fake_discover_links)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        # Note: no url_validator override here — exercises the real default
        # (validate_scan_url), which also rejects file:// for the start URL's
        # discovered "children" the same way it would reject a loopback IP.
        result = await crawl_site(
            TWO_PAGE_SITE_URL, browser, max_pages=5, har_dir=str(tmp_path)
        )
        await browser.close()

    urls = {p["url"] for p in result["pages"]}
    assert "http://127.0.0.1:9/internal" not in urls
    assert len(result["pages"]) == 1  # only the start page — the discovered link was rejected


# --- Kategorie-fokussierter Crawl: Queue-Priorisierung + Flow-Walk ---

PRIORITY_SITE_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/site_priority/index.html"
).as_uri()

FLOW_CHECKOUT_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/site_flow_checkout/checkout/step1.html"
).as_uri()

FLOW_CATEGORY_CHANGE_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/site_flow_leaves_target/checkout/step1.html"
).as_uri()

FLOW_LOOP_URL = pathlib.Path(__file__).parent.joinpath(
    "fixtures/site_flow_loop/checkout/a.html"
).as_uri()


class _SequentialFakeClient:
    """Like _FakeClient, but returns a different scripted response per call
    — needed to drive a multi-step decide_next_interaction flow (click,
    then eventually 'none')."""

    class _Messages:
        def __init__(self, outer):
            self._outer = outer

        async def create(self, **kwargs):
            idx = min(self._outer.calls, len(self._outer._responses) - 1)
            self._outer.calls += 1
            return _FakeMessage(self._outer._responses[idx])

    def __init__(self, response_texts):
        self._responses = list(response_texts)
        self.calls = 0
        self.messages = self._Messages(self)


@pytest.mark.asyncio
async def test_crawl_site_prioritizes_target_category_links_over_other(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        result = await crawl_site(
            PRIORITY_SITE_URL, browser, max_pages=2, har_dir=str(tmp_path),
            url_validator=lambda url: None,
        )
        await browser.close()

    urls = {p["url"] for p in result["pages"]}
    assert PRIORITY_SITE_URL in urls
    assert any("checkout/start.html" in u for u in urls)
    assert not any("about.html" in u for u in urls)  # deprioritized, budget ran out first


@pytest.mark.asyncio
async def test_crawl_site_walks_category_flow_across_pages_until_no_interaction(tmp_path):
    client = _SequentialFakeClient([
        '{"type": "click", "target": "a#next"}',  # step1 -> step2
        '{"type": "none"}',  # step2: flow goal reached
    ])
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        result = await crawl_site(
            FLOW_CHECKOUT_URL, browser, max_pages=5, har_dir=str(tmp_path),
            llm_client=client, url_validator=lambda url: None,
        )
        await browser.close()

    urls = [p["url"] for p in result["pages"]]
    assert len(urls) == 2
    assert "step1.html" in urls[0]
    assert "step2.html" in urls[1]
    assert all(p["category"] == "checkout_payment" for p in result["pages"])


@pytest.mark.asyncio
async def test_crawl_site_flow_stops_when_category_changes(tmp_path):
    client = _SequentialFakeClient([
        '{"type": "click", "target": "a#next"}',  # step1 (checkout) -> imprint (other)
    ])
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        result = await crawl_site(
            FLOW_CATEGORY_CHANGE_URL, browser, max_pages=5, har_dir=str(tmp_path),
            llm_client=client, url_validator=lambda url: None,
        )
        await browser.close()

    assert len(result["pages"]) == 2
    assert result["pages"][0]["category"] == "checkout_payment"
    assert result["pages"][1]["category"] == "other"


@pytest.mark.asyncio
async def test_crawl_site_flow_has_a_safety_cap_against_loops(tmp_path):
    # Always offers the same click target — a.html and b.html link back and
    # forth to each other forever without MAX_FLOW_STEPS.
    client = _FakeClient('{"type": "click", "target": "a#next"}')
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        result = await crawl_site(
            FLOW_LOOP_URL, browser, max_pages=20, har_dir=str(tmp_path),
            llm_client=client, url_validator=lambda url: None,
        )
        await browser.close()

    from app.site_crawler import MAX_FLOW_STEPS

    assert len(result["pages"]) <= MAX_FLOW_STEPS + 1
    assert len(result["pages"]) < 20  # proves the cap fired, not max_pages
