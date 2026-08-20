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
COUNTDOWN_HINTS = ("countdown", "timer", "deal-timer", "ablauf", "zaehler", "zähler")


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
        negated_a = any(kw in text_a.lower() for kw in _NEGATION_KEYWORDS)
        negated_b = any(kw in text_b.lower() for kw in _NEGATION_KEYWORDS)
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
