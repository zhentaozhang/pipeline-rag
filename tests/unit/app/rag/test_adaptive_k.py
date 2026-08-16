"""调研 P2：查询自适应 Top-k 截断——陡降截断 / 平坦保留 / 上下限"""


from app.rag.adaptive_k import adaptive_truncate


class _Doc:
    def __init__(self, cid: str, score: float):
        self.chunk_id = cid
        self.original_score = score


def _docs(scores: list[float]):
    return [_Doc(f"c{i}", s) for i, s in enumerate(scores)]


def test_steep_drop_truncates_early():
    """简单查询：得分陡降 → 提前截断（省噪声）"""
    docs = _docs([0.95, 0.90, 0.31, 0.20, 0.10])  # 0.31 < 0.95*0.4=0.38 → 截断
    kept = adaptive_truncate(docs, min_k=2, max_k=20, ratio_threshold=0.4)
    assert len(kept) == 2
    assert kept[0].chunk_id == "c0"


def test_flat_tail_keeps_more():
    """复杂查询：得分平坦 → 保留更多（保召回）"""
    docs = _docs([0.60, 0.58, 0.55, 0.52, 0.50])  # 都 ≥ 0.60*0.4=0.24 → 全保留
    kept = adaptive_truncate(docs, min_k=2, max_k=20, ratio_threshold=0.4)
    assert len(kept) == 5


def test_min_k_floor():
    """保底下限：即使得分很低也至少保留 min_k"""
    docs = _docs([0.50, 0.01, 0.005, 0.001])
    kept = adaptive_truncate(docs, min_k=3, max_k=20, ratio_threshold=0.4)
    assert len(kept) == 3  # 0.01 < 0.5*0.4 → 截断，但保住前 3（min_k）


def test_max_k_cap():
    """上限：得分都高时最多保留 max_k"""
    docs = _docs([0.90] * 30)
    kept = adaptive_truncate(docs, min_k=2, max_k=10, ratio_threshold=0.4)
    assert len(kept) == 10


def test_zero_scores_fallback_to_min_k():
    """得分全 0（无区分度）→ 保底 min_k，不误伤"""
    docs = _docs([0.0] * 6)
    kept = adaptive_truncate(docs, min_k=2, max_k=20, ratio_threshold=0.4)
    assert len(kept) == 2


def test_empty_and_max_k_zero():
    assert adaptive_truncate([], 2, 20, 0.4) == []
    assert len(adaptive_truncate(_docs([0.9, 0.8]), 2, 0, 0.4)) == 2
