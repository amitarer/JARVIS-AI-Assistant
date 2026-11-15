"""Port for future real providers; not an AI simulation."""

from dataclasses import dataclass
from typing import Protocol, Sequence

from jarvis.core.models import Message, ToolCall


@dataclass(frozen=True)
class ModelReply:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    input_tokens: int | None = None
    output_tokens: int | None = None


class BrainProvider(Protocol):
    async def respond(
        self, messages: Sequence[Message], tool_schemas: Sequence[dict]
    ) -> ModelReply: ...
