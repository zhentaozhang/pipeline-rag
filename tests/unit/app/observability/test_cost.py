"""LLM 成本估算测试（Prompt Caching 折扣 / 混合 token）"""

import pytest

from app.observability.cost import estimate_cost


def test_estimate_cost_with_cache_discount():
    """命中 token 按折扣单价计费（默认 0.1）"""
    # deepseek-chat: 输入 $0.0005/M，输出 $0.0015/M
    cost_hit = estimate_cost("deepseek-chat", 1000, 0, cache_hit_tokens=1000, cache_hit_factor=0.1)
    cost_miss = estimate_cost("deepseek-chat", 1000, 0, cache_hit_tokens=0, cache_hit_factor=0.1)
    assert cost_hit == pytest.approx(0.00005, abs=1e-6)
    assert cost_miss == pytest.approx(0.0005, abs=1e-6)
    assert cost_hit < cost_miss


def test_estimate_cost_mixed():
    cost = estimate_cost("deepseek-chat", 2000, 1000, cache_hit_tokens=1500, cache_hit_factor=0.1)
    expected = (500 / 1000 * 0.0005) + (1500 / 1000 * 0.0005 * 0.1) + (1000 / 1000 * 0.0015)
    assert cost == pytest.approx(expected, abs=1e-7)


def test_estimate_cost_unknown_model_uses_fallback():
    cost = estimate_cost("unknown-model", 1000, 1000)
    assert cost > 0


def test_estimate_cost_configured_flash_model_uses_table_price():
    # deepseek-v4-flash 在价表内，按 (0.0005, 0.0015) 计，而非默认兜底价 (0.001, 0.002)
    cost = estimate_cost("deepseek-v4-flash", 1000, 1000)
    assert cost == pytest.approx(0.0005 + 0.0015, abs=1e-7)
