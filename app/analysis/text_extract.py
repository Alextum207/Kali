import trafilatura

# ponytail: 200-char threshold is uncalibrated/arbitrary but cheap — tune
# against real short-nag-banner pages if favor_recall turns out too noisy.
_MIN_PRECISE_LEN = 200


def extract_main_text(html: str) -> str:
    text = trafilatura.extract(html, favor_precision=True)
    if text is None or len(text) < _MIN_PRECISE_LEN:
        # favor_precision can cut short manipulative micro-copy (nag banners,
        # tiny disclaimers) as "not main content" — retry looser.
        fallback = trafilatura.extract(html, favor_precision=False, favor_recall=True)
        if fallback:
            text = fallback
    return text or ""
