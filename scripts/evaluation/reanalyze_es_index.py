"""把已存在的 ES 索引原地换成可用 analyzer（不丢数据）。

背景：ES 索引的 analyzer 无法在线修改。容器里没装 IK 插件时，
`_ensure_chunk_index` 会静默建成 standard 分词（中文切单字），关键词通道因此退化为
"字符重叠"检索。本脚本用 `_search` 全量读出 `_source` → 删索引 → 按目标 analyzer
重建 mapping → 原样写回，只改变分析行为，不改任何业务字段。

用法：
    uv run python -m scripts.evaluation.reanalyze_es_index [--analyzer cjk] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import structlog  # noqa: E402

from app.infra.es import (  # noqa: E402
    CHUNK_INDEX,
    NAVIGATION_INDEX,
    _build_chunk_mapping,
    _build_navigation_mapping,
    get_es,
    init_es,
)

logger = structlog.get_logger(__name__)

_PROBE_TEXT = "试用期的时长是如何确定的"


async def _snapshot(index: str) -> list[dict[str, Any]]:
    es = get_es()
    if not await es.indices.exists(index=index):
        return []
    res = await es.search(index=index, body={"query": {"match_all": {}}, "size": 1000})
    return [
        {"_id": hit["_id"], "_source": hit["_source"]}
        for hit in res.get("hits", {}).get("hits", [])
    ]


async def _current_analyzer(index: str) -> str | None:
    es = get_es()
    if not await es.indices.exists(index=index):
        return None
    mapping = await es.indices.get_mapping(index=index)
    props = mapping[index]["mappings"].get("properties", {})
    for field in ("chunkText", "sectionTitle", "text"):
        analyzer = (props.get(field) or {}).get("analyzer")
        if analyzer:
            return analyzer
    return None


async def _rebuild(index: str, docs: list[dict[str, Any]], analyzer: str) -> None:
    es = get_es()
    if await es.indices.exists(index=index):
        await es.indices.delete(index=index)
        logger.info("deleted index", index=index)
    is_nav = index == NAVIGATION_INDEX
    mapping = (
        _build_navigation_mapping(analyzer, analyzer)
        if is_nav
        else _build_chunk_mapping(analyzer, analyzer)
    )
    await es.indices.create(index=index, body=mapping)
    logger.info("recreated index", index=index, analyzer=analyzer, docs=len(docs))

    if not docs:
        return
    ops: list[dict[str, Any]] = []
    for doc in docs:
        ops.append({"index": {"_index": index, "_id": doc["_id"]}})
        ops.append(doc["_source"])
    await es.bulk(operations=ops, refresh=True)


async def reanalyze(analyzer: str, *, dry_run: bool = False) -> dict[str, Any]:
    await init_es()
    report: dict[str, Any] = {"analyzer": analyzer, "indices": {}}
    for index in (CHUNK_INDEX, NAVIGATION_INDEX):
        before = await _current_analyzer(index)
        docs = await _snapshot(index)
        report["indices"][index] = {"before": before, "docs": len(docs)}
        logger.info("snapshot", index=index, analyzer_before=before, docs=len(docs))
        if dry_run or before == analyzer:
            report["indices"][index]["after"] = before
            continue
        await _rebuild(index, docs, analyzer)
        after = await _current_analyzer(index)
        count = (await get_es().count(index=index))["count"]
        report["indices"][index].update({"after": after, "count": count})
        if count != len(docs):
            raise RuntimeError(f"{index}: doc count mismatch {count} != {len(docs)}")
        logger.info("reanalyzed", index=index, analyzer=after, count=count)

    tokens = await get_es().indices.analyze(analyzer=analyzer, text=_PROBE_TEXT)
    report["probe_tokens"] = [t["token"] for t in tokens.get("tokens", [])]
    logger.info("probe analysis", analyzer=analyzer, tokens=report["probe_tokens"][:12])
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="原地重建 ES 索引 analyzer（保留数据）")
    parser.add_argument("--analyzer", default="cjk", help="目标 analyzer（默认 cjk）")
    parser.add_argument("--dry-run", action="store_true", help="只报告不修改")
    args = parser.parse_args(argv)

    report = asyncio.run(reanalyze(args.analyzer, dry_run=args.dry_run))
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
