"""LLM 成本估算（provider 无关，含 Prompt Caching 折扣）

命中 token 按折扣单价计费（DeepSeek context caching 命中约 1/10 单价）。
被 llm_observe 与 service_finalizer 共用，保证全链路成本口径一致。

未知模型**不静默兜底**：使用默认价并打印一次告警，避免成本数据被悄悄污染。
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

# 单价（USD / 1K tokens）：(prompt, completion)
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "qwen-plus": (0.0008, 0.002),
    "qwen-max": (0.002, 0.006),
    "deepseek-chat": (0.0005, 0.0015),
    # 近似按 deepseek-chat 计；如官方定价不同，请在 MODEL_PRICES 中据实调整
    "deepseek-v4-flash": (0.0005, 0.0015),
}

_DEFAULT_PRICES: tuple[float, float] = (0.001, 0.002)
_warned_models: set[str] = set()


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_hit_tokens: int = 0,
    cache_hit_factor: float = 0.1,
) -> float:
    """成本估算（区分缓存命中/未命中单价）"""
    prices = MODEL_PRICES.get(model)
    if prices is None:
        if model not in _warned_models:
            _warned_models.add(model)
            logger.warning(
                "unknown model price, using default", model=model, default=_DEFAULT_PRICES
            )
        prices = _DEFAULT_PRICES
    cache_miss_tokens = max(0, prompt_tokens - cache_hit_tokens)
    prompt_cost = (cache_miss_tokens / 1000 * prices[0]) + (
        cache_hit_tokens / 1000 * prices[0] * cache_hit_factor
    )
    return prompt_cost + (completion_tokens / 1000 * prices[1])
