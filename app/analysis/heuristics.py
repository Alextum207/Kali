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
        if "required" in box.attrs:
            continue  # a legally required checkbox isn't a dark pattern
        findings.append(
            {
                "pattern_type": "Pre-ticked Box",
                "confidence_score": 0.9,
                "evidence_data": {"selector": _selector_for(box)},
            }
        )
    return findings


COUNTDOWN_HINTS = ("countdown", "timer", "deal-timer")


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
