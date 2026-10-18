"""McNemar 精确检验：配对二元结果（命中/未命中）的显著性。

为什么用它：召回类指标是逐题 0/1，配对 bootstrap 看均值差，
而 McNemar 直接看"只有 A 命中"与"只有 B 命中"的对称性，
对 n=30 这种小样本比均值差更敏感、更可解释。
"""

import pytest

from scripts.evaluation.metrics import mcnemar_exact, paired_hit_counts


def test_paired_hit_counts_only_counts_discordant_pairs():
    base = {"q1": 1.0, "q2": 0.0, "q3": 1.0, "q4": 0.0}
    opt = {"q1": 1.0, "q2": 1.0, "q3": 0.0, "q4": 0.0}
    only_base, only_opt = paired_hit_counts(base, opt)
    assert only_base == 1  # q3
    assert only_opt == 1  # q2


def test_mcnemar_no_discordant_pairs_is_p_one():
    assert mcnemar_exact(0, 0) == 1.0


def test_mcnemar_strongly_asymmetric_is_significant():
    p = mcnemar_exact(1, 12)
    assert p < 0.01


def test_mcnemar_balanced_is_not_significant():
    assert mcnemar_exact(5, 5) > 0.5


def test_mcnemar_is_symmetric():
    assert mcnemar_exact(1, 12) == pytest.approx(mcnemar_exact(12, 1))
