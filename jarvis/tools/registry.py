"""Default-deny tool catalog and the single execution gateway."""

import json
from collections.abc import Callable

from jarvis.core.models import ApprovalRequest, ToolCall, ToolResult, UserError
from jarvis.core.tasks import TaskContext
from jarvis.security.policy import SecurityPolicy, canonical_call
from jarvis.tools.base import Tool


class ToolRegistry:
    def __init__(self, policy: SecurityPolicy):
        self.policy = policy
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError("Strumento già registrato.")
        self._tools[tool.name] = tool

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def schemas(self, for_model: bool = False) -> list[dict]:
        return [{"type": "function", "name": tool.name, "description": tool.description,
                 "parameters": tool.parameters} for tool in self._tools.values()
                if not for_model or (not tool.name.startswith("research_") and tool.name not in {"clear_history", "reset_preferences", "run_powershell",
                    "browser_chat_open", "browser_chat_observe", "browser_chat_send", "browser_chat_reply"})]

    def execute(
        self, call: ToolCall, context: TaskContext,
        ask_approval: Callable[[ApprovalRequest, TaskContext], str | None],
        before_execute: Callable[[], None] | None = None,
    ) -> ToolResult:
        context.checkpoint()
        tool = self._tools.get(call.name)
        if tool is None:
            raise UserError("Strumento non autorizzato o non disponibile.")
        try:
            raw = json.loads(call.arguments_json)
        except (ValueError, TypeError):
            raise UserError("Parametri dello strumento non validi.") from None
        if not isinstance(raw, dict):
            raise UserError("I parametri devono essere un oggetto JSON.")
        arguments = tool.validate(raw)
        normalized = canonical_call(tool.name, arguments)
        if hasattr(tool, "risk_for_context"):
            risk = tool.risk_for_context(arguments, context)
        else:
            risk = tool.risk_for(arguments) if hasattr(tool, "risk_for") else tool.risk
        session_authorized = self.policy.session_authorized(context, normalized)
        proposal = None if session_authorized else self.policy.proposal(context.task_id, normalized, risk, tool.describe(arguments))
        token = ask_approval(proposal, context) if proposal else None
        context.checkpoint()
        if not self.policy.session_authorized(context, normalized):
            self.policy.authorize(context.task_id, normalized, risk, token)
        context.checkpoint()
        if before_execute:
            before_execute()
        context.checkpoint()
        if session_authorized and not self.policy.session_authorized(context, normalized):
            raise UserError("Autorizzazione della sessione revocata. Nessuna nuova azione eseguita.")
        return tool.execute(arguments, context)
