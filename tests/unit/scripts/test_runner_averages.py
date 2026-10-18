"""评测均值：没有样本必须给 None，而不是 0.0（后者会被读成"真实得 0 分"）。"""

from __future__ import annotations

from scripts.evaluation.datasets.base import EvalResult
from scripts.evaluation.runner import _print_report


def _result(**overrides) -> EvalResult:
    defaults = dict(question_id="q1", question="问题", status="completed")
    defaults.update(overrides)
    return EvalResult(**defaults)


def test_metrics_without_samples_are_none():
    avg, _ = _print_report([_result(recall_at_5=1.0)], "unit")
    assert avg["recall_at_5"] == 1.0
    assert avg["faithfulness"] is None
    assert avg["answer_correctness"] is None


def test_no_results_at_all_is_all_none():
    avg, _ = _print_report([], "unit")
    assert avg["recall_at_5"] is None
    assert avg["mrr"] is None
