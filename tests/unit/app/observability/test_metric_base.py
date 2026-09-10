"""Metric._call_llm 记录 Langfuse generation 测试"""

from types import SimpleNamespace

import pytest

from app.observability.metrics.base import Metric, MetricResult


class FakeTracer:
    def __init__(self):
        self.calls: list[dict] = []

    def record_generation(self, name, **kwargs):
        self.calls.append({"name": name, **kwargs})


class _FakeEvalLLM:
    def __init__(self):
        self.last_kwargs: dict = {}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
            choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))],
        )


class _DummyMetric(Metric):
    async def ascore(
        self, question, answer, contexts, ground_truth=None, tracer=None
    ) -> MetricResult:
        return MetricResult(metric_name="dummy", value=1.0)


@pytest.mark.asyncio
async def test_metric_call_llm_records_generation():
    metric = _DummyMetric(eval_llm=_FakeEvalLLM(), model="deepseek-chat")
    tracer = FakeTracer()

    content = await metric._call_llm(
        tracer=tracer,
        name="faithfulness_extract",
        messages=[{"role": "user", "content": "q"}],
        temperature=0.0,
    )

    assert content == "hello"
    assert tracer.calls, "应记录 generation"
    call = tracer.calls[0]
    assert call["name"] == "faithfulness_extract"
    assert call["model"] == "deepseek-chat"
    assert call["output"] == "hello"
    assert call["usage"] == {"input": 10, "output": 5, "total": 15}
    assert call["cost"]["total"] > 0


@pytest.mark.asyncio
async def test_metric_call_llm_noop_recording_without_tracer():
    metric = _DummyMetric(eval_llm=_FakeEvalLLM(), model="deepseek-chat")
    content = await metric._call_llm(
        tracer=None,
        name="x",
        messages=[{"role": "user", "content": "q"}],
    )
    assert content == "hello"
