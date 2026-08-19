from app.analysis.heuristics import (
    find_preticked_checkboxes,
    find_countdown_elements,
    find_trick_questions,
    find_autoplay_media,
)

PRETICKED_HTML = """
<form>
  <input type="checkbox" id="newsletter" checked>
  <input type="checkbox" id="required" checked required>
</form>
"""

COUNTDOWN_HTML = """
<div class="countdown-timer" id="deal-timer">00:14:59</div>
"""

TRICK_QUESTION_HTML = """
<form>
  <input type="checkbox" id="newsletter">
  <label for="newsletter">Bitte ankreuzen, wenn Sie Angebote erhalten möchten</label>
  <input type="checkbox" id="tracking" checked>
  <label for="tracking">Bitte NICHT ankreuzen, wenn Sie Tracking ablehnen</label>
</form>
"""

CONSISTENT_CHECKBOXES_HTML = """
<form>
  <input type="checkbox" id="a"><label for="a">Newsletter abonnieren</label>
  <input type="checkbox" id="b"><label for="b">SMS-Updates abonnieren</label>
</form>
"""

AUTOPLAY_HTML = """
<video id="hero-video" autoplay></video>
<audio id="bg-audio" autoplay></audio>
<video id="manual-video"></video>
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


def test_find_trick_questions_flags_opposite_polarity_labels():
    findings = find_trick_questions(TRICK_QUESTION_HTML)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Trick Questions"
    assert findings[0]["evidence_data"]["selector_a"] == "#newsletter"
    assert findings[0]["evidence_data"]["selector_b"] == "#tracking"


def test_find_trick_questions_ignores_consistent_polarity():
    assert find_trick_questions(CONSISTENT_CHECKBOXES_HTML) == []


def test_find_autoplay_media_flags_autoplay_attribute():
    findings = find_autoplay_media(AUTOPLAY_HTML)
    selectors = {f["evidence_data"]["selector"] for f in findings}
    assert selectors == {"#hero-video", "#bg-audio"}
    assert all(f["pattern_type"] == "Exploiting Addiction (Autoplay)" for f in findings)
