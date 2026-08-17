"""一次性重灌 ES chunk 索引（IK 分词生效，017 轮中文检索修复）。

背景：IK 插件安装前 ES 索引用 standard 分词创建——analyzer 无法在线修改，
必须删除重建 index + 从 PG 重灌数据。

用法：
    uv run python -m scripts.evaluation.reindex_es_ik
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import structlog  # noqa: E402

from app.db.session import init_db  # noqa: E402
from app.infra.es import CHUNK_INDEX, NAVIGATION_INDEX, get_es, init_es  # noqa: E402
from app.infra.pg import fetch  # noqa: E402

logger = structlog.get_logger(__name__)


async def reindex_chunks() -> None:
    # 1. 先建立 client 删旧索引（standard 分词）——init_es 对已存在索引不会重建 analyzer
    from elastic_transport._node._http_httpx import HttpxAsyncHttpNode
    from elasticsearch import AsyncElasticsearch

    from app.config import get_settings

    _s = get_settings()
    _client = AsyncElasticsearch(
        node_class=HttpxAsyncHttpNode,
        hosts=[_s.es.base_url],
        basic_auth=(_s.es.user, _s.es.password) if _s.es.user and _s.es.password else None,
        request_timeout=30,
    )
    for idx in (CHUNK_INDEX, NAVIGATION_INDEX):
        if await _client.indices.exists(index=idx):
            await _client.indices.delete(index=idx)
            logger.info("deleted old index", index=idx)
    await _client.close()

    # 2. 重建（IK mapping，es.py 已定义 ik_smart_analyzer）
    await init_es()
    logger.info("recreated indexes with IK analyzer", index=CHUNK_INDEX)
    es = get_es()

    # 3. 从 PG 重灌 chunk 数据
    rows = await fetch(
        """
        SELECT chunk_id, tenant_id, doc_id, chunk_index, content,
               section_title, chunk_type, token_count
        FROM document_chunk
        WHERE chunk_type = 'child'
        ORDER BY doc_id, chunk_index
        """
    )
    logger.info("pg chunks loaded", count=len(rows))

    operations: list[dict] = []
    for r in rows:
        operations.append({"index": {"_index": CHUNK_INDEX, "_id": r["chunk_id"]}})
        operations.append(
            {
                "chunkId": r["chunk_id"],
                "tenantId": r["tenant_id"] or "default",
                "documentId": int(r["doc_id"]) if str(r["doc_id"]).isdigit() else r["doc_id"],
                "chunkNo": r["chunk_index"],
                "sectionPath": r["section_title"],
                "chunkText": r["content"],
                "tokenCount": r["token_count"],
            }
        )

    if operations:
        resp = await es.bulk(operations=operations, refresh="wait_for")
        errors = [it for it in resp["items"] if "error" in it.get("index", {})]
        logger.info("bulk done", ok=len(operations) // 2 - len(errors), errors=len(errors))
        if errors:
            logger.warning("bulk errors sample", sample=errors[0])

    # 4. 验证 IK 分词命中
    res = await es.search(
        index=CHUNK_INDEX,
        body={"query": {"match": {"chunkText": "请假规定"}}, "size": 3},
    )
    hits = res["hits"]["hits"]
    logger.info("IK keyword search verification", hits=len(hits))
    for h in hits[:3]:
        print("  IK 命中:", (h["_source"].get("chunkText") or "")[:60].replace("\n", " "))


async def main() -> None:
    await init_db()
    await reindex_chunks()
    print("reindex done")


if __name__ == "__main__":
    asyncio.run(main())
