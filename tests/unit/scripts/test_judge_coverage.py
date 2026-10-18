"""判分覆盖率：生成/判分失败的样本必须被显式统计，不能让均值悄悄只代表子集。"""

from scripts.evaluation.datasets.base import EvalResult
from scripts.evaluation.runner import _judge_coverage, _min_judge_coverage


def _r(faith: float | None, acc: float | None) -> EvalResult:
    return EvalResult(
        question_id="q",
        question="q",
        faithfulness_score=faith,
        answer_correctness_score=acc,
    )


FIELDS = {"faithfulness": "faithfulness_score", "answer_correctness": "answer_correctness_score"}


class TestJudgeCoverage:
    def test_all_scored_is_one(self):
        cov = _judge_coverage([_r(1.0, 0.9), _r(0.8, 0.7)], FIELDS)
        assert cov == {"faithfulness": 1.0, "answer_correctness": 1.0}
        assert _min_judge_coverage(cov) == 1.0

    def test_partial_scoring_reports_fraction(self):
        # 真实事故：85 题只判了 38 题，均值仍按 38 题报出高 0.06 的假分数
        cov = _judge_coverage([_r(1.0, 0.9), _r(None, None), _r(None, None), _r(None, None)], FIELDS)
        assert cov["faithfulness"] == 0.25
        assert _min_judge_coverage(cov) == 0.25

    def test_empty_results_is_none(self):
        cov = _judge_coverage([], FIELDS)
        assert cov == {"faithfulness": None, "answer_correctness": None}
        assert _min_judge_coverage(cov) is None

    def test_min_picks_worst_metric(self):
        cov = {"faithfulness": 1.0, "answer_correctness": 0.5}
        assert _min_judge_coverage(cov) == 0.5
