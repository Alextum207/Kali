import re

from bs4 import BeautifulSoup


def _selector_for(tag) -> str:
    if tag.get("id"):
        return f"#{tag['id']}"
    if tag.get("class"):
        return "." + ".".join(tag["class"])
    return tag.name


def find_preticked_checkboxes(dom_html: str) -> list[dict]:
    soup = BeautifulSoup(dom_html, "html.parser")
    findings = []
    for box in soup.find_all("input", {"type": "checkbox"}):
        if "checked" not in box.attrs:
            continue
        forced_required = "required" in box.attrs
        findings.append(
            {
                "pattern_type": "Pre-ticked Box",
                # A pre-ticked box marked `required` forces the user to keep
                # consent to proceed at all — more suspicious, not less.
                "confidence_score": 0.95 if forced_required else 0.9,
                "evidence_data": {
                    "selector": _selector_for(box),
                    "forced_required": forced_required,
                },
            }
        )
    return findings


# ponytail: CSS-Module-generated class name hashes (e.g., "Timer_abc123__label")
# and Shadow DOM countdowns are not detectable via class/id string matching alone —
# would need computed-style inspection. Left as-is; add if Computed-Styles data
# lands from crawl layer.
COUNTDOWN_HINTS = ("countdown", "timer", "deal-timer", "ablaufzeit", "restlaufzeit", "zaehler", "zähler")


def find_countdown_elements(dom_html: str) -> list[dict]:
    soup = BeautifulSoup(dom_html, "html.parser")
    findings = []
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class", []))
        tag_id = tag.get("id", "")
        haystack = f"{classes} {tag_id}".lower()
        if any(hint in haystack for hint in COUNTDOWN_HINTS):
            findings.append(
                {
                    "pattern_type": "Fake Urgency",
                    "confidence_score": 0.7,
                    "evidence_data": {"selector": _selector_for(tag)},
                }
            )
    return findings


_NEGATION_KEYWORDS = (
    "nicht",
    "kein",
    "keine",
    "ohne",
    "niemals",
    "verzicht",
    "verzichten",
    "not",
    "don't",
    "do not",
)

# Left-word-boundary matching (not plain substring) so e.g. "ohne" doesn't
# match mid-word inside words like "bewohnen" — routine German vocabulary on
# checkout/registration pages. No trailing \b, deliberately: German negation
# words conjugate/inflect ("verzicht" -> "verzichte"/"verzichtet") and a
# leading boundary is enough to rule out the false-positive substring case
# while still matching those suffixed forms.
_NEGATION_PATTERN = re.compile(
    "|".join(rf"\b{re.escape(kw)}" for kw in _NEGATION_KEYWORDS)
)


def _has_negation(text: str) -> bool:
    return bool(_NEGATION_PATTERN.search(text.lower()))


def _label_text_for(soup, box) -> str:
    box_id = box.get("id")
    if box_id:
        label = soup.find("label", {"for": box_id})
        if label:
            return label.get_text(strip=True)
    parent_label = box.find_parent("label")
    return parent_label.get_text(strip=True) if parent_label else ""


def find_trick_questions(dom_html: str) -> list[dict]:
    """Flags adjacent checkbox pairs whose labels switch polarity (one
    phrased as opt-in, the next as opt-out) — the classic "trick question"
    pattern where a consistent-looking checkbox list actually means the
    opposite of what a quick scan suggests."""
    soup = BeautifulSoup(dom_html, "html.parser")
    boxes = soup.find_all("input", {"type": "checkbox"})
    labeled = [(box, _label_text_for(soup, box)) for box in boxes]
    labeled = [(box, text) for box, text in labeled if text]

    findings = []
    for i in range(len(labeled) - 1):
        box_a, text_a = labeled[i]
        box_b, text_b = labeled[i + 1]
        negated_a = _has_negation(text_a)
        negated_b = _has_negation(text_b)
        if negated_a != negated_b:
            findings.append(
                {
                    "pattern_type": "Trick Questions",
                    "confidence_score": 0.65,
                    "evidence_data": {
                        "selector_a": _selector_for(box_a),
                        "selector_b": _selector_for(box_b),
                        "text_a": text_a,
                        "text_b": text_b,
                    },
                }
            )
    return findings


# Narrow, high-precision signal for a single checkbox whose own label text
# explicitly spells out that NOT checking it results in default consent —
# e.g. Mailchimp's sign-up checkbox: "I don't want to receive emails...
# By not checking the box, I agree to be opted in by default." Structurally
# different from find_trick_questions (needs two adjacent checkboxes with
# differing polarity) and find_preticked_checkboxes (needs `checked` set) —
# this one is unchecked and alone, the trick is purely in the wording.
# Deliberately narrow (both hint groups must co-occur) since a plain
# opt-out checkbox ("Ich möchte keine Werbung erhalten") never needs to
# state its own default-consequence — spelling that out is itself the tell.
_NOT_CHECKING_HINTS = (
    "not checking", "don't check", "do not check", "not check the box",
    "nicht ankreuzt", "nicht anklickst", "nicht aktivierst", "nicht markierst",
)
_DEFAULT_CONSENT_HINTS = (
    "by default", "automatically opted in", "automatically subscribed", "opted in by default",
    "automatisch angemeldet", "automatisch abonniert", "standardmäßig", "per voreinstellung", "voreingestellt",
)


def find_default_consent_checkboxes(dom_html: str) -> list[dict]:
    """Flags a single checkbox whose label text explicitly states that
    leaving it unchecked results in default consent — see module comment
    above for the Mailchimp example this mirrors."""
    soup = BeautifulSoup(dom_html, "html.parser")
    findings = []
    for box in soup.find_all("input", {"type": "checkbox"}):
        text = _label_text_for(soup, box).lower()
        if not text:
            continue
        if any(h in text for h in _NOT_CHECKING_HINTS) and any(h in text for h in _DEFAULT_CONSENT_HINTS):
            findings.append(
                {
                    "pattern_type": "Trick Questions",
                    "confidence_score": 0.85,
                    "evidence_data": {
                        "selector": _selector_for(box),
                        "quote": _label_text_for(soup, box),
                    },
                }
            )
    return findings


def find_autoplay_media(dom_html: str) -> list[dict]:
    soup = BeautifulSoup(dom_html, "html.parser")
    findings = []
    for tag in soup.find_all(("video", "audio")):
        if "autoplay" in tag.attrs:
            findings.append(
                {
                    "pattern_type": "Exploiting Addiction (Autoplay)",
                    "confidence_score": 0.6,
                    "evidence_data": {"selector": _selector_for(tag)},
                }
            )
    return findings


# ponytail: only catches "sibling containers each holding a price + a
# <ul>/<ol> of items" shape (div/li cards). Misses <table>-based pricing
# grids, CSS-grid layouts using <div> rows instead of <li>, prices split
# across multiple text nodes, and non-EUR currencies. Also takes the *last*
# price match in a container as "the" price, so strikethrough/original-price
# markup can pick the wrong number. Upgrade path: if false negatives show up
# on real scans, add a <table> row detector and a currency-agnostic amount
# regex; not worth building speculatively now.
_PRICE_PATTERN = re.compile(
    r"(?:€\s?(\d{1,3}(?:\.\d{3})*,\d{2})|"
    r"(\d{1,3}(?:\.\d{3})*,\d{2})\s?€|"
    r"EUR\s?(\d{1,3}(?:\.\d{3})*,\d{2})|"
    r"(\d{1,3}(?:\.\d{3})*,\d{2})\s?EUR)",
    re.IGNORECASE,
)


def _parse_price(match: re.Match) -> float:
    raw = next(g for g in match.groups() if g)
    return float(raw.replace(".", "").replace(",", "."))


def _tier_container(tag):
    """Walks up to 4 levels from a price-bearing tag to find the nearest
    ancestor that also contains a <ul>/<ol> with at least one <li> — the
    "tier container" for that price."""
    node = tag
    for _ in range(4):
        if node is None:
            return None
        list_tag = node.find(("ul", "ol"))
        if list_tag is not None and list_tag.find("li") is not None:
            return node, list_tag
        node = node.parent
    return None


def find_decoy_pricing(dom_html: str) -> list[dict]:
    soup = BeautifulSoup(dom_html, "html.parser")

    tiers = {}  # container tag id -> (container, price, value_count)
    for tag in soup.find_all(True):
        matches = list(_PRICE_PATTERN.finditer(tag.get_text()))
        if not matches:
            continue
        result = _tier_container(tag)
        if result is None:
            continue
        container, list_tag = result
        if id(container) in tiers:
            continue
        price = _parse_price(matches[-1])
        value_count = len(list_tag.find_all("li"))
        tiers[id(container)] = (container, price, value_count)

    # Only keep containers that are siblings of another tier container
    # (real pricing tables render as a row of sibling cards).
    by_parent: dict = {}
    for container, price, value_count in tiers.values():
        by_parent.setdefault(id(container.parent), []).append((container, price, value_count))

    findings = []
    for group in by_parent.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda t: t[1])
        for (cheaper, cheaper_price, cheaper_count), (pricier, pricier_price, pricier_count) in zip(
            group, group[1:]
        ):
            price_delta_pct = (pricier_price - cheaper_price) / cheaper_price
            value_ratio = pricier_count / max(cheaper_count, 1)
            if price_delta_pct <= 0.15 and value_ratio >= 3.0:
                findings.append(
                    {
                        "pattern_type": "Decoy Pricing",
                        "confidence_score": 0.6,
                        "evidence_data": {
                            "cheaper_selector": _selector_for(cheaper),
                            "pricier_selector": _selector_for(pricier),
                            "cheaper_price": cheaper_price,
                            "pricier_price": pricier_price,
                            "cheaper_value_count": cheaper_count,
                            "pricier_value_count": pricier_count,
                            "price_delta_pct": round(price_delta_pct, 3),
                            "value_ratio": round(value_ratio, 2),
                        },
                    }
                )
    return findings


# Schwellen für find_price_increase_in_flow: ein Preisanstieg zählt nur,
# wenn er sowohl relativ (5%) als auch absolut (0,50€) spürbar ist —
# reines Rundungsrauschen (z.B. 49,99€ -> 50,00€) soll nicht als Fund
# zählen.
_PRICE_INCREASE_MIN_PCT = 0.05
_PRICE_INCREASE_MIN_ABS = 0.50


def find_price_increase_in_flow(flow_group_pages: list[dict]) -> list[dict]:
    """Vergleicht die SUMME aller im Text gefundenen Preisnennungen (Proxy
    für 'was der Nutzer insgesamt zahlt', deckt genau den Fall ab, dass
    eine neue Position wie eine Servicegebühr erst auf einem späteren
    Schritt dazukommt — nicht nur einen einzelnen größten Betrag, der eine
    neue Zusatzzeile übersehen würde) zwischen dem ersten und jedem
    folgenden Schritt eines Checkout-Flows.

    ponytail: keine echte 'Gesamtsumme'-Semantik — wenn eine Seite denselben
    Preis zweimal anzeigt (z.B. Kachel + Zusammenfassung), zählt er doppelt;
    Upgrade-Pfad: ein <table>/Summenzeilen-Detektor, falls reale Scans zu
    viele Fehltreffer zeigen."""
    if len(flow_group_pages) < 2:
        return []

    def _sum_prices(dom_html: str) -> float | None:
        matches = list(_PRICE_PATTERN.finditer(dom_html))
        if not matches:
            return None
        return sum(_parse_price(m) for m in matches)

    baseline_price = _sum_prices(flow_group_pages[0]["dom_after"])
    if baseline_price is None:
        return []

    findings = []
    # reference_price tracks the last price a finding was raised against
    # (starts at the baseline) — comparing every later step back to the
    # ORIGINAL baseline would re-flag a step that's merely still elevated
    # by an already-reported fee (no *further* increase happened) as a
    # second, duplicate finding for the same underlying jump.
    reference_price = baseline_price
    for later_index in range(1, len(flow_group_pages)):
        later_price = _sum_prices(flow_group_pages[later_index]["dom_after"])
        if later_price is None:
            continue
        delta = later_price - reference_price
        if delta <= 0:
            continue
        # A genuinely free (0,00€) starting step — real for trial-then-fee
        # patterns — makes "percent increase" undefined; any real absolute
        # jump off a free baseline is significant on its own, so the
        # percentage gate is skipped rather than dividing by zero.
        delta_pct = (delta / reference_price) if reference_price > 0 else float("inf")
        if delta_pct < _PRICE_INCREASE_MIN_PCT or delta < _PRICE_INCREASE_MIN_ABS:
            continue
        findings.append(
            {
                "pattern_type": "Sneaking / Hidden Costs",
                "confidence_score": 0.75,
                "evidence_data": {
                    "note": (
                        f"Preis stieg von {baseline_price:.2f}€ (Schritt 1) auf "
                        f"{later_price:.2f}€ (Schritt {later_index + 1}) ohne "
                        "vorherige Offenlegung."
                    ),
                    "baseline_price": round(baseline_price, 2),
                    "later_price": round(later_price, 2),
                    "price_increase_pct": (
                        round((later_price - baseline_price) / baseline_price, 3) if baseline_price > 0 else None
                    ),
                    "baseline_page_index": 0,
                    "later_page_index": later_index,
                },
            }
        )
        reference_price = later_price
    return findings
