"""Values shared by the core, tools and adapters."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class Risk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Cancelled(Exception):
    """Cooperative task cancellation."""


class TaskTimeout(Exception):
    """The active task exceeded its deadline."""


class UserError(Exception):
    """An error whose message is safe to display to the user."""


class UserActionRequired(UserError):
    """A visible login, consent or challenge must be completed by the user."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments_json: str


@dataclass(frozen=True)
class ToolResult:
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    observation: bool = False
    public_message: str | None = None


@dataclass(frozen=True)
class Event:
    kind: str
    data: Any = None


@dataclass(frozen=True)
class ApprovalRequest:
    task_id: str
    call: ToolCall
    risk: Risk
    description: str
    request_id: str = field(default_factory=lambda: uuid4().hex)


@dataclass(frozen=True)
class Message:
    role: str
    content: str
    created_at: str
