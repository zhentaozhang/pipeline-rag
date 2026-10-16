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


@pytest.mark.asyncio
async def test_answer_relevancy_jev_handles_none_score_data():
    """验证当 JEV 返回 answers 中 relevancy 为 None 时，AnswerRelevancyMetric 触发回退到 LLM"""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.observability.metrics.answer_relevancy import AnswerRelevancyMetric

    metric = AnswerRelevancyMetric(eval_llm=_FakeEvalLLM(), model="deepseek-chat")
    mock_jev = MagicMock()
    # 模拟 JEV 返回 relevancy 为 None 的不完整情况
    mock_jev.system_one = AsyncMock(return_value={"relevancy": None})
    metric._call_llm = AsyncMock(return_value="90")

    with patch("app.infra.jev_client.get_jev_client", return_value=mock_jev):
        res = await metric.ascore(
            question="什么是 RAG？",
            answer="RAG 是检索增强生成技术。",
            contexts=["RAG 技术结合了检索系统与大语言模型。"],
        )
        assert res.metric_name == "answer_relevancy"
        # 缺失有效打分结构触发 LLM 回退，分值为 0.90
        assert res.value == 0.90
        assert res.metadata.get("evaluated_by") != "jev-system-one"


@pytest.mark.asyncio
async def test_answer_relevancy_jev_success_path():
    """验证当 JEV 正常返回完整结构时，正常解析 JEV 打分与置信度"""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.observability.metrics.answer_relevancy import AnswerRelevancyMetric

    metric = AnswerRelevancyMetric()
    mock_jev = MagicMock()
    mock_jev.system_one = AsyncMock(
        return_value={
            "relevancy": {
                "score": "高度相关",
                "confidence": 0.88,
                "distribution": {"高度相关": 0.88, "完全切题": 0.12},
            }
        }
    )

    with patch("app.infra.jev_client.get_jev_client", return_value=mock_jev):
        res = await metric.ascore(
            question="什么是 RAG？",
            answer="RAG 是检索增强生成技术。",
            contexts=["RAG 技术结合了检索系统与大语言模型。"],
        )
        assert res.metric_name == "answer_relevancy"
        assert res.value == 0.75
        assert res.metadata.get("evaluated_by") == "jev-system-one"
        assert res.metadata.get("level") == "高度相关"
        assert res.metadata.get("confidence") == 0.88


@pytest.mark.asyncio
async def test_answer_relevancy_jev_exception_falls_back_to_llm():
    """验证当 JEV 抛出异常时，AnswerRelevancyMetric 平滑降级到 LLM"""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.observability.metrics.answer_relevancy import AnswerRelevancyMetric

    metric = AnswerRelevancyMetric(eval_llm=_FakeEvalLLM(), model="deepseek-chat")
    mock_jev = MagicMock()
    mock_jev.system_one = AsyncMock(side_effect=RuntimeError("JEV service down"))

    # 模拟 LLM 返回打分 85
    metric._call_llm = AsyncMock(return_value="85")

    with patch("app.infra.jev_client.get_jev_client", return_value=mock_jev):
        res = await metric.ascore(
            question="什么是 RAG？",
            answer="RAG 是检索增强生成技术。",
            contexts=["RAG 技术结合了检索系统与大语言模型。"],
        )
        assert res.metric_name == "answer_relevancy"
        assert res.value == 0.85
        assert "LLM scored" in res.reason
