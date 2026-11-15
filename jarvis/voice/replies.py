"""Short spoken follow-up, added only to final results, never action intentions."""

import re

FOLLOW_UP = "Ha bisogno d'altro, signore?"


def spoken_reply(text):
    text = text.strip()
    if not text:
        return FOLLOW_UP
    existing = re.search(r"ha bisogno d[’']altro(?:,?\s+signore)?\s*\?\s*$", text, flags=re.IGNORECASE)
    body = text[:existing.start()].rstrip() if existing else text
    budget = 2000 - len(FOLLOW_UP) - 1
    if len(body) > budget:
        body = body[:budget - 1].rstrip() + "…"
    return body + "\n" + FOLLOW_UP if body else FOLLOW_UP
