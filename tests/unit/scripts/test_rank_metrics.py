"""MRR / nDCG@k 检索排序指标纯逻辑测试（无网络）。"""

from scripts.evaluation.metrics import compute_mrr, compute_ndcg_at_k

REL = ["试用期不得超过六个月"]


class TestMrr:
    def test_first_hit_rank1(self):
        assert compute_mrr(["试用期不得超过六个月的规定"], REL) == 1.0

    def test_hit_rank2(self):
        assert compute_mrr(["无关内容", "试用期不得超过六个月的规定"], REL) == 0.5

    def test_no_hit(self):
        assert compute_mrr(["完全无关的一段文字"], REL) == 0.0

    def test_empty_inputs(self):
        assert compute_mrr([], REL) == 0.0
        assert compute_mrr(["x"], []) == 0.0


class TestNdcg:
    def test_perfect_at_rank1(self):
        assert compute_ndcg_at_k(["试用期不得超过六个月的规定"], REL, 5) == 1.0

    def test_rank2_between_zero_and_one(self):
        v = compute_ndcg_at_k(["无关", "试用期不得超过六个月的规定"], REL, 5)
        assert 0.0 < v < 1.0

    def test_no_hit_is_zero(self):
        assert compute_ndcg_at_k(["完全无关的一段文字"], REL, 5) == 0.0

    def test_invalid_k(self):
        assert compute_ndcg_at_k(["试用期不得超过六个月的规定"], REL, 0) == 0.0
