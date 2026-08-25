from app.analysis.heuristics import (
    find_preticked_checkboxes,
    find_countdown_elements,
    find_trick_questions,
    find_default_consent_checkboxes,
    find_autoplay_media,
    find_decoy_pricing,
    find_price_increase_in_flow,
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


def test_find_preticked_checkboxes_flags_required_ones_with_higher_confidence():
    findings = find_preticked_checkboxes(PRETICKED_HTML)
    assert len(findings) == 2
    by_selector = {f["evidence_data"]["selector"]: f for f in findings}

    non_required = by_selector["#newsletter"]
    assert non_required["pattern_type"] == "Pre-ticked Box"
    assert non_required["confidence_score"] == 0.9
    assert non_required["evidence_data"]["forced_required"] is False

    required = by_selector["#required"]
    assert required["confidence_score"] == 0.95
    assert required["evidence_data"]["forced_required"] is True


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


EXTENDED_NEGATION_HTML = """
<form>
  <input type="checkbox" id="a">
  <label for="a">Ich moechte Angebote erhalten</label>
  <input type="checkbox" id="b" checked>
  <label for="b">Ich verzichte auf personalisierte Werbung</label>
</form>
"""


def test_find_trick_questions_detects_extended_negation_keywords():
    findings = find_trick_questions(EXTENDED_NEGATION_HTML)
    assert len(findings) == 1
    assert findings[0]["evidence_data"]["selector_b"] == "#b"


MAILCHIMP_STYLE_HTML = """
<form>
  <input type="checkbox" id="marketing">
  <label for="marketing">I don't want to receive emails about product updates,
    marketing best practices, and promotions. By not checking the box, I agree
    to be opted in by default.</label>
</form>
"""

PLAIN_OPT_OUT_HTML = """
<form>
  <input type="checkbox" id="newsletter">
  <label for="newsletter">Ich möchte keine Werbung per E-Mail erhalten.</label>
</form>
"""


def test_find_default_consent_checkboxes_flags_mailchimp_style_wording():
    findings = find_default_consent_checkboxes(MAILCHIMP_STYLE_HTML)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Trick Questions"
    assert findings[0]["evidence_data"]["selector"] == "#marketing"


def test_find_default_consent_checkboxes_ignores_plain_opt_out():
    """A normal opt-out checkbox that never states its own default
    consequence must not be flagged — only the explicit "not checking =
    default consent" wording is the tell (see module docstring)."""
    assert find_default_consent_checkboxes(PLAIN_OPT_OUT_HTML) == []


def test_find_autoplay_media_flags_autoplay_attribute():
    findings = find_autoplay_media(AUTOPLAY_HTML)
    selectors = {f["evidence_data"]["selector"] for f in findings}
    assert selectors == {"#hero-video", "#bg-audio"}
    assert all(f["pattern_type"] == "Exploiting Addiction (Autoplay)" for f in findings)


DECOY_PRICING_HTML = """
<div class="pricing-row">
  <div class="plan" id="basic">
    <p>Basic-Paket: 9,99€</p>
    <ul><li>Feature A</li></ul>
  </div>
  <div class="plan" id="pro">
    <p>Pro-Paket: 10,99€</p>
    <ul>
      <li>Feature A</li><li>Feature B</li><li>Feature C</li><li>Feature D</li>
      <li>Feature E</li><li>Feature F</li><li>Feature G</li><li>Feature H</li>
      <li>Feature I</li><li>Feature J</li><li>Feature K</li><li>Feature L</li>
      <li>Feature M</li><li>Feature N</li><li>Feature O</li>
    </ul>
  </div>
</div>
"""

PROPORTIONAL_PRICING_HTML = """
<div class="pricing-row">
  <div class="plan" id="basic">
    <p>Basic-Paket: 9,99€</p>
    <ul><li>Feature A</li><li>Feature B</li></ul>
  </div>
  <div class="plan" id="premium">
    <p>Premium-Paket: 14,99€</p>
    <ul><li>Feature A</li><li>Feature B</li><li>Feature C</li><li>Feature D</li></ul>
  </div>
</div>
"""

SINGLE_TIER_HTML = """
<div class="pricing-row">
  <div class="plan" id="only"><p>9,99€</p><ul><li>Feature A</li></ul></div>
</div>
"""

NO_PRICE_HTML = """
<div class="pricing-row">
  <div class="plan"><p>Kontaktieren Sie uns</p><ul><li>Feature A</li></ul></div>
  <div class="plan"><p>Individuell</p><ul><li>Feature A</li><li>Feature B</li></ul></div>
</div>
"""


def test_find_decoy_pricing_flags_asymmetric_dominance():
    findings = find_decoy_pricing(DECOY_PRICING_HTML)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["pattern_type"] == "Decoy Pricing"
    assert finding["confidence_score"] == 0.6
    assert finding["evidence_data"]["cheaper_price"] == 9.99
    assert finding["evidence_data"]["pricier_price"] == 10.99
    assert finding["evidence_data"]["cheaper_value_count"] == 1
    assert finding["evidence_data"]["pricier_value_count"] == 15


def test_find_decoy_pricing_ignores_proportional_tiers():
    assert find_decoy_pricing(PROPORTIONAL_PRICING_HTML) == []


def test_find_decoy_pricing_single_tier_no_finding():
    assert find_decoy_pricing(SINGLE_TIER_HTML) == []


def test_find_decoy_pricing_no_currency_no_finding():
    assert find_decoy_pricing(NO_PRICE_HTML) == []


def test_find_price_increase_in_flow_flags_hidden_fee_added_later():
    flow_pages = [
        {"dom_after": "<p>Preis: 49,99 €</p>"},
        {"dom_after": "<p>Zwischensumme: 49,99 €</p><p>Servicegebühr: 6,99 €</p>"},
    ]
    findings = find_price_increase_in_flow(flow_pages)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["pattern_type"] == "Sneaking / Hidden Costs"
    assert finding["evidence_data"]["baseline_price"] == 49.99
    assert finding["evidence_data"]["later_price"] == 56.98
    assert finding["evidence_data"]["baseline_page_index"] == 0
    assert finding["evidence_data"]["later_page_index"] == 1


def test_find_price_increase_in_flow_ignores_stable_price():
    flow_pages = [
        {"dom_after": "<p>Preis: 49,99 €</p>"},
        {"dom_after": "<p>Gesamt: 49,99 €</p>"},
    ]
    assert find_price_increase_in_flow(flow_pages) == []


def test_find_price_increase_in_flow_ignores_tiny_rounding_delta():
    flow_pages = [
        {"dom_after": "<p>Preis: 49,99 €</p>"},
        {"dom_after": "<p>Preis: 50,00 €</p>"},
    ]
    assert find_price_increase_in_flow(flow_pages) == []


def test_find_price_increase_in_flow_needs_at_least_two_pages():
    assert find_price_increase_in_flow([{"dom_after": "<p>Preis: 49,99 €</p>"}]) == []
    assert find_price_increase_in_flow([]) == []


def test_find_price_increase_in_flow_ignores_page_with_no_price():
    flow_pages = [
        {"dom_after": "<p>Preis: 49,99 €</p>"},
        {"dom_after": "<p>Warenkorb</p>"},
    ]
    assert find_price_increase_in_flow(flow_pages) == []
