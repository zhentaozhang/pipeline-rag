"""
RRF 融合（Reciprocal Rank Fusion）

算法：score = 1/(K + rank_vector) + 1/(K + rank_keyword)，K=60
两个通道分数量纲不同，无法直接比大小，RRF 按排名倒数法融合。
"""

from app.chat.schema import Evidence


def rrf_fusion(
    vector_hits: list[Evidence],
    keyword_hits: list[Evidence],
    k: int = 60,
) -> list[Evidence]:
    """
    RRF 融合两个检索通道的结果。

    Args:
        vector_hits:   向量通道结果（已按 score DESC 排序）
        keyword_hits:  关键词通道结果（已按 score DESC 排序）
        k:             RRF 参数，默认 60

    Returns:
        融合后按 rrf_score DESC 排序的 Evidence 列表（去重）
    """
    scores: dict[str, float] = {}
    evidence_map: dict[str, Evidence] = {}
    channels_map: dict[str, set[str]] = {}

    # 向量通道贡献
    for rank, ev in enumerate(vector_hits, start=0):
        scores[ev.chunk_id] = scores.get(ev.chunk_id, 0.0) + 1.0 / (k + rank + 1)
        evidence_map[ev.chunk_id] = ev
        channels_map.setdefault(ev.chunk_id, set()).add("vector")

    # 关键词通道贡献
    for rank, ev in enumerate(keyword_hits, start=0):
        scores[ev.chunk_id] = scores.get(ev.chunk_id, 0.0) + 1.0 / (k + rank + 1)
        if ev.chunk_id not in evidence_map:
            evidence_map[ev.chunk_id] = ev
        channels_map.setdefault(ev.chunk_id, set()).add("keyword")

    # 按 RRF 分排序，将最终分数写回 Evidence
    sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)
    result: list[Evidence] = []
    for cid in sorted_ids:
        ev = evidence_map[cid].model_copy()
        rrf_val = round(scores[cid], 6)
        ev.score = rrf_val
        ev.rrf_score = rrf_val

        channels = channels_map[cid]
        if len(channels) > 1:
            ev.channel = "hybrid"
        else:
            ev.channel = list(channels)[0]

        result.append(ev)

    return result
