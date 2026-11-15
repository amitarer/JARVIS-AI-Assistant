"""Read factual audit evidence without inventing past actions."""

import json

from jarvis.core.models import Risk, ToolResult, UserError
from jarvis.core.tasks import TaskContext
from jarvis.memory.repository import Repository


class ReadOperationsTool:
    name = "read_operations"
    risk = Risk.LOW
    description = "Consulta azioni effettive ed evidenze nel registro locale. Usalo per domande su operazioni passate."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
                  "required": ["query"], "additionalProperties": False}

    def __init__(self, repository: Repository):
        self.repository = repository

    def validate(self, arguments: dict) -> dict:
        if (set(arguments) - {"query", "limit"} or not isinstance(arguments.get("query"), str)
                or len(arguments["query"]) > 200 or type(arguments.get("limit", 10)) is not int
                or not 1 <= arguments.get("limit", 10) <= 20):
            raise UserError("Parametri di ricerca registro non validi.")
        return {"query": arguments["query"], "limit": arguments.get("limit", 10)}

    def describe(self, arguments: dict) -> str:
        return "Consulta il registro locale delle operazioni."

    def execute(self, arguments: dict, context: TaskContext) -> ToolResult:
        context.checkpoint()
        records = self.repository.operations(arguments["query"], arguments["limit"])
        return ToolResult(json.dumps(records, ensure_ascii=False) if records else "Nessuna operazione corrispondente registrata. Non è prova di un invio o completamento.",
                          {"records_found": len(records), "source": "local_operation_audit"}, observation=True)
