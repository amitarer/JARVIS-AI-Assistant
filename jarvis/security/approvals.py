"""An approval is bound to exact canonical parameters, task and expiration."""

import secrets
import threading
import time
from dataclasses import dataclass

from jarvis.core.models import ApprovalRequest, Risk, ToolCall, UserError


@dataclass(frozen=True)
class Grant:
    task_id: str
    call: ToolCall
    risk: Risk
    expires_at: float


class ApprovalStore:
    def __init__(self) -> None:
        self._grants: dict[str, Grant] = {}
        self._lock = threading.Lock()

    def issue(self, request: ApprovalRequest, ttl: float = 30) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._grants[token] = Grant(request.task_id, request.call, request.risk, time.monotonic() + ttl)
        return token

    def consume(self, token: str | None, task_id: str, call: ToolCall, risk: Risk) -> None:
        with self._lock:
            grant = self._grants.pop(token or "", None)
        if (grant is None or grant.expires_at < time.monotonic() or grant.task_id != task_id
                or grant.call != call or grant.risk != risk):
            raise UserError("Conferma assente, scaduta o non valida per questa operazione.")

    def revoke_all(self) -> None:
        with self._lock:
            self._grants.clear()
