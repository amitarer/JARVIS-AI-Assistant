"""Destructive operations use exactly the same authorization gate as other tools."""

from typing import Any

from jarvis.core.models import Risk, ToolResult, UserError
from jarvis.core.tasks import TaskContext
from jarvis.memory.repository import Repository


class ClearHistoryTool:
    name = "clear_history"
    risk = Risk.HIGH
    description = "Cancella messaggi e attività precedenti dal database locale."
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}

    def __init__(self, repository: Repository):
        self.repository = repository

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments:
            raise UserError("La cancellazione cronologia non accetta parametri aggiuntivi.")
        return {}

    def describe(self, arguments: dict[str, Any]) -> str:
        return ("Cancella tutti i messaggi e tutte le attività precedenti nel database locale.\n"
                "Restano le preferenze, i log tecnici e la registrazione di questa cancellazione.\n"
                "Questa operazione non è annullabile.")

    def execute(self, arguments: dict[str, Any], context: TaskContext) -> ToolResult:
        context.checkpoint()
        self.repository.clear_history(context.task_id)
        return ToolResult("Cronologia cancellata. Preferenze e log tecnici conservati.", {"history_cleared": True})


class ResetPreferencesTool:
    name = "reset_preferences"
    risk = Risk.HIGH
    description = "Cancella le preferenze salvate e ripristina quelle iniziali."
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}

    def __init__(self, repository: Repository):
        self.repository = repository

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments:
            raise UserError("Il ripristino non accetta parametri aggiuntivi.")
        return {}

    def describe(self, arguments: dict[str, Any]) -> str:
        return "Elimina le preferenze salvate (animazioni e livello log). La cronologia resta invariata."

    def execute(self, arguments: dict[str, Any], context: TaskContext) -> ToolResult:
        context.checkpoint()
        self.repository.clear_preferences()
        return ToolResult("Preferenze ripristinate ai valori di configurazione iniziali.")
