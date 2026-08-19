import json
import logging
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def discover_links(dom_html: str, base_url: str, allowed_hosts: set[str]) -> list[str]:
    """Extracts internal navigation links from a page. Filters to
    `allowed_hosts` (exact match or subdomain), drops anchors/mailto/tel/js
    links, and dedupes. Does NOT enforce http(s)-only or SSRF safety — that
    is `app.url_safety.validate_scan_url`'s job, applied by the caller
    before navigating to any of these URLs."""
    soup = BeautifulSoup(dom_html, "html.parser")
    seen: set[str] = set()
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href).split("#")[0]
        parsed = urlparse(absolute)
        host = parsed.hostname or ""
        if not any(host == h or host.endswith("." + h) for h in allowed_hosts):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)
    return links


PAGE_CATEGORIES = (
    "cookie_consent",
    "checkout_payment",
    "product_category",
    "account_subscription",
    "popup_leadform",
    "other",
)

_CATEGORY_KEYWORDS = {
    "checkout_payment": ("checkout", "kasse", "warenkorb", "cart", "bestellung", "payment", "zahlung"),
    "account_subscription": ("/account", "/konto", "subscription", "kündig", "cancel", "mein abo"),
    "product_category": ("product", "produkt", "/p/", "kategorie", "category"),
}


def _llm_classify_category(url: str, dom_html: str, client) -> str:
    import re

    text_sample = re.sub(r"<[^>]+>", " ", dom_html)[:1500]
    prompt = (
        "Klassifiziere folgende Webseite in genau eine Kategorie: "
        "cookie_consent, checkout_payment, product_category, account_subscription, "
        "popup_leadform, other. Antworte NUR mit dem Kategorie-Namen, nichts sonst.\n\n"
        f"URL: {url}\n\nSeiteninhalt (Auszug): {text_sample}"
    )
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=20,
        messages=[{"role": "user", "content": prompt}],
    )
    result = response.content[0].text.strip().lower()
    return result if result in PAGE_CATEGORIES else "other"


def classify_page_category(url: str, dom_html: str, llm_client=None) -> str:
    haystack = url.lower()
    soup = BeautifulSoup(dom_html, "html.parser")
    heading = soup.find(["h1", "h2"])
    if heading:
        haystack += " " + heading.get_text(strip=True).lower()

    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return category

    if llm_client is not None:
        try:
            return _llm_classify_category(url, dom_html, llm_client)
        except Exception as exc:  # noqa: BLE001 - deliberate broad catch, LLM call
            logger.warning("LLM category classification failed, using 'other': %s", exc)

    return "other"


# One-line navigation goal per category; categories not listed here (or
# mapped to None) get no LLM-driven interaction — cookie_consent is already
# handled by apply_consent_rules, "other" has no specific journey to drive.
_INTERACTION_GOALS = {
    "checkout_payment": (
        "Klicke dich bis zum letzten Schritt vor der Zahlung durch "
        "(z.B. 'Weiter', 'Zur Kasse', 'Warenkorb ansehen'), aber löse "
        "NIEMALS eine echte Zahlung aus."
    ),
    "account_subscription": (
        "Suche einen Kündigungs- oder Konto-löschen-Link/Button und "
        "klicke ihn an, aber bestätige die Kündigung NICHT endgültig."
    ),
    "product_category": "Klicke auf ein Produkt und danach auf 'In den Warenkorb', falls vorhanden.",
    "popup_leadform": "Klicke den Schließen-Button (X) des Overlays, falls vorhanden.",
}


def decide_next_interaction(category: str, clickable_elements: list[dict], llm_client=None) -> dict | None:
    goal = _INTERACTION_GOALS.get(category)
    if not goal or not clickable_elements or llm_client is None:
        return None

    elements_text = "\n".join(
        f'- "{el["text"]}" (selector: {el["selector"]})' for el in clickable_elements[:40]
    )
    prompt = (
        f"Ziel: {goal}\n\n"
        f"Anklickbare Elemente auf der aktuellen Seite:\n{elements_text}\n\n"
        'Antworte AUSSCHLIESSLICH mit einem JSON-Objekt {"type": "click", "target": "<selector>"} '
        'für das nächste sinnvolle Element, oder {"type": "none"}, falls kein Element zum Ziel passt.'
    )
    try:
        response = llm_client.messages.create(
            model="claude-sonnet-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        result = json.loads(response.content[0].text)
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, LLM call
        logger.warning("decide_next_interaction failed, skipping: %s", exc)
        return None

    if result.get("type") == "click" and result.get("target"):
        return {"type": "click", "target": result["target"]}
    return None
