"""标定指标：ECE / AUC / 阈值选择。这些函数决定"某个判据能不能上线"，必须可手算复核。"""

from __future__ import annotations

import pytest

from scripts.evaluation.calibration_metrics import (
    auc,
    choose_threshold,
    expected_calibration_error,
    summarize,
)


class TestAuc:
    def test_perfect_separation(self):
        assert auc([0.9, 0.8], [0.2, 0.1]) == 1.0

    def test_reversed_separation(self):
        assert auc([0.1, 0.2], [0.8, 0.9]) == 0.0

    def test_all_ties_is_half(self):
        assert auc([0.5, 0.5], [0.5, 0.5]) == pytest.approx(0.5)

    def test_partial_tie(self):
        # pos 0.9 胜 2 个；pos 0.5 与 neg 0.5 平局(0.5) + 胜 0.1(1)；故 3.5 / 4 = 0.875
        assert auc([0.9, 0.5], [0.5, 0.1]) == pytest.approx(0.875)

    def test_empty_side_returns_none(self):
        assert auc([], [0.5]) is None
        assert auc([0.5], []) is None


class TestEce:
    def test_perfectly_calibrated_is_zero(self):
        # 一半样本 p=1.0 且都对，一半 p=0.0 且都错
        probs = [1.0] * 5 + [0.0] * 5
        labels = [1] * 5 + [0] * 5
        assert expected_calibration_error(probs, labels) == pytest.approx(0.0)

    def test_systematic_overconfidence(self):
        # 所有样本都说 0.9，但只有一半对 -> ECE = |0.9 - 0.5| = 0.4
        probs = [0.9] * 10
        labels = [1] * 5 + [0] * 5
        assert expected_calibration_error(probs, labels) == pytest.approx(0.4, abs=1e-6)

    def test_bins_are_weighted_by_size(self):
        probs = [0.95] * 9 + [0.05]
        labels = [1] * 9 + [0]
        assert expected_calibration_error(probs, labels) == pytest.approx(0.05, abs=1e-6)

    def test_empty_is_none(self):
        assert expected_calibration_error([], []) is None


class TestChooseThreshold:
    def test_picks_a_threshold_satisfying_the_false_pass_budget(self):
        rows = [(0.9, 1)] * 20 + [(0.4, 0)] * 20
        picked = choose_threshold(rows, max_false_pass=0.05)
        assert picked is not None
        assert picked["threshold"] == pytest.approx(0.9)
        assert picked["false_pass_rate"] == 0.0
        assert picked["true_pass_rate"] == 1.0

    def test_returns_none_when_no_threshold_can_satisfy_the_budget(self):
        # 正样本分数比负样本还低：任何阈值都会放行更多负样本
        rows = [(0.2, 1)] * 10 + [(0.3, 0)] * 10
        assert choose_threshold(rows, max_false_pass=0.0) is None

    def test_prefers_the_lowest_threshold_that_still_meets_the_budget(self):
        # 0.4 会把负样本也放进来（违反预算），0.6 与 0.9 都满足，但 0.6 放行的正样本更多
        rows = [(0.9, 1), (0.6, 1), (0.4, 0)]
        picked = choose_threshold(rows, max_false_pass=0.0)
        assert picked is not None
        assert picked["threshold"] == pytest.approx(0.6)
        assert picked["true_pass_rate"] == 1.0


class TestSummarize:
    def test_reports_rates_and_balanced_accuracy(self):
        rows = [(0.9, 1), (0.8, 1), (0.2, 0), (0.3, 0)]
        summary = summarize(rows)
        assert summary["n"] == 4
        assert summary["positives"] == 2
        assert summary["negatives"] == 2
        assert summary["auc"] == pytest.approx(1.0)
        assert summary["balanced_accuracy_at_0.5"] == pytest.approx(1.0)
        assert summary["pass_rate_at_threshold"] == pytest.approx(0.5)

    def test_marks_a_criterion_unusable_when_auc_below_bar(self):
        rows = [(0.5, 1), (0.5, 0)]
        summary = summarize(rows)
        assert summary["usable"] is False

    def test_usable_requires_auc_and_ece(self):
        rows = [(0.99, 1)] * 10 + [(0.01, 0)] * 10
        summary = summarize(rows)
        assert summary["usable"] is True
