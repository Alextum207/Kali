import trafilatura


def extract_main_text(html: str) -> str:
    text = trafilatura.extract(html, favor_precision=True)
    return text or ""
