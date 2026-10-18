"""跨集群/同集群索引迁移：快照 _source → 按新 mapping 重建 → bulk 回灌 → 校验条数。

为什么需要它：ES 的 analyzer 不可原地修改，装 IK 必须重建索引；而语料重建来源必须是
**原索引的 _source**（PG 只有 273 条 embedding，索引里是 305 条 chunk，从 PG 重建会丢 32 条，
基线就不可比了）。

注意：用**同步** Elasticsearch 客户端（项目里没装 aiohttp，AsyncElasticsearch 不可用）。

用法：
  .venv/bin/python -m scripts.evaluation.migrate_es_index \
    --source-url http://localhost:9200 --target-url http://localhost:9201 \
    --index pipeline_rag_document_chunk --analyzer ik_max_word --search-analyzer ik_smart
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import structlog
from elasticsearch import Elasticsearch

from app.infra.es import _build_chunk_mapping

logger = structlog.get_logger(__name__)


def apply_derived_fields(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """迁移时回填派生 keyword 字段（复用索引侧同一套解析，避免两边分叉）。"""
    from app.document.indexer import enrich_chunk_document

    return [enrich_chunk_document(doc) for doc in docs]


def build_target_mapping(analyzer: str, search_analyzer: str) -> dict[str, Any]:
    return _build_chunk_mapping(analyzer, search_analyzer)


def verify_migration(*, source_count: int, target_count: int) -> dict[str, Any]:
    if source_count != target_count:
        raise ValueError(f"迁移条数不一致：source={source_count} target={target_count}")
    return {"source": source_count, "target": target_count, "matched": True}


def _read_all(es: Elasticsearch, index: str, limit: int = 10000) -> list[dict[str, Any]]:
    """读出全量文档。语料仅数百条，单请求 size=limit 足够；
    不用 search_after + sort=["_doc"]（_doc 排序不保证可续、且易把 id 与正文错配）。"""
    resp = es.search(index=index, body={"query": {"match_all": {}}, "size": limit})
    hits = resp["hits"]["hits"]
    if len(hits) >= limit:
        msg = f"index {index} has >= {limit} docs; raise limit or use scroll"
        raise RuntimeError(msg)
    return [hit["_source"] | {"_id": hit["_id"]} for hit in hits]


def copy_index(
    *,
    source_url: str,
    target_url: str,
    index: str,
    analyzer: str,
    search_analyzer: str,
    dry_run: bool = False,
    derived_fields: bool = False,
) -> dict[str, Any]:
    source = Elasticsearch(source_url)
    target = Elasticsearch(target_url)
    try:
        docs = _read_all(source, index)
        source_count = len(docs)
        if derived_fields:
            ids = [doc.pop("_id") for doc in docs]
            docs = [
                doc | {"_id": cid} for doc, cid in zip(apply_derived_fields(docs), ids, strict=True)
            ]
        if dry_run:
            return {
                "source": source_count,
                "target": None,
                "matched": None,
                "analyzer": analyzer,
                "dry_run": True,
            }
        if target.indices.exists(index=index):
            target.indices.delete(index=index)
        target.indices.create(index=index, body=build_target_mapping(analyzer, search_analyzer))
        operations: list[dict[str, Any]] = []
        for doc in docs:  # 逐条配对写出，绝不用集合重排（会把 id 与正文错配）
            chunk_id = doc.pop("_id")
            operations.append({"index": {"_index": index, "_id": chunk_id}})
            operations.append(doc)
        for start in range(0, len(operations), 1000):
            target.bulk(operations=operations[start : start + 1000], refresh=False)
        target.indices.refresh(index=index)
        target_count = target.count(index=index)["count"]
        summary = verify_migration(source_count=source_count, target_count=target_count)
        summary |= {"analyzer": analyzer}
        return summary
    finally:
        source.close()
        target.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", default="http://localhost:9200")
    parser.add_argument("--target-url", default="http://localhost:9201")
    parser.add_argument("--index", default="pipeline_rag_document_chunk")
    parser.add_argument("--analyzer", default="ik_max_word")
    parser.add_argument("--search-analyzer", default="ik_smart")
    parser.add_argument("--derived-fields", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    summary = copy_index(
        source_url=args.source_url,
        target_url=args.target_url,
        index=args.index,
        analyzer=args.analyzer,
        search_analyzer=args.search_analyzer,
        dry_run=args.dry_run,
        derived_fields=args.derived_fields,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
