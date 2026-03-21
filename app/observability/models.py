from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.observability.enums import SpanKind, SpanStatus


class Score(BaseModel):
    score_id: str
    trace_id: str
    span_id: str
    metric_name: str
    value: float
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SpanContext(BaseModel):
    span_id: str
    trace_id: str
    parent_span_id: str | None = None
    kind: SpanKind = SpanKind.PIPELINE
    name: str = ""
    status: SpanStatus = SpanStatus.OK
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    duration_ms: float | None = None
    input: Any = None
    output: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    scores: list[Score] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class Trace(BaseModel):
    trace_id: str
    conversation_id: str
    exchange_id: int
    session_id: str | None = None
    root_span_id: str = ""
    input: str = ""
    output: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    flushed_at: datetime | None = None
