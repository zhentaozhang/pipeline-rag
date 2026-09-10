"""LLM 成本估算（provider 无关，含 Prompt Caching 折扣）

命中 token 按折扣单价计费（DeepSeek context caching 命中约 1/10 单价）。
被 llm_observe 与 service_finalizer 共用，保证全链路成本口径一致。
"""

from __future__ import annotations

MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "qwen-plus": (0.0008, 0.002),
    "qwen-max": (0.002, 0.006),
    "deepseek-chat": (0.0005, 0.0015),
}


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_hit_tokens: int = 0,
    cache_hit_factor: float = 0.1,
) -> float:
    """成本估算（区分缓存命中/未命中单价）"""
    prices = MODEL_PRICES.get(model, (0.001, 0.002))
    cache_miss_tokens = max(0, prompt_tokens - cache_hit_tokens)
    prompt_cost = (cache_miss_tokens / 1000 * prices[0]) + (
        cache_hit_tokens / 1000 * prices[0] * cache_hit_factor
    )
    return prompt_cost + (completion_tokens / 1000 * prices[1])
