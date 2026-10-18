"""any-of gold 口径的召回指标（多解条款题）。"""

from scripts.evaluation.metrics import compute_any_of_mrr, compute_any_of_recall_at_k


def test_any_of_hit_when_first_gold_in_top_k():
    assert compute_any_of_recall_at_k(["c1", "c2"], {"c1", "c2", "c3"}, 5) == 1.0


def test_any_of_miss_when_no_gold_in_top_k():
    assert compute_any_of_recall_at_k(["x1", "x2"], {"c1", "c2"}, 2) == 0.0


def test_any_of_none_when_no_gold():
    assert compute_any_of_recall_at_k(["x1"], set(), 5) is None


def test_any_of_mrr_uses_first_matching_rank():
    assert compute_any_of_mrr(["x1", "c2", "c3"], {"c2", "c3"}) == 0.5


def test_any_of_mrr_zero_when_absent():
    assert compute_any_of_mrr(["x1"], {"c9"}) == 0.0
