from app.analysis.regex_classify import find_regex_patterns

NEUTRAL_TEXT = "Willkommen in unserem Onlineshop. Wir freuen uns auf Ihren Besuch."


def test_find_regex_patterns_ignores_neutral_text():
    assert find_regex_patterns(NEUTRAL_TEXT) == []


def test_finds_fake_urgency_countdown_en():
    findings = find_regex_patterns("Hurry, offer ends in 2 days 3 hours!")
    assert any(f["pattern_type"] == "Fake Urgency" for f in findings)


def test_finds_fake_urgency_countdown_de():
    findings = find_regex_patterns("Nur noch 2 Tage 3 Stunden bis zum Angebotsende!")
    assert any(f["pattern_type"] == "Fake Urgency" for f in findings)


def test_fake_urgency_does_not_match_plain_opening_hours():
    """Regression: the source repo's colon-format alternative only fires
    behind a live DOM-diff check in constants.js (does the number actually
    decrease?) — on static text alone it matched any HH:MM-shaped
    substring, so ordinary opening-hours text was misread as a countdown."""
    findings = find_regex_patterns("Öffnungszeiten: Mo-Fr 9:00 - 18:00 Uhr")
    assert not any(f["pattern_type"] == "Fake Urgency" for f in findings)


def test_finds_fake_scarcity_en():
    findings = find_regex_patterns("Only 3 items available, order now.")
    assert any(f["pattern_type"] == "Fake Scarcity" for f in findings)
    quote = next(f for f in findings if f["pattern_type"] == "Fake Scarcity")["evidence_data"]["quote"]
    assert quote


def test_finds_fake_scarcity_de():
    findings = find_regex_patterns("Nur noch 3 Stück verfügbar, jetzt bestellen.")
    assert any(f["pattern_type"] == "Fake Scarcity" for f in findings)


def test_finds_fake_social_proof_en():
    findings = find_regex_patterns("128 customers have also bought this item.")
    assert any(f["pattern_type"] == "Fake Social Proof" for f in findings)


def test_finds_fake_social_proof_de():
    findings = find_regex_patterns("128 Kunden haben auch gekauft.")
    assert any(f["pattern_type"] == "Fake Social Proof" for f in findings)


def test_finds_forced_continuity_en():
    findings = find_regex_patterns("Free for the first month, then $9.99 after month.")
    assert any(f["pattern_type"] == "Forced Continuity" for f in findings)


def test_finds_forced_continuity_de():
    findings = find_regex_patterns("9,99 Euro ab dem 2. Monat.")
    assert any(f["pattern_type"] == "Forced Continuity" for f in findings)


def test_finds_forced_continuity_en_after_nth_month():
    """Ported from constants.js — was previously only caught by the
    browser extension, not the server-side (report-generating) classifier."""
    findings = find_regex_patterns("This costs $10.99 after 12 months.")
    assert any(f["pattern_type"] == "Forced Continuity" for f in findings)


def test_finds_forced_continuity_de_danach_phrasing():
    """Ported from constants.js — was previously only caught by the
    browser extension, not the server-side (report-generating) classifier."""
    findings = find_regex_patterns("Danach 10 Euro/Monat.")
    assert any(f["pattern_type"] == "Forced Continuity" for f in findings)


def test_finds_multiple_pattern_types_in_same_text():
    text = "Only 3 items available. 128 customers have also bought this item."
    findings = find_regex_patterns(text)
    pattern_types = {f["pattern_type"] for f in findings}
    assert pattern_types == {"Fake Scarcity", "Fake Social Proof"}


def test_scarcity_does_not_match_unrelated_rating_count_and_seller_line():
    """Regression: a product card's rating count ("...39") immediately
    followed by an unrelated "Verkauft von X" seller-attribution line (a
    separate DOM block, joined by a newline in innerText) must not read as
    "39 verkauft" (39 sold) — real bug report from a live Knuspr listing
    page. The old `\\s*` between number and verb matched across that
    newline; only same-line adjacency (a real "N Stück verkauft" phrase)
    should count."""
    text = "4,6 von 5 Sternen39\nVerkauft von Knuspr DE"
    findings = find_regex_patterns(text)
    assert not any(f["pattern_type"] == "Fake Scarcity" for f in findings)


def test_finds_fake_scarcity_de_verkauft_phrase_still_works():
    findings = find_regex_patterns("Nur noch 5 Stück verkauft, schnell zugreifen.")
    assert any(f["pattern_type"] == "Fake Scarcity" for f in findings)
