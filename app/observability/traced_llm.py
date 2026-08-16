from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.observability.enums import SpanKind
from app.observability.models import SpanContext
from app.observability.tracer import (
    LLM_CACHE_HIT_TOKEN_TOTAL,
    LLM_CACHE_MISS_TOKEN_TOTAL,
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
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0


_MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "qwen-plus": (0.0008, 0.002),
    "qwen-max": (0.002, 0.006),
    "deepseek-chat": (0.0005, 0.0015),
}


def _estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_hit_tokens: int = 0,
    cache_hit_factor: float = 0.1,
) -> float:
    """成本估算（P0：区分缓存命中/未命中单价——DeepSeek 命中约 1/10）"""
    prices = _MODEL_PRICES.get(model, (0.001, 0.002))
    cache_miss_tokens = max(0, prompt_tokens - cache_hit_tokens)
    prompt_cost = (cache_miss_tokens / 1000 * prices[0]) + (
        cache_hit_tokens / 1000 * prices[0] * cache_hit_factor
    )
    return prompt_cost + (completion_tokens / 1000 * prices[1])


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
            # Prompt Caching（P0）：provider 无关解析缓存命中/未命中 token（缺失→0）
            cache_hit_tokens = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
            cache_miss_tokens = getattr(usage, "prompt_cache_miss_tokens", 0) or 0
            finish_reason = resp.choices[0].finish_reason or "stop"
            content = resp.choices[0].message.content or ""

            from app.config import get_settings

            cache_hit_factor = get_settings().llm.cache_hit_price_factor
            span.ended_at = datetime.now(UTC)
            span.duration_ms = duration * 1000
            span.output = content
            cost = _estimate_cost(
                self._model,
                prompt_tokens,
                completion_tokens,
                cache_hit_tokens,
                cache_hit_factor,
            )
            span.metadata = {
                "model": self._model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "prompt_cache_hit_tokens": cache_hit_tokens,
                "prompt_cache_miss_tokens": cache_miss_tokens,
                "cache_hit_ratio": (
                    round(cache_hit_tokens / prompt_tokens, 4) if prompt_tokens > 0 else 0.0
                ),
                "estimated_cost": cost,
                "finish_reason": finish_reason,
                "duration_ms": span.duration_ms,
            }

            LLM_CALL_TOTAL.labels(model=self._model, status="ok").inc()
            LLM_TOKEN_TOTAL.labels(model=self._model, token_type="prompt").inc(prompt_tokens)
            LLM_TOKEN_TOTAL.labels(model=self._model, token_type="completion").inc(
                completion_tokens
            )
            LLM_CACHE_HIT_TOKEN_TOTAL.labels(model=self._model).inc(cache_hit_tokens)
            LLM_CACHE_MISS_TOKEN_TOTAL.labels(model=self._model).inc(cache_miss_tokens)
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
                prompt_cache_hit_tokens=cache_hit_tokens,
                prompt_cache_miss_tokens=cache_miss_tokens,
            )
        finally:
            self._tracer._pop()
