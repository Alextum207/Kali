from app.compliance import map_to_norm


def test_map_known_patterns():
    assert map_to_norm("Fake Urgency") == "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3"
    assert map_to_norm("Confirm Shaming") == "Art. 25 DSA"
    assert map_to_norm("Pre-ticked Box") == "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO"
    assert map_to_norm("Hidden Costs") == "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB"
    assert map_to_norm("Preisaufschlag") == "PAngV"


def test_map_unknown_pattern_returns_placeholder():
    assert map_to_norm("Something Weird") == "Unbekannt"
