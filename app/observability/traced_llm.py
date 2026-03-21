from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.observability.enums import SpanKind
from app.observability.models import SpanContext
from app.observability.tracer import (
    LLM_CALL_DURATION_SECONDS,
    LLM_CALL_TOTAL,
    LLM_COST_TOTAL,
    LLM_TOKEN_TOTAL,
    Tracer,
    next_id_str,
)


@dataclass
class LLMResult:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str
    raw: Any


_MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "qwen-plus": (0.0008, 0.002),
    "qwen-max": (0.002, 0.006),
    "deepseek-chat": (0.0005, 0.0015),
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prices = _MODEL_PRICES.get(model, (0.001, 0.002))
    return (prompt_tokens / 1000 * prices[0]) + (completion_tokens / 1000 * prices[1])


class TracedLLM:
    def __init__(self, tracer: Tracer, client: Any, model: str) -> None:
        self._tracer = tracer
        self._client = client
        self._model = model

    async def agenerate(self, messages: list[dict], **kwargs: Any) -> LLMResult:
        parent_span_id = self._tracer.current_span_id

        span = SpanContext(
            span_id=next_id_str(),
            trace_id=self._tracer.trace_id,
            parent_span_id=parent_span_id,
            kind=SpanKind.LLM,
            name="llm_call",
            input=messages,
        )
        span.started_at = datetime.now(UTC)
        self._tracer._push(span)

        try:
            start = time.monotonic()
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                **kwargs,
            )
            duration = time.monotonic() - start

            usage = resp.usage
            prompt_tokens = getattr(usage, "prompt_tokens", 0)
            completion_tokens = getattr(usage, "completion_tokens", 0)
            total_tokens = prompt_tokens + completion_tokens
            finish_reason = resp.choices[0].finish_reason or "stop"
            content = resp.choices[0].message.content or ""

            span.ended_at = datetime.now(UTC)
            span.duration_ms = duration * 1000
            span.output = content
            cost = _estimate_cost(self._model, prompt_tokens, completion_tokens)
            span.metadata = {
                "model": self._model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated_cost": cost,
                "finish_reason": finish_reason,
                "duration_ms": span.duration_ms,
            }

            LLM_CALL_TOTAL.labels(model=self._model, status="ok").inc()
            LLM_TOKEN_TOTAL.labels(model=self._model, token_type="prompt").inc(prompt_tokens)
            LLM_TOKEN_TOTAL.labels(model=self._model, token_type="completion").inc(completion_tokens)
            LLM_CALL_DURATION_SECONDS.labels(model=self._model).observe(duration)
            LLM_COST_TOTAL.labels(model=self._model).inc(cost)

            return LLMResult(
                content=content,
                model=self._model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                finish_reason=finish_reason,
                raw=resp,
            )
        finally:
            self._tracer._pop()
