"""Regenerates chrome/data/consent-rules.json by bundling every file under
Kali's data/consent_rules/*.json into a single array (one array element per
source file, contents unchanged) — one manifest entry / one fetch() for the
extension instead of 204. Re-run manually whenever data/consent_rules/
changes; not wired into any build/CI step.
"""

import json
import pathlib

rules_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "consent_rules"
out_path = pathlib.Path(__file__).parent / "chrome" / "data" / "consent-rules.json"

files = sorted(rules_dir.glob("*.json"))
combined = [json.loads(f.read_text(encoding="utf-8")) for f in files]

# Manual-QA-only fixture rule (not a real vendored Consent-O-Matic file):
# an accept-only banner with no reject action and no consent-toggle
# structure, for exercising the "missing reject option" pattern via
# test-page-missing-reject.html. Appended here (rather than committed to
# data/consent_rules/, which mirrors the real upstream project) so it
# survives every regeneration without polluting the real rule source.
combined.append({
    "kali-qa-missing-reject": {
        "detectors": [
            {"presentMatcher": [{"type": "css", "target": {"selector": "#kali-qa-cookie-banner-no-reject"}}]}
        ],
        "methods": [
            {
                "action": {
                    "type": "click",
                    "target": {"selector": "button", "textFilter": ["Accept all"]},
                    "parent": {"selector": "#kali-qa-cookie-banner-no-reject"},
                },
                "name": "DO_CONSENT",
            }
        ],
    }
})

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(combined), encoding="utf-8")
print(f"Wrote {len(combined)} rules to {out_path}")
