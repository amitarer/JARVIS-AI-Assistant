"""A task-bound, revocable capability for one explicitly approved conversation."""

from dataclasses import dataclass, field
import threading


@dataclass(frozen=True)
class SessionPermission:
    task_id: str
    cancellation: threading.Event
    tools: frozenset[str] = frozenset({"browser_chat_open", "browser_chat_observe", "browser_chat_send", "browser_chat_reply"})
    revoked: threading.Event = field(default_factory=threading.Event)

    def allows(self, context, call):
        return (context.task_id == self.task_id and context.cancellation is self.cancellation
                and not self.cancellation.is_set() and not self.revoked.is_set() and call.name in self.tools)
