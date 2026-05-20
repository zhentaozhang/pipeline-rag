from typing import Any

import structlog

from app.infra.es import NAVIGATION_INDEX, get_es, get_es_breaker

logger = structlog.get_logger(__name__)


class ElasticsearchDocumentNavigationIndexService:
    """文档导航结构索引服务"""

    async def delete_document(self, doc_id: str) -> None:
        """删除指定文档的所有章节索引"""
        es = get_es()
        try:
            async with get_es_breaker():
                await es.delete_by_query(
                    index=NAVIGATION_INDEX,
                    body={"query": {"bool": {"filter": [{"term": {"documentId": int(doc_id)}}]}}},
                )
        except Exception as e:
            logger.error(
                "elasticsearch delete navigation index failed", error=str(e), exc_info=True
            )

    async def search_sections(
        self,
        doc_id: str,
        query_texts: list[str],
        size: int = 8,
    ) -> list[dict[str, Any]]:
        """
        多字段加权章节搜索。
        搜索章节：matchPhrase(20x) + multiMatch multi-field。
        """
        if not query_texts:
            return []
        es = get_es()
        should_clauses = []
        for qt in query_texts:
            should_clauses.append({"match_phrase": {"title": {"query": qt, "boost": 20.0}}})
            should_clauses.append({"match_phrase": {"sectionPath": {"query": qt, "boost": 15.0}}})
            should_clauses.append(
                {
                    "multi_match": {
                        "query": qt,
                        "fields": ["title^10", "sectionPath^8", "anchorText^5", "contentText"],
                        "type": "best_fields",
                    }
                }
            )
        body = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"documentId": int(doc_id)}},
                        {"term": {"nodeType": "1"}},
                    ],
                    "should": should_clauses,
                    "minimum_should_match": 1,
                }
            },
            "size": min(size, 20),
        }
        try:
            async with get_es_breaker():
                res = await es.search(index=NAVIGATION_INDEX, body=body)
            hits = res.get("hits", {}).get("hits", [])
            return [{"_score": h["_score"], **h["_source"]} for h in hits]
        except Exception as e:
            logger.error("es search_sections failed", doc_id=doc_id, error=str(e), exc_info=True)
            return []


class ElasticsearchKnowledgeRouteIndexService:
    """知识路由索引服务"""

    _last_refresh_ts: float = 0.0
    _REFRESH_INTERVAL = 5.0

    async def route_by_query(
        self, query_text: str, top_k: int = 5, tenant_id: str = "default"
    ) -> list[dict[str, Any]]:
        """基于用户查询路由到对应的知识域/文档"""
        from app.infra.route_indexer import ROUTE_INDEX as _RI

        es = get_es()

        query = {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query_text,
                            "fields": [
                                "routeText^3.0",
                                "displayName^2.0",
                                "documentName^1.5",
                                "scopeName^1.5",
                                "topicName^1.5",
                                "summaryText^1.2",
                                "descriptionText",
                                "aliasesText",
                                "examplesText",
                            ],
                            "type": "best_fields",
                        }
                    }
                ],
                "filter": [{"term": {"tenantId": tenant_id}}],
            }
        }

        try:
            async with get_es_breaker():
                resp = await es.search(index=_RI, query=query, size=top_k)
            hits = resp.get("hits", {}).get("hits", [])

            results = []
            for hit in hits:
                results.append({"_source": hit["_source"], "_score": hit.get("_score", 0.0)})
            return results
        except Exception as e:
            logger.error("elasticsearch route search failed", error=str(e), exc_info=True)
            return []

    async def delete_document_route(self, doc_id: str) -> None:
        """
        删除指定文档的所有路由快照。
        删除知识路由索引：按 entityType=document + documentId 过滤。
        """
        from app.infra.route_indexer import ROUTE_INDEX as _RI

        es = get_es()
        try:
            async with get_es_breaker():
                await es.delete_by_query(
                    index=_RI,
                    body={
                        "query": {
                            "bool": {
                                "filter": [
                                    {"term": {"entityType": "DOCUMENT"}},
                                    {"term": {"documentId": int(doc_id)}},
                                ]
                            }
                        }
                    },
                    refresh=True,
                )
            logger.info("document route deleted", doc_id=doc_id)
        except Exception as e:
            logger.error("delete document route failed", doc_id=doc_id, error=str(e), exc_info=True)
