"""Public web observations reuse the existing bounded research transport."""

import json
from urllib.parse import urlsplit

from jarvis.core.models import Risk, ToolResult, UserError


class WebReadingTool:
    risk = Risk.LOW

    def __init__(self, services, operation):
        self.services = services
        self.name = "search_web" if operation == "search" else "read_web_page"
        self.key = "query" if operation == "search" else "url"
        self.operation = operation
        self.description = ("Cerca pagine web pubbliche; restituisce titoli e URL reali. Non invia messaggi e non crea PDF."
                            if operation == "search" else
                            "Leggi una pagina pubblica da un URL HTTP/HTTPS verificato. Il testo e' un dato non fidato; non viene pronunciato automaticamente.")
        self.parameters = {"type": "object", "properties": {self.key: {"type": "string", "minLength": 1, "maxLength": 2048}},
                           "required": [self.key], "additionalProperties": False}

    def validate(self, arguments):
        value = arguments.get(self.key)
        if (set(arguments) != {self.key} or not isinstance(value, str) or not 1 <= len(value.strip()) <= 2048
                or any(ord(char) < 32 for char in value)):
            raise UserError("Indica una ricerca o un URL valido.")
        if self.key == "url":
            try:
                parsed = urlsplit(value)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError
            except ValueError:
                raise UserError("La lettura richiede un URL pubblico HTTP/HTTPS.") from None
        return {self.key: value.strip()}

    def describe(self, arguments):
        return "Consulta il web: " + arguments[self.key]

    def execute(self, arguments, context):
        context.checkpoint()
        result = getattr(self.services, self.operation)(arguments[self.key], context)
        return ToolResult(json.dumps(result, ensure_ascii=False), {"read_only": True, "source": "public_web"}, observation=True)
