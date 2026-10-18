"""把评测集的 gold 文本片段对齐成 chunk_id，产出可复用的 gold 文件。

用法：
    # 词法对齐（免费、确定性）
    env -u NO_PROXY -u no_proxy .venv/bin/python -m scripts.evaluation.ground_gold \
        --method lexical --out reports/gold_lexical.json

    # LLM 抽取式对齐（人工 gold 是复述时必需；可复现、带一致率）
    env -u NO_PROXY -u no_proxy .venv/bin/python -m scripts.evaluation.ground_gold \
        --method llm --out reports/gold_llm.json --concurrency 4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="gold 片段 -> chunk_id 对齐")
    parser.add_argument("--method", choices=["lexical", "llm"], default="lexical")
    parser.add_argument("--out", required=True, help="输出 gold 文件路径（JSON）")
    parser.add_argument("--seed-dataset", action="store_true", help="使用历史 FastMCP 数据集")
    parser.add_argument(
        "--min-ratio", type=float, default=0.92, help="词法对齐的 bigram 覆盖率阈值"
    )
    parser.add_argument("--top-k", type=int, default=25, help="LLM 对齐时每题的候选片段数")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--model", default=None, help="覆盖默认标注模型")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from app.db.session import close_db, init_db
    from scripts.evaluation.datasets import load_dataset
    from scripts.evaluation.runner import _load_indexed_chunks

    await init_db()
    started = time.perf_counter()
    try:
        chunks = await _load_indexed_chunks()
        if not chunks:
            logger.error("no indexed chunks found; run ingestion first")
            return 2
        dataset = load_dataset(seed=args.seed_dataset)

        if args.method == "lexical":
            from scripts.evaluation.gold_grounding import ground_gold_chunks

            results: dict[str, Any] = ground_gold_chunks(dataset, chunks, min_ratio=args.min_ratio)
        else:
            from scripts.evaluation.gold_grounding_llm import ground_dataset_with_llm

            results = await ground_dataset_with_llm(
                dataset,
                chunks,
                model=args.model,
                concurrency=args.concurrency,
                top_k=args.top_k,
                min_ratio=args.min_ratio,
            )
    finally:
        await close_db()

    grounded = [v for v in results.values() if v.get("relevant_chunk_ids")]
    payload = {
        "meta": {
            "method": args.method,
            "dataset_size": len(results),
            "chunks": len(chunks),
            "min_ratio": args.min_ratio,
            "grounded_questions": len(grounded),
            "ungrounded_questions": len(results) - len(grounded),
            "elapsed_s": round(time.perf_counter() - started, 1),
        },
        "questions": results,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "gold file written",
        path=str(out_path),
        grounded=len(grounded),
        total=len(results),
        elapsed_s=payload["meta"]["elapsed_s"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
