from app.analysis.visual import contrast_ratio, compute_button_asymmetry


def test_contrast_ratio_black_on_white_is_max():
    ratio = contrast_ratio((0, 0, 0), (255, 255, 255))
    assert 20.0 < ratio < 21.1  # WCAG max is 21:1


def test_compute_button_asymmetry_flags_large_size_and_contrast_gap():
    accept = {"width": 200, "height": 60, "bg_color": (0, 128, 0), "text_color": (255, 255, 255)}
    reject = {"width": 60, "height": 20, "bg_color": (230, 230, 230), "text_color": (240, 240, 240)}
    findings = compute_button_asymmetry(accept, reject)
    assert len(findings) == 1
    assert findings[0]["pattern_type"] == "Visuelle Asymmetrie (Button)"
    assert findings[0]["confidence_score"] > 0.5


def test_compute_button_asymmetry_symmetric_buttons_no_finding():
    accept = {"width": 120, "height": 40, "bg_color": (0, 0, 0), "text_color": (255, 255, 255)}
    reject = {"width": 118, "height": 40, "bg_color": (20, 20, 20), "text_color": (255, 255, 255)}
    findings = compute_button_asymmetry(accept, reject)
    assert findings == []
