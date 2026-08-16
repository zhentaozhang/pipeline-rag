"""P0 · Prompt Caching：缓存字段解析 / 成本折扣 / provider 兼容"""

from types import SimpleNamespace

import pytest

from app.observability.traced_llm import LLMResult, _estimate_cost


def test_estimate_cost_with_cache_discount():
    """命中 token 按折扣单价计费（默认 0.1）"""
    # deepseek-chat: 输入 $0.0005/M，输出 $0.0015/M
    cost_hit = _estimate_cost("deepseek-chat", 1000, 0, cache_hit_tokens=1000, cache_hit_factor=0.1)
    cost_miss = _estimate_cost("deepseek-chat", 1000, 0, cache_hit_tokens=0, cache_hit_factor=0.1)
    assert cost_hit == pytest.approx(0.00005, abs=1e-6)
    assert cost_miss == pytest.approx(0.0005, abs=1e-6)
    assert cost_hit < cost_miss


def test_estimate_cost_mixed():
    cost = _estimate_cost("deepseek-chat", 2000, 1000, cache_hit_tokens=1500, cache_hit_factor=0.1)
    expected = (500 / 1000 * 0.0005) + (1500 / 1000 * 0.0005 * 0.1) + (1000 / 1000 * 0.0015)
    assert cost == pytest.approx(expected, abs=1e-7)


class _FakeUsage:
    prompt_tokens = 3000
    completion_tokens = 500
    prompt_cache_hit_tokens = 2000
    prompt_cache_miss_tokens = 1000


class _FakeResp:
    def __init__(self, with_cache: bool = True):
        self.usage = _FakeUsage() if with_cache else SimpleNamespace(
            prompt_tokens=100, completion_tokens=10
        )
        self.choices = [
            SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="hi"))
        ]


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp
        self.calls = 0

    @property
    def chat(self):
        return SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    async def _create(self, **kwargs):
        self.calls += 1
        return self._resp


class _FakeTracer:
    current_span_id = None
    trace_id = "t"

    def __init__(self):
        self.spans = []

    def _push(self, span):
        self.spans.append(span)

    def _pop(self):
        return self.spans.pop()


@pytest.mark.asyncio
async def test_agenerate_parses_cache_usage():
    from app.observability.traced_llm import TracedLLM

    tracer = _FakeTracer()
    client = _FakeClient(_FakeResp(with_cache=True))
    result = await TracedLLM(tracer, client, "deepseek-chat").agenerate(
        [{"role": "user", "content": "q"}]
    )

    assert isinstance(result, LLMResult)
    assert result.prompt_cache_hit_tokens == 2000
    assert result.prompt_cache_miss_tokens == 1000
    assert client.calls == 1


@pytest.mark.asyncio
async def test_agenerate_missing_cache_fields_no_error():
    from app.observability.traced_llm import TracedLLM

    tracer = _FakeTracer()
    client = _FakeClient(_FakeResp(with_cache=False))
    result = await TracedLLM(tracer, client, "deepseek-chat").agenerate(
        [{"role": "user", "content": "q"}]
    )

    assert result.prompt_cache_hit_tokens == 0
    assert result.prompt_cache_miss_tokens == 0
