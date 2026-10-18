"""chunk 级召回指标（Task 1）——用证据 ID 精确判定命中，替代 bigram 模糊匹配。"""

from __future__ import annotations

import pytest

from scripts.evaluation.metrics import (
    compute_id_mrr,
    compute_id_ndcg_at_k,
    compute_id_recall_at_k,
)


class TestIdRecallAtK:
    def test_hit_within_k(self):
        assert compute_id_recall_at_k(["a", "b", "c"], {"c"}, 3) == 1.0

    def test_hit_outside_k_is_missed(self):
        assert compute_id_recall_at_k(["a", "b", "c"], {"c"}, 2) == 0.0

    def test_partial_coverage(self):
        assert compute_id_recall_at_k(["a", "b"], {"a", "z"}, 2) == 0.5

    def test_empty_gold_returns_none(self):
        """拒答题没有 gold，不能记 0 分拉低均值，返回 None 由调用方剔除。"""
        assert compute_id_recall_at_k(["a"], set(), 5) is None

    def test_empty_retrieved_scores_zero(self):
        assert compute_id_recall_at_k([], {"a"}, 5) == 0.0

    def test_mixed_int_and_str_ids_are_equal(self):
        """DB 里是 int，Evidence.chunk_id 是 str，比对必须归一化。"""
        assert compute_id_recall_at_k([1, 2], {"2"}, 2) == 1.0
        assert compute_id_recall_at_k(["1", "2"], {2}, 2) == 1.0

    def test_none_ids_are_ignored(self):
        assert compute_id_recall_at_k([None, "a"], {"a"}, 2) == 1.0

    def test_blank_ids_are_ignored(self):
        assert compute_id_recall_at_k(["", "a"], {"a"}, 2) == 1.0

    def test_bad_k_returns_zero(self):
        assert compute_id_recall_at_k(["a"], {"a"}, 0) == 0.0

    def test_preserves_rank_order_semantics(self):
        """顺序即名次：同一 gold 在第 5 名则 k=4 不算命中。"""
        ids = ["x", "x", "x", "x", "g"]
        assert compute_id_recall_at_k(ids, {"g"}, 5) == 1.0
        assert compute_id_recall_at_k(ids, {"g"}, 4) == 0.0


class TestIdMrr:
    def test_first_hit_rank(self):
        assert compute_id_mrr(["a", "b", "c"], {"c"}) == pytest.approx(round(1 / 3, 4))

    def test_hit_at_rank_one(self):
        assert compute_id_mrr(["a", "b"], {"a"}) == 1.0

    def test_no_hit_returns_zero(self):
        assert compute_id_mrr(["a", "b"], {"z"}) == 0.0

    def test_empty_gold_returns_none(self):
        assert compute_id_mrr(["a"], set()) is None

    def test_empty_retrieved_returns_zero(self):
        assert compute_id_mrr([], {"a"}) == 0.0


class TestIdNdcgAtK:
    def test_perfect_order_scores_one(self):
        assert compute_id_ndcg_at_k(["g1", "g2", "x"], {"g1", "g2"}, 3) == 1.0

    def test_swap_of_equal_gains_keeps_score(self):
        """二值相关性下两条 gold 互换名次不改变 nDCG（增益相同）。"""
        a = compute_id_ndcg_at_k(["g1", "g2"], {"g1", "g2"}, 2)
        b = compute_id_ndcg_at_k(["g2", "g1"], {"g1", "g2"}, 2)
        assert b == pytest.approx(a)

    def test_hit_only_at_second_position(self):
        score = compute_id_ndcg_at_k(["x", "g1"], {"g1"}, 2)
        assert 0.0 < score < 1.0

    def test_empty_gold_returns_none(self):
        assert compute_id_ndcg_at_k(["a"], set(), 5) is None

    def test_dedup_gold(self):
        """同一 gold 只计一次增益。"""
        assert compute_id_ndcg_at_k(["g", "g"], {"g"}, 2) == 1.0
