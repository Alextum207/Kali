NORM_MAP = {
    "Fake Urgency": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Fake Scarcity": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Fake Social Proof": "UWG §§ 5, 5a; Anhang zu § 3 Abs. 3",
    "Hidden Costs": "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB",
    "Unklare Button-Beschriftung": "§ 312j Abs. 3, 4 BGB; Art. 246a EGBGB",
    "Confirm Shaming": "Art. 25 DSA",
    "Visuelle Asymmetrie (Button)": "Art. 25 DSA",
    "Obstruction": "Art. 25 DSA",
    "Pre-ticked Box": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "Verdeckter Opt-out": "Art. 4 Nr. 11, Art. 7 Abs. 4 DSGVO",
    "Preisaufschlag": "PAngV",
}


def map_to_norm(pattern_type: str) -> str:
    return NORM_MAP.get(pattern_type, "Unbekannt")
