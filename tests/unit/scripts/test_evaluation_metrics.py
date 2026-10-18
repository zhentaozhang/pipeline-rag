"""scripts/evaluation/metrics.py 单元测试"""

from unittest.mock import AsyncMock, patch

import pytest

from scripts.evaluation.metrics import (
    compute_answer_correctness,
    compute_context_recall,
    compute_lexical_context_recall,
    compute_recall_at_k,
    compute_semantic_context_recall,
)


def test_compute_recall_at_k_normal():
    retrieved = [
        "合同期限3个月以上不满1年试用期1个月",
        "转正考核要求评分大于70分且无违纪",
        "无关内容段落",
    ]
    relevant = ["试用期1个月", "转正考核要求评分大于70分"]
    score = compute_recall_at_k(retrieved, relevant, k=2)
    assert score == 1.0

    score_k1 = compute_recall_at_k(retrieved, relevant, k=1)
    assert score_k1 == 0.5


def test_compute_recall_at_k_short_tokens():
    retrieved = ["这是 M3 级经理的差旅住宿标准为 600元/晚"]
    relevant = ["M3", "600元/晚"]
    score = compute_recall_at_k(retrieved, relevant, k=1)
    assert score == 1.0


def test_compute_recall_at_k_empty():
    assert compute_recall_at_k([], ["something"], 5) == 0.0
    assert compute_recall_at_k(["something"], [], 5) == 0.0


def test_compute_lexical_context_recall():
    retrieved = ["试用期转正条件为考核评分大于等于70分且无违纪"]
    relevant = ["考核评分大于等于70分", "无违纪"]
    score = compute_lexical_context_recall(retrieved, relevant)
    assert score == 1.0
    # 兼容别名
    assert compute_context_recall(retrieved, relevant) == 1.0


@pytest.mark.asyncio
async def test_compute_semantic_context_recall():
    from app.observability.metrics.base import MetricResult

    with patch(
        "app.observability.metrics.context_recall.ContextRecallMetric.ascore",
        new=AsyncMock(return_value=MetricResult(metric_name="context_recall", value=0.92)),
    ):
        score = await compute_semantic_context_recall(
            question="试用期多久",
            retrieved_contexts=["3个月以上试用期1个月"],
            ground_truth_answer="3个月试用期1个月",
        )
        assert score == 0.92


@pytest.mark.asyncio
async def test_compute_answer_correctness_proxy():
    from app.observability.metrics.base import MetricResult

    with patch(
        "app.observability.metrics.answer_correctness.AnswerCorrectnessMetric.ascore",
        new=AsyncMock(return_value=MetricResult(metric_name="answer_correctness", value=0.95)),
    ):
        score = await compute_answer_correctness(
            fallback=None,
            question="试用期薪资是多少",
            generated_answer="为转正薪资的80%",
            ground_truth_answer="为转正薪酬的80%",
        )
        assert score == 0.95
