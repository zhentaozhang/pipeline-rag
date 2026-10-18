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


class TestPairedBootstrapDelta:
    """配对 bootstrap：判断两次评测的差值是不是噪声。"""

    def test_identical_series_has_zero_delta(self):
        from scripts.evaluation.metrics import paired_bootstrap_delta

        base = [1.0, 0.5, 0.0, 0.8, 0.2]
        r = paired_bootstrap_delta(base, list(base))
        assert r["delta"] == pytest.approx(0.0)
        assert r["ci_low"] == pytest.approx(0.0)
        assert r["ci_high"] == pytest.approx(0.0)
        assert r["significant"] is False

    def test_clear_improvement_is_significant(self):
        from scripts.evaluation.metrics import paired_bootstrap_delta

        base = [0.0, 0.1, 0.2, 0.0, 0.1, 0.0, 0.2, 0.1, 0.0, 0.2]
        opt = [x + 0.5 for x in base]
        r = paired_bootstrap_delta(base, opt)
        assert r["delta"] == pytest.approx(0.5)
        assert r["ci_low"] > 0
        assert r["significant"] is True

    def test_mixed_noise_is_not_significant(self):
        from scripts.evaluation.metrics import paired_bootstrap_delta

        base = [0.0, 1.0] * 10
        opt = [0.1, 0.9] * 10
        r = paired_bootstrap_delta(base, opt)
        assert r["delta"] == pytest.approx(0.0)
        assert r["significant"] is False
        assert r["ci_low"] < 0 < r["ci_high"]

    def test_deterministic_with_seed(self):
        from scripts.evaluation.metrics import paired_bootstrap_delta

        base = [0.1 * i for i in range(20)]
        opt = [0.1 * i + 0.05 for i in range(20)]
        r1 = paired_bootstrap_delta(base, opt, seed=7)
        r2 = paired_bootstrap_delta(base, opt, seed=7)
        assert r1 == r2

    def test_length_mismatch_raises(self):
        from scripts.evaluation.metrics import paired_bootstrap_delta

        with pytest.raises(ValueError):
            paired_bootstrap_delta([0.1, 0.2], [0.1])

    def test_empty_series(self):
        from scripts.evaluation.metrics import paired_bootstrap_delta

        r = paired_bootstrap_delta([], [])
        assert r["delta"] == pytest.approx(0.0)
        assert r["significant"] is False

    def test_extract_metric_series_pairs_by_question_id(self):
        from scripts.evaluation.metrics import extract_metric_series

        base = {
            "results": [
                {"question_id": "a", "recall_at_5": 1.0},
                {"question_id": "b", "recall_at_5": 0.0},
            ]
        }
        opt = {
            "results": [
                {"question_id": "b", "recall_at_5": 1.0},
                {"question_id": "a", "recall_at_5": 1.0},
            ]
        }
        b_vals, o_vals = extract_metric_series(base, opt, "recall_at_5")
        assert b_vals == [1.0, 0.0]
        assert o_vals == [1.0, 1.0]

    def test_extract_metric_series_skips_missing_questions(self):
        from scripts.evaluation.metrics import extract_metric_series

        base = {
            "results": [
                {"question_id": "a", "recall_at_5": 1.0},
                {"question_id": "b", "recall_at_5": 0.0},
            ]
        }
        opt = {"results": [{"question_id": "a", "recall_at_5": 0.0}]}
        b_vals, o_vals = extract_metric_series(base, opt, "recall_at_5")
        assert b_vals == [1.0]
        assert o_vals == [0.0]
