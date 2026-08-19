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


def test_classify_page_category_by_url_keyword():
    assert classify_page_category("https://shop.example.com/checkout", "<h1>Kasse</h1>") == "checkout_payment"
    assert classify_page_category("https://shop.example.com/konto/abo", "<h1>Mein Abo</h1>") == "account_subscription"
    assert classify_page_category("https://shop.example.com/p/sneaker-123", "<h1>Sneaker</h1>") == "product_category"


def test_classify_page_category_falls_back_to_other_without_llm():
    assert classify_page_category("https://shop.example.com/about-us", "<h1>Über uns</h1>") == "other"


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, response_text):
        self._response_text = response_text

    def create(self, **kwargs):
        return _FakeMessage(self._response_text)


class _FakeClient:
    def __init__(self, response_text):
        self.messages = _FakeMessages(response_text)


def test_classify_page_category_uses_llm_fallback_for_ambiguous_pages():
    client = _FakeClient("popup_leadform")
    result = classify_page_category("https://shop.example.com/about-us", "<h1>Über uns</h1>", llm_client=client)
    assert result == "popup_leadform"


def test_classify_page_category_llm_failure_falls_back_to_other():
    class _BrokenClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("API down")

    result = classify_page_category("https://shop.example.com/about-us", "<h1>Über uns</h1>", llm_client=_BrokenClient())
    assert result == "other"


from app.site_crawler import decide_next_interaction

CLICKABLE_ELEMENTS = [
    {"text": "Startseite", "selector": "nav a#home"},
    {"text": "In den Warenkorb", "selector": "button#add-to-cart"},
    {"text": "Impressum", "selector": "footer a#imprint"},
]


def test_decide_next_interaction_returns_llm_choice_for_relevant_category():
    client = _FakeClient('{"type": "click", "target": "button#add-to-cart"}')
    result = decide_next_interaction("product_category", CLICKABLE_ELEMENTS, llm_client=client)
    assert result == {"type": "click", "target": "button#add-to-cart"}


def test_decide_next_interaction_returns_none_when_llm_says_none():
    client = _FakeClient('{"type": "none"}')
    result = decide_next_interaction("product_category", CLICKABLE_ELEMENTS, llm_client=client)
    assert result is None


def test_decide_next_interaction_returns_none_without_llm_client():
    assert decide_next_interaction("product_category", CLICKABLE_ELEMENTS, llm_client=None) is None


def test_decide_next_interaction_returns_none_for_categories_without_a_goal():
    client = _FakeClient('{"type": "click", "target": "button#add-to-cart"}')
    assert decide_next_interaction("cookie_consent", CLICKABLE_ELEMENTS, llm_client=client) is None
    assert decide_next_interaction("other", CLICKABLE_ELEMENTS, llm_client=client) is None


def test_decide_next_interaction_returns_none_on_llm_failure():
    class _BrokenClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("API down")

    result = decide_next_interaction("product_category", CLICKABLE_ELEMENTS, llm_client=_BrokenClient())
    assert result is None
