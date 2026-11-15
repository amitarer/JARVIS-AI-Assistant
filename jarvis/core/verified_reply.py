"""Conservative guard for unsupported action-completion statements in Italian."""

import re

COMPLETION = re.compile(
    r"\b(?:sto|stiamo)\s+(?:aprendo|avviando|chiudendo|inviando|eliminando|eseguendo)\b|"
    r"\b(?:ho|abbiamo)\s+(?:(?:già|appena|correttamente|effettivamente)\s+){0,3}"
    r"(?:aperto|avviato|chiuso|inviato|spedito|eliminato|cancellato|salvato|creato|modificato|installato|pubblicato|registrato|eseguito|completato|pagato)\b"
    r"|\b(?:operazione|attività|invio|apertura|installazione)\s+(?:completat[oa]|riuscit[oa]|eseguit[oa])\b"
    r"|\b(?:email|mail|messaggio|file|finestra|programma|applicazione|pagamento|account)\s+"
    r"(?:è\s+|sono\s+)?(?:stat[oaie]\s+)?(?:inviat[oaie]|apert[oaie]|avviat[oaie]|eliminat[oaie]|creat[oaie]|salvat[oaie])\b",
    re.IGNORECASE,
)


def has_completion_claim(text: str) -> bool:
    for match in COMPLETION.finditer(text):
        prefix = text[max(0, match.start() - 40):match.start()]
        if re.search(r"\b(?:non|nessuna|nessun|nessun'altra)\s*$", prefix, re.IGNORECASE):
            continue
        return True
    return False


def guard_unverified_answer(text: str) -> tuple[str, bool]:
    if has_completion_claim(text):
        return ("Non posso confermare il completamento: non è stata eseguita un'operazione verificata per questa richiesta. "
                "Le operazioni passate devono essere controllate nel registro locale.", True)
    return text, False
