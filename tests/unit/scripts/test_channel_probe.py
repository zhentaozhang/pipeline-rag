"""通道健康度聚合（纯函数）：直接衡量关键词通道本身是否有效。"""

from scripts.evaluation.channel_probe import summarize_probe


def test_summarize_probe_counts_zero_hits_and_coverage():
    rows = [
        {"hits": ["c1", "c2"], "gold": {"c1"}},
        {"hits": [], "gold": {"c9"}},
        {"hits": ["c3"], "gold": set()},
    ]
    out = summarize_probe(rows, k=2)
    assert out["questions"] == 3
    assert out["zero_hit_rate"] == round(1 / 3, 4)
    assert out["avg_hits"] == round(3 / 3, 2)
    assert out["gold_coverage_at_k"] == 0.5
    assert out["mrr"] == 0.5  # 两道有 gold 的题里只有一道命中 rank-1


def test_summarize_probe_handles_no_gold():
    rows = [{"hits": [], "gold": set()}]
    out = summarize_probe(rows, k=5)
    assert out["gold_coverage_at_k"] is None
    assert out["mrr"] is None


def test_summarize_probe_handles_empty_rows():
    out = summarize_probe([], k=5)
    assert out["questions"] == 0
    assert out["zero_hit_rate"] is None
