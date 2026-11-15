"""Resolve explicit, user-editable website aliases without guessing domains."""

import json
import re
from urllib.parse import urlsplit, urlunsplit

from jarvis.core.models import UserError
from jarvis.tools.applications import normalized


class WebsiteCatalog:
    def __init__(self, root):
        self.root = root

    def entries(self):
        path = self.root / "config/websites.json"
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            result = []
            for identifier, entry in raw.items():
                parsed = urlsplit(entry["url"])
                aliases = entry.get("aliases", [])
                if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                        or not isinstance(entry["label"], str) or not isinstance(aliases, list)
                        or any(not isinstance(alias, str) or not alias.strip() for alias in aliases)):
                    raise ValueError
                result.append({**entry, "id": identifier, "host": parsed.hostname})
            return result
        except (ValueError, TypeError, AttributeError, KeyError):
            raise UserError("Configurazione siti non valida: controlla config/websites.json.") from None

    def resolve(self, value):
        try:
            parsed = urlsplit(value)
        except ValueError:
            raise UserError("Indirizzo web non valido.") from None
        is_url = parsed.scheme.casefold() in {"http", "https"}
        if is_url and (parsed.username or parsed.password):
            return value
        candidate = parsed.hostname if is_url else value
        matches = []
        for entry in self.entries():
            names = [entry["id"], entry["label"], entry["host"], entry["host"].removeprefix("www."), *entry.get("aliases", [])]
            if normalized(candidate or "") in {normalized(name) for name in names}:
                matches.append(entry)
        if len(matches) > 1:
            raise UserError("Nome sito ambiguo. Specifica l'indirizzo completo.")
        if matches:
            base = urlsplit(matches[0]["url"])
            return urlunsplit((base.scheme, base.netloc, parsed.path or base.path, parsed.query, parsed.fragment)) if is_url else matches[0]["url"]
        if not parsed.scheme and re.fullmatch(r"(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,63}(?::[0-9]+)?(?:[/][^\s]*)?", value):
            return "https://" + value
        return value

    def known_host(self, value):
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and any(
            (parsed.hostname or "").removeprefix("www.") == entry["host"].removeprefix("www.") for entry in self.entries())

    def hints(self):
        return "; ".join(f"{entry['label']}: {entry['url']} (nomi: {', '.join(entry.get('aliases', []))})" for entry in self.entries())
