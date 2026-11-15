"""Launch configured or discovered Windows apps without shell or user arguments."""

import os
import subprocess
from typing import Any

from jarvis.core.models import Risk, ToolResult, UserError
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import Application


class OpenApplicationTool:
    name = "open_application"
    risk = Risk.LOW
    description = "Avvia un'applicazione Windows, senza argomenti."

    def __init__(self, applications: dict[str, Application], catalog=None):
        self._applications = dict(applications)
        self.catalog = catalog
        self.parameters = {"type": "object", "properties": {
            "application_id": {"type": "string", "enum": sorted(applications)}
        }, "required": ["application_id"], "additionalProperties": False}
        if catalog is not None:
            self.parameters["properties"]["application_id"] = {"type": "string"}
            self.description = ("Apri qualsiasi applicazione installata, ad esempio Chrome, Spotify o Calcolatrice. "
                                "application_id accetta nome, ID di list_applications o percorso completo .exe. "
                                "Se il nome e' ambiguo, cerca con list_applications. Nessun argomento o comando shell.")
            aliases = [f"{', '.join(app.aliases)} -> {identifier}" for identifier, app in applications.items() if app.aliases]
            if aliases:
                self.description += " Nomi alternativi configurati (anche trascrizioni vocali): " + "; ".join(aliases)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if set(arguments) != {"application_id"} or not isinstance(arguments["application_id"], str):
            raise UserError("Specificare soltanto application_id.")
        if not arguments["application_id"].strip() or len(arguments["application_id"]) > 1024:
            raise UserError("Nome applicazione non valido.")
        if self.catalog is None and arguments["application_id"] not in self._applications:
            raise UserError("Applicazione non autorizzata. Usa /app per vedere la lista.")
        return dict(arguments)

    def describe(self, arguments: dict[str, Any]) -> str:
        if self.catalog is not None:
            return f"Avvia applicazione Windows: {arguments['application_id']} (nessun argomento)."
        app = self._applications[arguments["application_id"]]
        return f"Avvia {app.label}: {app.executable} (nessun argomento)."

    def execute(self, arguments: dict[str, Any], context: TaskContext) -> ToolResult:
        if os.name != "nt":
            raise UserError("L'apertura delle applicazioni è disponibile soltanto su Windows.")
        app = (self.catalog.resolve(arguments["application_id"], context) if self.catalog is not None
               else self._applications[arguments["application_id"]])
        if self.catalog is not None and app.app_id:
            context.checkpoint()
            try:
                os.startfile("shell:AppsFolder\\" + app.app_id)
            except OSError:
                raise UserError("Windows non ha consentito l'avvio dell'applicazione dal menu Start.") from None
            return ToolResult(f"Richiesta di avvio di {app.label} accettata da Windows. Finestra non ancora verificata.",
                              {"application_id": app.identifier, "launch_accepted": True, "window_verified": False})
        if not app.executable.is_file():
            raise UserError("Eseguibile non trovato. Verifica config/applications.json.")
        # A redirected executable must not silently inherit authorization.
        if app.executable.is_symlink() or app.executable.is_junction():
            raise UserError("Collegamenti e junction non sono ammessi come eseguibili.")
        context.checkpoint()
        try:
            process = subprocess.Popen([str(app.executable)], shell=False,
                                       cwd=str(app.executable.parent), close_fds=True,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
        except OSError:
            raise UserError("Windows non ha consentito l'avvio dell'applicazione.") from None
        exit_code = process.poll()
        if exit_code is not None and exit_code != 0:
            raise UserError("Il processo si è chiuso subito con un errore.")
        return ToolResult(
            f"Avvio di {app.label} accettato da Windows (PID {process.pid}). "
            "La presenza della finestra non è ancora verificata.",
            {"pid": process.pid, "process_created": True, "window_verified": False,
             "application_id": arguments["application_id"]},
        )
