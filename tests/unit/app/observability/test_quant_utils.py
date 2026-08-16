"""量化能力补充：Recall@K 与压测分位纯函数"""

from scripts.bench.sse_bench import _percentile
from scripts.evaluation.metrics import compute_recall_at_k


def test_percentile_interpolation():
    assert _percentile([1, 2, 3, 4], 0.5) == 2.5  # 标准中位数
    assert _percentile([1, 2, 3, 4], 0.9) > 3.5
    assert _percentile([], 0.5) == 0


def test_recall_at_k():
    # 检索结果与应检上下文高度重叠（bigram 匹配阈值 0.5）
    relevant = ["差旅报销需要提供发票", "住宿标准为每晚八百元"]
    retrieved = ["差旅报销需要提供发票与行程单", "住宿标准为每晚八百元左右", "商务招待需提前报备"]
    assert compute_recall_at_k(retrieved, relevant, 5) == 1.0
    assert compute_recall_at_k(retrieved, relevant, 1) == 0.5  # 只取 1 条只能覆盖其一
    assert compute_recall_at_k([], relevant, 5) == 0.0
    assert compute_recall_at_k(retrieved, [], 5) == 0.0
