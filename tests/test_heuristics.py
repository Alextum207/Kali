from app.analysis.heuristics import find_preticked_checkboxes, find_countdown_elements

PRETICKED_HTML = """
<form>
  <input type="checkbox" id="newsletter" checked>
  <input type="checkbox" id="required" checked required>
</form>
"""

COUNTDOWN_HTML = """
<div class="countdown-timer" id="deal-timer">00:14:59</div>
"""


def test_find_preticked_checkboxes_ignores_required_ones():
    findings = find_preticked_checkboxes(PRETICKED_HTML)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Pre-ticked Box"
    assert findings[0]["evidence_data"]["selector"] == "#newsletter"


def test_find_countdown_elements():
    findings = find_countdown_elements(COUNTDOWN_HTML)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Fake Urgency"
    assert findings[0]["evidence_data"]["selector"] == "#deal-timer"
