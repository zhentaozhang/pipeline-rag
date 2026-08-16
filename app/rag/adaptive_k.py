"""查询自适应 Top-k 截断（第二轮调研 P2 · Tail-Aware Adaptive-k 简化版）

问题：固定 Top-k 在"简单查询"（高置信、得分陡降）时多取噪声 token，
在"复杂查询"（得分平坦长尾）时截断过狠丢失召回。

方案（训练无关、可解释）：
  对通道候选按得分降序，从最高分往下：
  - 当前得分 < 最高分 × ratio_threshold 且已保留 ≥ min_k → 截断
  - 保底 min_k（保证召回下限），上限 max_k（控制成本）
  简单查询提前截断（省 token/噪声），复杂查询保留更多（保召回）。

注意：这是对"得分有区分度"的通道（vector 余弦/keyword 相关性）有效；
RRF 融合前调用，不改变融合算法本身。
"""

from __future__ import annotations

from typing import Any


def adaptive_truncate(
    documents: list[Any],
    min_k: int,
    max_k: int,
    ratio_threshold: float,
) -> list[Any]:
    """按得分分布自适应截断（documents 需含 original_score/score 属性）"""
    if not documents:
        return documents
    if max_k <= 0:
        return documents

    def _score(doc: Any) -> float:
        raw = getattr(doc, "original_score", None)
        if raw is None:
            raw = getattr(doc, "score", 0.0)
        try:
            return float(raw or 0.0)
        except (TypeError, ValueError):
            return 0.0

    scored = [(doc, _score(doc)) for doc in documents]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    if not scored or scored[0][1] <= 0:
        # 得分无区分度（全 0 或缺失）→ 保底 min_k，不误伤
        return [doc for doc, _ in scored[: min_k]]

    top_score = scored[0][1]
    kept: list[Any] = []
    for doc, s in scored:
        if len(kept) >= max_k:
            break
        if len(kept) >= min_k and s < top_score * ratio_threshold:
            break
        kept.append(doc)
    return kept
