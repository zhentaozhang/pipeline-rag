"""通道健康度直测：绕过引擎，直接量单通道返回了什么。

为什么需要它：只看端到端 R@5 无法判断"关键词通道是否在工作"——两路融合后
向量通道可能把关键词的零命中完全掩盖。这里直接数：零命中率、平均返回条数、
gold 覆盖率、MRR。keyword 通道零命中率长期 60%+ 就是这个工具测出来的。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import structlog

from scripts.evaluation.runner import _build_plan

logger = structlog.get_logger(__name__)


def build_probe_row(
    question_id: str,
    hits: list[str],
    gold: set[str] | None,
    *,
    top_k: int,
    extra_gold: set[str] | None = None,
) -> dict[str, Any]:
    """构造一行探针结果。gold 必须是 list（JSON 报告里 set 不可序列化）。"""
    merged = {str(g) for g in (gold or set())} | {str(g) for g in (extra_gold or set())}
    return {
        "question_id": question_id,
        "hits": [str(h) for h in hits][:top_k],
        "gold": sorted(merged),
    }


def summarize_probe(rows: list[dict[str, Any]], *, k: int) -> dict[str, Any]:
    """聚合探针结果（纯函数，便于单测）。"""
    if not rows:
        return {
            "questions": 0,
            "zero_hit_rate": None,
            "avg_hits": None,
            "gold_coverage_at_k": None,
            "mrr": None,
        }
    zero = 0
    total_hits = 0
    gold_rows = 0
    covered = 0
    mrr_sum = 0.0
    for row in rows:
        hits = [str(h) for h in (row.get("hits") or [])][:k]
        gold = {str(g) for g in (row.get("gold") or set())}
        if not hits:
            zero += 1
        total_hits += len(hits)
        if gold:
            gold_rows += 1
            hit_rank = next((i + 1 for i, h in enumerate(hits) if h in gold), 0)
            if hit_rank:
                covered += 1
                mrr_sum += 1.0 / hit_rank
    return {
        "questions": len(rows),
        "zero_hit_rate": round(zero / len(rows), 4),
        "avg_hits": round(total_hits / len(rows), 2),
        "gold_coverage_at_k": round(covered / gold_rows, 4) if gold_rows else None,
        "mrr": round(mrr_sum / gold_rows, 4) if gold_rows else None,
    }


async def probe(channel: str, *, top_k: int, gold: dict[str, dict]) -> list[dict[str, Any]]:
    from app.infra.es import close_es, init_es
    from app.infra.pg import close_pg, init_pg
    from app.rag.channels.keyword import KeywordRetrievalChannel
    from app.rag.channels.vector import VectorRetrievalChannel

    # Task 2 之前还没有 combined.py：先用 85 题；Task 2 完成后改成
    from scripts.evaluation.datasets.combined import ALL_QUESTIONS

    await init_pg()
    await init_es()
    impl = KeywordRetrievalChannel() if channel == "keyword" else VectorRetrievalChannel()
    rows: list[dict[str, Any]] = []
    try:
        for q in ALL_QUESTIONS:
            plan = _build_plan(q)
            hits: list[str] = []
            for sub_q in plan.sub_questions:
                evidences = await impl.retrieve(sub_q)
                hits.extend(str(ev.chunk_id) for ev in evidences[:top_k])
            rows.append(
                build_probe_row(
                    q.id,
                    hits,
                    (gold.get(q.id) or {}).get("relevant_chunk_ids") or [],
                    top_k=top_k,
                    extra_gold=q.relevant_chunk_ids or [],
                )
            )
    finally:
        await close_es()
        await close_pg()
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", choices=["keyword", "vector"], default="keyword")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--gold-file", default="")
    parser.add_argument("--out", default="reports/channel_probe.json")
    parsed = parser.parse_args(argv)

    gold: dict[str, dict] = {}
    if parsed.gold_file:
        with open(parsed.gold_file, encoding="utf-8") as fh:
            gold = json.load(fh).get("questions") or {}

    rows = asyncio.run(probe(parsed.channel, top_k=parsed.top_k, gold=gold))
    summary = summarize_probe(rows, k=parsed.top_k)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    with open(parsed.out, "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "rows": rows}, fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
