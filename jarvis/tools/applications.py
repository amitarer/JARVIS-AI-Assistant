"""Discover applications from the local Windows Start menu, without installing."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import unicodedata

from jarvis.core.models import Risk, ToolResult, UserError
from jarvis.infrastructure.windows import powershell


def normalized(value):
    return "".join(character for character in unicodedata.normalize("NFKD", value.casefold())
                   if character.isalnum())


@dataclass(frozen=True)
class InstalledApplication:
    identifier: str
    label: str
    executable: Path | None = None
    app_id: str = ""
    aliases: tuple[str, ...] = ()


class ApplicationCatalog:
    def __init__(self, root):
        self.root = root
        self._lock = threading.Lock()
        self._installed = []
        self._loaded = False
        self._loaded_at = 0

    def applications(self, context):
        # Reload the user's explicit entries on every request, without a restart.
        from jarvis.infrastructure.settings import load_settings
        configured = load_settings(self.root).applications
        entries = [InstalledApplication(key, app.label, app.executable, aliases=app.aliases) for key, app in configured.items()]
        with self._lock:
            if os.name == "nt" and (not self._loaded or time.monotonic() - self._loaded_at > 60):
                code, output = powershell(
                    "@(Get-StartApps | Select-Object Name, AppID) | ConvertTo-Json -Compress", context)
                if code != 0:
                    raise UserError("Impossibile leggere le applicazioni del menu Start.")
                try:
                    rows = json.loads(output or "[]")
                    if isinstance(rows, dict):
                        rows = [rows]
                    self._installed = [InstalledApplication(
                        "app_" + hashlib.sha256(row["AppID"].encode()).hexdigest()[:16],
                        row["Name"], app_id=row["AppID"]) for row in rows
                        if isinstance(row, dict) and row.get("AppID") and row.get("Name")]
                except (ValueError, TypeError, KeyError):
                    raise UserError("Elenco applicazioni Windows non valido.") from None
                self._loaded = True
                self._loaded_at = time.monotonic()
            labels = {normalized(entry.label) for entry in entries}
            entries.extend(entry for entry in self._installed if normalized(entry.label) not in labels)
        return entries

    def resolve(self, query, context):
        entries = self.applications(context)
        match = next((entry for entry in entries if entry.identifier == query), None)
        if match:
            return match
        name = normalized(query)
        exact = [entry for entry in entries if normalized(entry.label) == name]
        aliases = [entry for entry in entries if name in {normalized(alias) for alias in entry.aliases}]
        matches = exact or aliases or [entry for entry in entries if name and name in normalized(entry.label)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise UserError("Nome ambiguo. Scegli una di queste applicazioni: " +
                            ", ".join(f"{entry.label} ({entry.identifier})" for entry in matches[:12]))
        path = Path(query)
        if path.is_absolute() and path.suffix.casefold() == ".exe" and path.is_file():
            return InstalledApplication(str(path), path.stem, path)
        raise UserError("Applicazione non trovata. Cerca con list_applications oppure specifica il percorso completo dell'eseguibile .exe.")


class ListApplicationsTool:
    name = "list_applications"
    risk = Risk.LOW
    description = "Cerca le applicazioni installate nel menu Start per nome. Restituisce gli ID per open_application; query vuota elenca tutte le app."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}},
                  "required": ["query"], "additionalProperties": False}

    def __init__(self, catalog):
        self.catalog = catalog

    def validate(self, arguments):
        if set(arguments) != {"query"} or not isinstance(arguments["query"], str) or len(arguments["query"]) > 200:
            raise UserError("Specifica una ricerca applicazioni di massimo 200 caratteri.")
        return {"query": arguments["query"].strip()}

    def describe(self, arguments):
        return "Consulta le applicazioni installate in Windows."

    def execute(self, arguments, context):
        context.checkpoint()
        query = normalized(arguments["query"])
        entries = [entry for entry in self.catalog.applications(context)
                   if not query or query in normalized(entry.label) or query in normalized(entry.identifier)
                   or any(query in normalized(alias) for alias in entry.aliases)]
        items = [{"application_id": entry.identifier, "name": entry.label} for entry in entries[:200]]
        return ToolResult(json.dumps({"applications": items, "total": len(entries), "truncated": len(entries) > 200}, ensure_ascii=False),
                          {"applications_found": len(entries)}, observation=True)
