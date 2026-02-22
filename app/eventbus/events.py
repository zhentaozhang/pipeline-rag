from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class Event(Generic[T]):
    name: str
    payload: T
    conversation_id: str | None = None
    exchange_id: int | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationStartedPayload:
    question: str
    chat_mode: str


@dataclass
class ConversationCompletedPayload:
    exchange_id: int
    turn_status: int
    total_tokens: int
    total_duration_ms: int


@dataclass
class ConversationFailedPayload:
    exchange_id: int
    error: str


@dataclass
class ConversationCancelledPayload:
    exchange_id: int


@dataclass
class ExecutionStartedPayload:
    mode: str
    sub_questions: list[str]


@dataclass
class RetrievalStartedPayload:
    sub_question: str
    channels: list[str]


@dataclass
class RetrievalCompletedPayload:
    sub_question: str
    evidence_count: int
    channels: list[str]


@dataclass
class SafetyViolationPayload:
    layer: str
    reason: str
    risk_score: float
    text_preview: str


@dataclass
class QualityCheckCompletedPayload:
    score: float
    passed: bool
    retry_round: int


@dataclass
class MemorySavedPayload:
    conversation_id: str
    exchange_id: int


@dataclass
class StateTransitionPayload:
    from_state: str
    to_state: str
    elapsed_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)
