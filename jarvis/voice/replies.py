"""Bounded speech without automatic conversational closing questions."""

import re

def spoken_reply(text):
    text = text.strip()
    existing = re.search(r"(?:ha|hai) bisogno d[’']altro(?:,?\s+signore)?\s*\?\s*$", text, flags=re.IGNORECASE)
    body = text[:existing.start()].rstrip() if existing else text
    return body if len(body) <= 2000 else body[:1999].rstrip() + "…"


def requests_silence(text):
    """Explicit turn-level instructions; website text never reaches this parser."""
    return bool(re.search(
        r"\b(?:in silenzio|senza (?:parlare|voce|audio)|non (?:leggere|leggerle|leggerlo|parlare|dire)"
        r"(?:.{0,45})(?:voce|alta|sentire)|non (?:voglio|volgio) sentir\w*|non legger\w* ad alta voce)\b",
        text, re.IGNORECASE))
