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


def test_finds_multiple_pattern_types_in_same_text():
    text = "Only 3 items available. 128 customers have also bought this item."
    findings = find_regex_patterns(text)
    pattern_types = {f["pattern_type"] for f in findings}
    assert pattern_types == {"Fake Scarcity", "Fake Social Proof"}
