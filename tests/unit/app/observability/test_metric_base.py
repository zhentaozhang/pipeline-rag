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


@pytest.fixture
def jev_on(monkeypatch):
    """启用 JEV 评测开关（单测默认全局关闭）。"""
    from app.config import get_settings

    for flag in (
        "answer_relevancy_enabled",
        "answer_correctness_enabled",
        "faithfulness_eval_enabled",
        "context_precision_enabled",
        "context_recall_enabled",
    ):
        monkeypatch.setattr(get_settings().jev, flag, True, raising=False)
    yield


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
async def test_answer_relevancy_jev_handles_none_score_data(jev_on):
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
async def test_answer_relevancy_jev_success_path(jev_on):
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
        # 期望得分：0.88 * 0.75 + 0.12 * 1.0 = 0.78
        assert res.value == 0.78
        assert res.metadata.get("evaluated_by") == "jev-system-one"
        assert res.metadata.get("level") == "高度相关"
        assert res.metadata.get("confidence") == 0.88


@pytest.mark.asyncio
async def test_answer_relevancy_jev_exception_falls_back_to_llm(jev_on):
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


@pytest.mark.asyncio
async def test_answer_correctness_jev_success_path(jev_on):
    """JEV 正常返回完整结构时，解析等级评分与置信度"""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.observability.metrics.answer_correctness import AnswerCorrectnessMetric

    metric = AnswerCorrectnessMetric()
    mock_jev = MagicMock()
    mock_jev.system_one = AsyncMock(
        return_value={
            "correctness": {
                "score": "完全一致",
                "confidence": 0.93,
                "distribution": {"完全一致": 0.93, "基本一致": 0.07},
            }
        }
    )

    with patch("app.infra.jev_client.get_jev_client", return_value=mock_jev):
        res = await metric.ascore(
            question="试用期多久？",
            answer="3年以上或无固定期限为6个月。",
            contexts=[],
            ground_truth="3年以上或无固定期限试用期6个月。",
        )
        assert res.metric_name == "answer_correctness"
        assert res.value == 1.0
        assert res.metadata.get("evaluated_by") == "jev-system-one"
        assert res.metadata.get("level") == "完全一致"
        assert res.metadata.get("confidence") == 0.93


@pytest.mark.asyncio
async def test_answer_correctness_jev_invalid_falls_back_to_llm(jev_on):
    """JEV 返回缺失/非法结构时回退到 LLM 打分"""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.observability.metrics.answer_correctness import AnswerCorrectnessMetric

    metric = AnswerCorrectnessMetric(eval_llm=_FakeEvalLLM(), model="deepseek-chat")
    mock_jev = MagicMock()
    mock_jev.system_one = AsyncMock(return_value={"correctness": None})
    metric._call_llm = AsyncMock(return_value="80")

    with patch("app.infra.jev_client.get_jev_client", return_value=mock_jev):
        res = await metric.ascore(
            question="q",
            answer="a",
            contexts=[],
            ground_truth="gt",
        )
        assert res.value == 0.80
        assert res.metadata.get("evaluated_by") != "jev-system-one"


@pytest.mark.asyncio
async def test_answer_correctness_jev_exception_falls_back_to_llm(jev_on):
    """JEV 抛异常时平滑降级到 LLM"""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.observability.metrics.answer_correctness import AnswerCorrectnessMetric

    metric = AnswerCorrectnessMetric(eval_llm=_FakeEvalLLM(), model="deepseek-chat")
    mock_jev = MagicMock()
    mock_jev.system_one = AsyncMock(side_effect=RuntimeError("JEV down"))
    metric._call_llm = AsyncMock(return_value="60")

    with patch("app.infra.jev_client.get_jev_client", return_value=mock_jev):
        res = await metric.ascore(
            question="q",
            answer="a",
            contexts=[],
            ground_truth="gt",
        )
        assert res.value == 0.60
        assert "LLM scored" in res.reason


@pytest.mark.asyncio
async def test_answer_relevancy_fallback_without_distribution(jev_on):
    """当 JEV 未返回 distribution 时，平滑回退至 level_map 离散打分"""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.observability.metrics.answer_relevancy import AnswerRelevancyMetric

    metric = AnswerRelevancyMetric()
    mock_jev = MagicMock()
    mock_jev.system_one = AsyncMock(
        return_value={
            "relevancy": {
                "score": "基本相关",
                "confidence": 0.90,
                # 无 distribution 字段
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
        assert res.value == 0.50
        assert res.metadata.get("level") == "基本相关"


def test_faithfulness_compose_bounded_context():
    """验证 _compose_bounded_context 严格遵循 chunk 边界且不中间截断文本"""
    from app.observability.metrics.faithfulness import _compose_bounded_context

    chunks = [
        "第一段内容：" + "A" * 500,
        "第二段内容：" + "B" * 500,
        "第三段内容：" + "C" * 500,
    ]
    # 上限 1100 字符，前两段加上分隔符共约 1020 字符，第三段不应被切半，而应完全排除
    result = _compose_bounded_context(chunks, max_chars=1100)
    assert "第一段内容" in result
    assert "第二段内容" in result
    assert "第三段内容" not in result
    assert "---" in result


@pytest.mark.asyncio
async def test_context_precision_1500_char_boundary(jev_on):
    """验证 ContextPrecisionMetric 向 JEV 传递 chunk 时支持达 1500 字符长文本"""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.observability.metrics.context_precision import ContextPrecisionMetric

    metric = ContextPrecisionMetric()
    mock_jev = MagicMock()
    recorded_questions = {}

    async def _mock_sys_one(state, questions):
        nonlocal recorded_questions
        recorded_questions = questions
        return {"chunk_0": {"noul": 0.95}}

    mock_jev.system_one = AsyncMock(side_effect=_mock_sys_one)

    long_chunk = "核心事实证据：" + "Z" * 1200 + "关键末尾事实"
    with patch("app.infra.jev_client.get_jev_client", return_value=mock_jev):
        res = await metric.ascore(
            question="测试问题",
            answer="测试回答",
            contexts=[long_chunk],
        )
        assert res.metric_name == "context_precision"
        assert res.value == 1.0
        # 验证 1200+ 字符未在 280 处被截断
        assert "关键末尾事实" in recorded_questions["chunk_0"]["instructions"]


@pytest.mark.asyncio
async def test_rag_evaluation_service_proxy():
    """验证 RAGEvaluationService 适配器透明代理至 EvaluationPipeline 而非返回空字典"""
    from unittest.mock import AsyncMock, patch

    from app.observability.metrics.base import MetricResult
    from app.rag.evaluation import RAGEvaluationService

    service = RAGEvaluationService()
    fake_results = [
        MetricResult(metric_name="faithfulness", value=0.9),
        MetricResult(metric_name="answer_relevancy", value=0.85),
    ]

    with patch.object(
        service._get_standard_pipeline(), "run", new=AsyncMock(return_value=fake_results)
    ):
        res = await service.evaluate(
            conversation_id="conv_1",
            exchange_id=1,
            question="q",
            answer="a",
            contexts=["c"],
        )
        assert res == {"faithfulness": 0.9, "answer_relevancy": 0.85}
