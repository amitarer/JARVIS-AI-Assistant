"""Explicit Foundation commands, deliberately without NLP heuristics."""

import json

from jarvis.core.models import ToolCall, UserError

HELP = (
    "Modalità demo: nessun provider AI è collegato.\n"
    "Comandi disponibili:\n"
    "/aiuto — mostra questi comandi\n"
    "/app — elenca le applicazioni installate\n"
    "/apri blocco_note — avvia Blocco note\n"
    "I messaggi normali vengono salvati nella cronologia locale; "
    "la comprensione del linguaggio naturale arriverà nella versione 0.2."
)


def parse_command(text: str) -> ToolCall | None:
    parts = text.strip().split()
    if not parts or not parts[0].startswith("/"):
        return None
    command = parts[0].casefold()
    if command in {"/aiuto", "/app"} and len(parts) == 1:
        return ToolCall(command[1:], "{}")
    if command == "/apri" and len(parts) == 2:
        return ToolCall("open_application", json.dumps({"application_id": parts[1]}))
    raise UserError("Comando non valido. Usa /aiuto per vedere i comandi disponibili.")
