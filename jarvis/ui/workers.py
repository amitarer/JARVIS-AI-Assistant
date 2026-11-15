"""Qt adapter for the synchronous, GUI-independent core."""

import threading
import time

from PySide6.QtCore import QThread, Signal

from jarvis.core.controller import Controller
from jarvis.core.models import ApprovalRequest, Cancelled, Event, UserError
from jarvis.core.tasks import TaskContext


class TaskWorker(QThread):
    event = Signal(object)

    def __init__(self, controller: Controller, payload: dict, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.payload = payload
        self.cancellation = threading.Event()
        self._answered = threading.Event()
        self._pending: ApprovalRequest | None = None
        self._token: str | None = None
        self._lock = threading.Lock()

    def run(self) -> None:
        self.controller.run(self.payload, self.cancellation, self.event.emit, self._ask_approval, self._before_tool)

    def _before_tool(self, tool: str, context: TaskContext) -> None:
        acknowledgement = threading.Event()
        self.event.emit(Event("execution_barrier", {"ack": acknowledgement, "tool": tool}))
        started = time.monotonic()
        while not acknowledgement.wait(0.05):
            context.checkpoint()
            if time.monotonic() - started > 20:
                raise UserError("L'interfaccia non ha confermato la chiusura dell'overlay: operazione arrestata.")

    def cancel(self) -> None:
        self.cancellation.set()
        self._answered.set()

    def resolve_approval(self, request_id: str, approved: bool) -> None:
        with self._lock:
            if self._pending is None or self._pending.request_id != request_id or self.cancellation.is_set():
                return
            if self._answered.is_set():
                return
            if approved:
                self._token = self.controller.tools.policy.approvals.issue(self._pending)
            self._answered.set()

    def _ask_approval(self, request: ApprovalRequest, context: TaskContext) -> str | None:
        self.controller.repository.set_task_status(context.task_id, "waiting_approval")
        self.event.emit(Event("snapshot", self.controller.repository.snapshot()))
        with self._lock:
            self._pending = request
            self._token = None
            self._answered.clear()
        self.event.emit(Event("approval", request))
        started = time.monotonic()
        try:
            while not self._answered.wait(0.05):
                if self.cancellation.is_set():
                    raise Cancelled("Attività interrotta prima dell'autorizzazione.")
                if time.monotonic() - started >= self.controller.settings.approval_timeout_seconds:
                    raise UserError("Richiesta di conferma scaduta. Nessuna azione autorizzata.")
            if self.cancellation.is_set():
                raise Cancelled("Attività interrotta prima dell'autorizzazione.")
            with self._lock:
                if not self._token:
                    raise UserError("Operazione negata. Nessuna modifica eseguita.")
                return self._token
        finally:
            context.extend_for_approval(time.monotonic() - started)
            with self._lock:
                self._pending = None
            self.event.emit(Event("approval_closed", request.request_id))
            self.controller.repository.set_task_status(context.task_id, "running")
