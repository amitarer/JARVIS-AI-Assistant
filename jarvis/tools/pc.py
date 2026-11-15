"""Files, resources and explicitly approved Windows commands."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from jarvis.core.models import Risk, ToolResult, UserError
from jarvis.infrastructure.windows import powershell


def local_path(value):
    aliases = {"desktop": Path.home() / "Desktop", "download": Path.home() / "Downloads",
               "downloads": Path.home() / "Downloads", "documenti": Path.home() / "Documents",
               "home": Path.home()}
    path = aliases.get(value.casefold(), Path(os.path.expandvars(value)).expanduser())
    if not path.is_absolute() or "\x00" in value:
        raise UserError("Specifica un percorso assoluto oppure desktop, downloads, documenti o home.")
    return path


class OpenResourceTool:
    name = "open_resource"
    risk = Risk.LOW
    description = "Apri un sito HTTP/HTTPS nel browser predefinito, una cartella o un documento locale con la sua app. Accetta anche ms-settings: per le impostazioni Windows."
    parameters = {"type": "object", "properties": {"target": {"type": "string"}},
                  "required": ["target"], "additionalProperties": False}

    def __init__(self, websites=None):
        self.websites = websites
        if websites is not None:
            self.description += " Siti configurati: " + websites.hints()

    def validate(self, arguments):
        if set(arguments) != {"target"} or not isinstance(arguments["target"], str):
            raise UserError("Specifica soltanto target.")
        target = arguments["target"].strip()
        if not target or len(target) > 4096 or any(ord(char) < 32 for char in target):
            raise UserError("Destinazione non valida.")
        if self.websites is not None:
            target = self.websites.resolve(target)
        try:
            parsed = urlsplit(target)
        except ValueError:
            raise UserError("Indirizzo non valido.") from None
        if parsed.scheme.casefold() in {"http", "https"}:
            if not parsed.hostname or parsed.username or parsed.password:
                raise UserError("Indirizzo web non valido o contenente credenziali.")
        elif target.startswith("ms-settings:"):
            if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:-?=&_%" for char in target):
                raise UserError("Indirizzo impostazioni Windows non valido.")
        else:
            path = local_path(target)
            if not path.exists():
                raise UserError("Il file o la cartella non esiste.")
            if path.is_file() and path.suffix.casefold() in {
                ".exe", ".com", ".bat", ".cmd", ".ps1", ".py", ".pyw", ".vbs", ".js", ".wsf", ".lnk", ".url", ".hta", ".reg", ".msi", ".scr",
            }:
                raise UserError("Per un programma usa open_application; per script o installazioni usa run_powershell con conferma.")
            target = str(path)
        return {"target": target}

    def describe(self, arguments):
        return "Apri: " + arguments["target"]

    def risk_for_context(self, arguments, context):
        target = arguments["target"]
        if (context.origin == "voice" and urlsplit(target).scheme in {"http", "https"}
                and (self.websites is None or not self.websites.known_host(target))):
            return Risk.MEDIUM
        return Risk.LOW

    def execute(self, arguments, context):
        context.checkpoint()
        if os.name != "nt":
            raise UserError("L'apertura delle risorse richiede Windows.")
        try:
            os.startfile(arguments["target"])
        except OSError:
            raise UserError("Windows non ha potuto aprire la destinazione.") from None
        return ToolResult("Richiesta di apertura accettata da Windows: " + arguments["target"],
                          {"launch_accepted": True, "content_verified": False})


class InspectFilesTool:
    name = "inspect_files"
    risk = Risk.LOW
    description = "Leggi il contenuto di una cartella (list) o di un file di testo UTF-8 (read_text). Usa percorsi assoluti o desktop, downloads, documenti, home."
    parameters = {"type": "object", "properties": {"action": {"type": "string", "enum": ["list", "read_text"]},
                  "path": {"type": "string"}}, "required": ["action", "path"], "additionalProperties": False}

    def validate(self, arguments):
        if (set(arguments) != {"action", "path"} or not isinstance(arguments["action"], str)
                or arguments["action"] not in {"list", "read_text"}
                or not isinstance(arguments["path"], str) or not 1 <= len(arguments["path"]) <= 4096):
            raise UserError("Specifica action (list/read_text) e path.")
        return {"action": arguments["action"], "path": str(local_path(arguments["path"]))}

    def describe(self, arguments):
        return f"Leggi {arguments['path']} ({arguments['action']})."

    def execute(self, arguments, context):
        context.checkpoint()
        path = Path(arguments["path"])
        try:
            if arguments["action"] == "list":
                items = []
                with os.scandir(path) as entries:
                    for entry in entries:
                        context.checkpoint()
                        if len(items) == 200:
                            break
                        items.append({"name": entry.name, "directory": entry.is_dir(follow_symlinks=False)})
                result = {"path": str(path), "entries": items, "limit": 200, "possibly_truncated": len(items) == 200}
            else:
                with path.open("rb") as source:
                    raw = source.read(12001)
                if b"\x00" in raw:
                    raise UserError("Il file non e' testo UTF-8. Usa un'applicazione adatta per aprirlo.")
                # Ignore only a UTF-8 sequence split by the preview limit.
                import codecs
                decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
                content = decoder.decode(raw[:12000], final=len(raw) <= 12000)
                result = {"path": str(path), "content": content, "truncated": len(raw) > 12000}
        except (OSError, UnicodeError):
            raise UserError("Impossibile leggere il percorso. Verifica accesso, tipo di file e codifica UTF-8.") from None
        return ToolResult(json.dumps(result, ensure_ascii=False), {"read_only": True}, observation=True)


class RunPowerShellTool:
    name = "run_powershell"
    risk = Risk.HIGH
    description = ("Esegui un comando PowerShell Windows per operazioni su file, processi, sistema e applicazioni "
                   "che gli altri strumenti non coprono. Il comando esatto viene mostrato all'utente e richiede conferma. "
                   "Nessuna elevazione automatica. Preferisci gli strumenti specifici quando disponibili.")
    parameters = {"type": "object", "properties": {"command": {"type": "string"}, "working_directory": {"type": "string"}},
                  "required": ["command"], "additionalProperties": False}

    def __init__(self, root):
        self.root = root

    def validate(self, arguments):
        if (set(arguments) - {"command", "working_directory"} or not isinstance(arguments.get("command"), str)
                or not 1 <= len(arguments["command"].strip()) <= 12000 or "\x00" in arguments["command"]
                or not isinstance(arguments.get("working_directory", str(self.root)), str)):
            raise UserError("Comando PowerShell non valido (massimo 12000 caratteri).")
        cwd = local_path(arguments.get("working_directory", str(self.root)))
        if not cwd.is_dir():
            raise UserError("La cartella di lavoro non esiste.")
        return {"command": arguments["command"], "working_directory": str(cwd)}

    def describe(self, arguments):
        return "Esegui questo comando PowerShell con i permessi del tuo utente Windows. Le modifiche gia' eseguite non vengono annullate da STOP."

    def execute(self, arguments, context):
        code, output = powershell(arguments["command"], context, cwd=arguments["working_directory"])
        truncated = len(output) > 14000
        text = output[:14000]
        message = f"Comando PowerShell terminato con codice {code}."
        if text:
            message += "\n" + text
        if truncated:
            message += "\n[Output troncato]"
        return ToolResult(message, {"exit_code": code, "command_succeeded": code == 0, "output_truncated": truncated})
