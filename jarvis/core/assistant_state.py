"""Shared assistant and overlay states, independent of widgets and audio engines."""

from enum import StrEnum


class AssistantState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    EXECUTING = "executing"
    CONFIRMATION = "confirmation"
    ERROR = "error"
