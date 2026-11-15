"""A tool validates inputs before authorization and execution."""

from typing import Any, Protocol

from jarvis.core.models import Risk, ToolResult
from jarvis.core.tasks import TaskContext


class Tool(Protocol):
    name: str
    risk: Risk
    description: str
    parameters: dict[str, Any]

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def describe(self, arguments: dict[str, Any]) -> str: ...
    def execute(self, arguments: dict[str, Any], context: TaskContext) -> ToolResult: ...
