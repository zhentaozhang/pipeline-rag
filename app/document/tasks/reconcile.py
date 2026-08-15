"""
索引对账任务（P1-2）：清理各存储中 MySQL 已不存在的文档残留。

背景：文档删除是"尽力而为"（各存储步骤失败仅 warning，不中断），
可能留下 PG 向量 / ES 索引 / Neo4j 图谱的孤儿数据。本任务周期对账：

1. 收集 MySQL 有效文档内部 id 集合
2. 逐个存储扫描实际存在的 documentId 集合
3. 差集 = 孤儿 → 清理并输出报告

接入 Celery beat（每日），与 cleanup-orphan-documents 互补：
- cleanup_orphans：MySQL 状态异常的文档 → 补偿重试
- reconcile_indexes：各存储残留 → 清理
"""

from typing import Any

import structlog

from app.celery_app import celery_app, run_async

logger = structlog.get_logger(__name__)


async def _collect_mysql_document_ids() -> set[int]:
    """MySQL 有效文档内部 id 集合"""
    from sqlalchemy import select

    from app.db.models.document import Document
    from app.document.tasks._base import _get_mysql_session

    async with _get_mysql_session() as db:
        rows = (await db.execute(select(Document.id))).scalars().all()
    return set(rows)


def _compute_orphans(stored_ids: set[int], valid_ids: set[int]) -> list[int]:
    """孤儿 = 存储中存在但 MySQL 已不存在的 id（纯逻辑，可单测）"""
    return sorted(stored_ids - valid_ids)


async def _reconcile_pg(valid_ids: set[int]) -> dict:
    """PG 向量表：pipeline_rag_document_embedding.document_id"""
    from app.infra.pg import fetch

    rows = await fetch("SELECT DISTINCT document_id FROM pipeline_rag_document_embedding")
    stored = {r["document_id"] for r in rows}
    orphans = _compute_orphans(stored, valid_ids)
    removed = 0
    for i in range(0, len(orphans), 100):
        batch = orphans[i : i + 100]
        await fetch(
            "DELETE FROM pipeline_rag_document_embedding WHERE document_id = ANY($1::bigint[])",
            batch,
        )
        removed += len(batch)
    return {"stored": len(stored), "orphans": len(orphans), "removed": removed}


async def _es_all_document_ids(index: str) -> set[int]:
    """聚合取某 ES 索引的全部 documentId"""
    from app.infra.es import get_es, get_es_breaker

    es = get_es()
    try:
        async with get_es_breaker():
            resp = await es.search(
                index=index,
                body={
                    "size": 0,
                    "aggs": {"docs": {"terms": {"field": "documentId", "size": 10000}}},
                },
            )
    except Exception as e:
        logger.warning("es terms agg failed", index=index, error=str(e))
        return set()
    buckets = resp.get("aggregations", {}).get("docs", {}).get("buckets", [])
    return {b.get("key") for b in buckets if isinstance(b.get("key"), int)}


async def _reconcile_es(index: str, valid_ids: set[int], extra_filter: dict | None = None) -> dict:
    """ES 索引：documentId 不在有效集 → delete_by_query"""
    from app.infra.es import get_es, get_es_breaker

    stored = await _es_all_document_ids(index)
    orphans = _compute_orphans(stored, valid_ids)
    removed = 0
    if orphans:
        es = get_es()
        for doc_id in orphans:
            filter_clauses: list[dict] = [{"term": {"documentId": int(doc_id)}}]
            if extra_filter:
                filter_clauses.append(extra_filter)
            try:
                async with get_es_breaker():
                    await es.delete_by_query(
                        index=index,
                        body={"query": {"bool": {"filter": filter_clauses}}},
                        refresh=True,
                    )
                removed += 1
            except Exception as e:
                logger.warning("es delete orphan failed", index=index, doc_id=doc_id, error=str(e))
    return {"stored": len(stored), "orphans": len(orphans), "removed": removed}


async def _reconcile_neo4j(valid_ids: set[int]) -> dict:
    """Neo4j 图谱：Document 节点 documentId 不在有效集 → 清理（仅启用时执行）"""
    from app.config import get_settings

    if not get_settings().neo4j.enabled:
        return {"stored": 0, "orphans": 0, "removed": 0, "skipped": True}
    try:
        from typing import Any

        from app.infra.neo4j import get_neo4j

        driver: Any = get_neo4j()
        async with driver.session() as session:
            result = await session.run("MATCH (n:Document) RETURN DISTINCT n.documentId AS id")
            stored = {int(r["id"]) for r in await result.data() if r.get("id") is not None}
        orphans = _compute_orphans(stored, valid_ids)
        removed = 0
        if orphans:
            async with driver.session() as session:
                for doc_id in orphans:
                    await session.run(
                        "MATCH (n) WHERE (n:Document OR n:Section OR n:Item) "
                        "AND n.documentId = $documentId DETACH DELETE n",
                        documentId=doc_id,
                    )
                    removed += 1
        return {"stored": len(stored), "orphans": len(orphans), "removed": removed}
    except Exception as e:
        logger.warning("neo4j reconcile failed", error=str(e))
        return {"stored": 0, "orphans": 0, "removed": 0, "error": str(e)}


@celery_app.task(name="document.reconcile_indexes")
def reconcile_indexes() -> dict:
    """索引对账入口：清理各存储孤儿文档（P1-2）"""

    async def _do() -> dict[str, Any]:
        from app.infra.es import CHUNK_INDEX, NAVIGATION_INDEX
        from app.infra.route_indexer import ROUTE_INDEX

        valid_ids = await _collect_mysql_document_ids()
        report: dict[str, Any] = {
            "mysql_documents": len(valid_ids),
            "pg": await _reconcile_pg(valid_ids),
            "es_chunk": await _reconcile_es(CHUNK_INDEX, valid_ids),
            "es_navigation": await _reconcile_es(NAVIGATION_INDEX, valid_ids),
            "es_route": await _reconcile_es(
                ROUTE_INDEX, valid_ids, extra_filter={"term": {"entityType": "DOCUMENT"}}
            ),
            "neo4j": await _reconcile_neo4j(valid_ids),
        }
        total_removed = (
            report["pg"]["removed"]
            + report["es_chunk"]["removed"]
            + report["es_navigation"]["removed"]
            + report["es_route"]["removed"]
            + report["neo4j"]["removed"]
        )
        report["total_removed"] = total_removed
        logger.info("index reconcile done", report=report)
        return report

    return run_async(_do())  # type: ignore[no-any-return]
