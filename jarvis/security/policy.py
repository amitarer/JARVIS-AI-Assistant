"""Only registered tools can reach this gate. Medium/high risk need approval."""

import json
from typing import Any

from jarvis.core.models import ApprovalRequest, Risk, ToolCall, UserError
from jarvis.security.approvals import ApprovalStore


def canonical_call(name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(name, json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))


class SecurityPolicy:
    def __init__(self, approvals: ApprovalStore):
        self.approvals = approvals

    def session_authorized(self, context, call):
        from jarvis.security.sessions import SessionPermission
        grant = context.session_permission
        return isinstance(grant, SessionPermission) and grant.allows(context, call)

    def proposal(self, task_id: str, call: ToolCall, risk: Risk, description: str) -> ApprovalRequest | None:
        if not isinstance(risk, Risk):
            raise UserError("Classificazione di rischio non valida.")
        if risk is Risk.LOW:
            return None
        return ApprovalRequest(task_id, call, risk, description)

    def authorize(self, task_id: str, call: ToolCall, risk: Risk, token: str | None) -> None:
        if risk is not Risk.LOW:
            self.approvals.consume(token, task_id, call, risk)
