def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(rgb_a: tuple[int, int, int], rgb_b: tuple[int, int, int]) -> float:
    l1 = _relative_luminance(rgb_a) + 0.05
    l2 = _relative_luminance(rgb_b) + 0.05
    return max(l1, l2) / min(l1, l2)


SIZE_RATIO_THRESHOLD = 1.8
CONTRAST_DELTA_THRESHOLD = 4.0


def compute_button_asymmetry(accept_style: dict, reject_style: dict) -> list[dict]:
    accept_area = accept_style["width"] * accept_style["height"]
    reject_area = reject_style["width"] * reject_style["height"]
    size_ratio = accept_area / reject_area if reject_area else float("inf")

    accept_contrast = contrast_ratio(accept_style["bg_color"], accept_style["text_color"])
    reject_contrast = contrast_ratio(reject_style["bg_color"], reject_style["text_color"])
    contrast_delta = abs(accept_contrast - reject_contrast)

    if size_ratio < SIZE_RATIO_THRESHOLD and contrast_delta < CONTRAST_DELTA_THRESHOLD:
        return []

    # Confidence grows with how far each measure exceeds its threshold, capped at 1.0.
    size_component = min(size_ratio / SIZE_RATIO_THRESHOLD - 1, 1.0) if size_ratio >= SIZE_RATIO_THRESHOLD else 0.0
    contrast_component = (
        min(contrast_delta / CONTRAST_DELTA_THRESHOLD - 1, 1.0)
        if contrast_delta >= CONTRAST_DELTA_THRESHOLD
        else 0.0
    )
    confidence = round(min(0.5 + max(size_component, contrast_component) * 0.5, 1.0), 2)

    return [
        {
            "pattern_type": "Visuelle Asymmetrie (Button)",
            "confidence_score": confidence,
            "evidence_data": {
                "size_ratio": round(size_ratio, 2),
                "contrast_delta": round(contrast_delta, 2),
            },
        }
    ]
