"""Bounded execution and cancellation, without forcibly terminating threads."""

import threading
import time

from jarvis.core.models import Cancelled, TaskTimeout


class TaskContext:
    def __init__(self, task_id: str, cancellation: threading.Event, timeout: float, *, origin=None):
        self.task_id = task_id
        self.cancellation = cancellation
        self.deadline = time.monotonic() + timeout
        self.origin = origin
        self.session_permission = None
        self.autonomy_objective = None
        self.research_plan = None

    def checkpoint(self) -> None:
        if self.cancellation.is_set():
            raise Cancelled("Attività interrotta.")
        if time.monotonic() >= self.deadline:
            raise TaskTimeout("Tempo massimo dell’attività superato.")

    @property
    def remaining_if_alive(self) -> float:
        return self.deadline - time.monotonic()

    @property
    def remaining(self) -> float:
        self.checkpoint()
        return max(0.01, self.deadline - time.monotonic())

    def extend_for_approval(self, seconds: float) -> None:
        # Time spent waiting for the human has its own bounded timeout.
        self.deadline += max(0.0, seconds)
