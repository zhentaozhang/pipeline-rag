from __future__ import annotations

import decimal
from typing import Any

import structlog

from app.infra.es import get_es
from app.infra.es_services import ElasticsearchKnowledgeRouteIndexService
from app.orchestrator.models import DocumentRouteCandidate, RouteQueryContext

logger = structlog.get_logger(__name__)


class RouteESRepository:
    async def search_lexical_scores(
        self, routing_text: str, index_name: str, size: int, entity_type: str = ""
    ) -> list[dict[str, Any]]:
        if not routing_text:
            return []
        es = get_es()
        if not await es.indices.exists(index=index_name):
            return []

        bool_query: dict[str, Any] = {
            "should": [
                {"term": {"displayName": {"value": routing_text, "boost": 2.0}}},
                {"match_phrase_prefix": {"displayName": {"query": routing_text, "boost": 1.5}}},
                {"match": {"displayName": {"query": routing_text, "boost": 1.0}}},
                {"fuzzy": {"displayName": {"value": routing_text, "boost": 0.5}}},
                {"match_phrase_prefix": {"documentName": {"query": routing_text, "boost": 0.8}}},
                {"wildcard": {"displayName": {"value": f"*{routing_text}*", "boost": 0.3}}},
                {
                    "match": {
                        "routeText": {
                            "query": routing_text,
                            "boost": 0.2,
                            "minimum_should_match": "2<50%",
                        }
                    }
                },
                {"match": {"aliasesText": {"query": routing_text, "boost": 0.3}}},
                {"match": {"examplesText": {"query": routing_text, "boost": 0.3}}},
                {"match": {"descriptionText": {"query": routing_text, "boost": 0.1}}},
            ],
            "minimum_should_match": 1,
        }
        if entity_type:
            bool_query["filter"] = [{"term": {"entityType": entity_type}}]

        query = {"query": {"bool": bool_query}}
        try:
            resp = await es.search(index=index_name, body=query, size=size)
            hits = resp.get("hits", {}).get("hits", [])
            results = []
            for hit in hits:
                source = hit.get("_source", {})
                results.append(
                    {
                        "entityCode": source.get("entityCode"),
                        "documentId": source.get("documentId"),
                        "score": hit.get("_score"),
                    }
                )
            return results
        except Exception:
            logger.warning(
                "ES lexical search query failed",
                index=index_name,
                entity_type=entity_type,
                exc_info=True,
            )
            return []

    async def fallback_es_documents(
        self, ctx: RouteQueryContext, tenant_id: str = "default"
    ) -> list[DocumentRouteCandidate]:
        try:
            es_svc = ElasticsearchKnowledgeRouteIndexService()
            es_results = await es_svc.route_by_query(
                ctx.routing_text or ctx.question, tenant_id=tenant_id, top_k=5
            )
            if es_results:
                return [
                    DocumentRouteCandidate(
                        document_id=str(r.get("_source", {}).get("documentId", "")),
                        document_name=r.get("_source", {}).get("documentName", ""),
                        last_index_task_id=str(r.get("_source", {}).get("lastIndexTaskId", "")),
                        scope_code=r.get("_source", {}).get("scopeCode", ""),
                        scope_name=r.get("_source", {}).get("scopeName", ""),
                        business_category=r.get("_source", {}).get("businessCategory", ""),
                        document_tags=r.get("_source", {}).get("tags", ""),
                        score=decimal.Decimal(str(round(r.get("_score", 0), 4))),
                        reason="ES 路由命中",
                    )
                    for r in es_results
                ]
        except Exception:
            logger.warning("ES fallback document route failed", exc_info=True)
        return []
