"""LLM 调用 → Langfuse generation 的统一记录入口

所有 LLM 调用点（流式/非流式）复用此入口，保证 usage/cost 口径一致。
未启用 Langfuse 或 tracer 缺失时静默短路。
"""

from __future__ import annotations

from typing import Any


def record_generation(
    tracer: Any,
    name: str,
    *,
    model: str,
    input: Any = None,
    output: Any = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cache_hit_tokens: int = 0,
) -> None:
    record = getattr(tracer, "record_generation", None)
    if record is None:
        return

    from app.config import get_settings
    from app.observability.traced_llm import _estimate_cost

    settings = get_settings()
    total = prompt_tokens + completion_tokens
    cost = _estimate_cost(
        model,
        prompt_tokens,
        completion_tokens,
        cache_hit_tokens=cache_hit_tokens,
        cache_hit_factor=settings.llm.cache_hit_price_factor,
    )
    record(
        name,
        model=model,
        input=input,
        output=output,
        usage={"input": prompt_tokens, "output": completion_tokens, "total": total},
        cost={"total": cost},
    )
