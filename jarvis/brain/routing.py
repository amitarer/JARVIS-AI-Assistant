"""Conservative fast path for explicitly analytical requests, never desktop effects."""

import re


def requests_deep_reasoning(text, pending_request=""):
    if pending_request:
        return False
    # Quoted message text can contain problem words. Operational requests must
    # keep the normal task router and its authorization boundaries.
    if re.search(r"\b(?:apr\w*|avvi\w*|invi\w*|mand\w*|scriv\w*|legg\w*|cerc\w*|salv\w*|"
                 r"elimin\w*|cancell\w*|spost\w*|install\w*|chiud\w*|prepar\w*)\b", text, re.I):
        return False
    return bool(re.search(r"\b(?:ragiona|ragionamento|risolvi|logica|logico|probabilit[aà]|vincoli|"
                          r"dipendenze|colpevole|dichiarazioni|ottimizzazione)\b|"
                          r"\b(?:tempo minimo|calendario valido|analizza i pro e contro)\b", text, re.I))
