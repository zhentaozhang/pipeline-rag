from __future__ import annotations

from enum import StrEnum


class SpanKind(StrEnum):
    PIPELINE = "pipeline"
    RETRIEVAL = "retrieval"
    CHANNEL = "channel"
    LLM = "llm"
    TOOL = "tool"
    EVALUATION = "evaluation"
    MEMORY = "memory"
    REWRITE = "rewrite"
    CLASSIFY = "classify"
    ROUTE = "route"
    RECOMMEND = "recommend"
    AGENT = "agent"


class SpanStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    SKIPPED = "skipped"
