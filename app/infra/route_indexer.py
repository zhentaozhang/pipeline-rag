"""
知识路由 Elasticsearch 倒排索引管理
"""

import structlog
from elasticsearch.helpers import async_bulk
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import BusinessStatus
from app.common.utils import safe_int
from app.config import get_settings
from app.db.models.document import Document
from app.db.models.knowledge import KnowledgeScope, KnowledgeTopic
from app.db.session import get_engine
from app.infra.es import get_es

logger = structlog.get_logger(__name__)
settings = get_settings()

ROUTE_INDEX_PREFIX = f"{settings.es.index_prefix}_knowledge_route"
ROUTE_INDEX = f"{ROUTE_INDEX_PREFIX}"
SCOPE_ROUTE_INDEX = ROUTE_INDEX
TOPIC_ROUTE_INDEX = ROUTE_INDEX
DOCUMENT_ROUTE_INDEX = ROUTE_INDEX


async def ensure_route_indices() -> None:
    """创建知识路由倒排索引（单一索引，统一 Scope/Topic/Document 路由）"""
    es = get_es()

    mapping = {
        "settings": {
            "analysis": {
                "analyzer": {
                    "ik_smart_analyzer": {"type": "custom", "tokenizer": "ik_smart"},
                    "ik_max_word_analyzer": {"type": "custom", "tokenizer": "ik_max_word"},
                }
            }
        },
        "mappings": {
            "dynamic": False,
            "properties": {
                "routeId": {"type": "keyword"},
                "tenantId": {"type": "keyword"},
                "entityType": {"type": "keyword"},
                "entityCode": {"type": "keyword"},
                "documentId": {"type": "long"},
                "scopeCode": {"type": "keyword"},
                "scopeName": {
                    "type": "text",
                    "analyzer": "ik_max_word_analyzer",
                    "search_analyzer": "ik_smart_analyzer",
                },
                "topicCode": {"type": "keyword"},
                "topicName": {
                    "type": "text",
                    "analyzer": "ik_max_word_analyzer",
                    "search_analyzer": "ik_smart_analyzer",
                },
                "documentName": {
                    "type": "text",
                    "analyzer": "ik_max_word_analyzer",
                    "search_analyzer": "ik_smart_analyzer",
                },
                "businessCategory": {"type": "keyword"},
                "displayName": {
                    "type": "text",
                    "analyzer": "ik_max_word_analyzer",
                    "search_analyzer": "ik_smart_analyzer",
                },
                "descriptionText": {
                    "type": "text",
                    "analyzer": "ik_max_word_analyzer",
                    "search_analyzer": "ik_smart_analyzer",
                },
                "aliasesText": {
                    "type": "text",
                    "analyzer": "ik_max_word_analyzer",
                    "search_analyzer": "ik_smart_analyzer",
                },
                "examplesText": {
                    "type": "text",
                    "analyzer": "ik_max_word_analyzer",
                    "search_analyzer": "ik_smart_analyzer",
                },
                "summaryText": {
                    "type": "text",
                    "analyzer": "ik_max_word_analyzer",
                    "search_analyzer": "ik_smart_analyzer",
                },
                "routeText": {
                    "type": "text",
                    "analyzer": "ik_max_word_analyzer",
                    "search_analyzer": "ik_smart_analyzer",
                },
                "entityTerms": {"type": "keyword"},
                "tags": {"type": "keyword"},
            },
        },
    }

    for idx in [ROUTE_INDEX]:
        if not await es.indices.exists(index=idx):
            try:
                await es.indices.create(index=idx, body=mapping)
                logger.info("elasticsearch route index created (IK)", index=idx)
            except Exception:
                logger.warning(
                    "IK analyzer unavailable for route index, falling back to standard",
                    index=idx,
                    exc_info=True,
                )
                fallback = _build_route_mapping_fallback("standard", "standard")
                await es.indices.create(index=idx, body=fallback)
                logger.info("elasticsearch route index created (standard)", index=idx)


def _build_route_mapping_fallback(analyzer: str, search_analyzer_str: str) -> dict:
    """构建不带 IK analyzer 的 fallback mapping"""
    return {
        "mappings": {
            "dynamic": False,
            "properties": {
                "routeId": {"type": "keyword"},
                "tenantId": {"type": "keyword"},
                "entityType": {"type": "keyword"},
                "entityCode": {"type": "keyword"},
                "documentId": {"type": "long"},
                "scopeCode": {"type": "keyword"},
                "scopeName": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "topicCode": {"type": "keyword"},
                "topicName": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "documentName": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "businessCategory": {"type": "keyword"},
                "displayName": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "descriptionText": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "aliasesText": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "examplesText": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "summaryText": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "routeText": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "entityTerms": {"type": "keyword"},
                "tags": {"type": "keyword"},
            },
        },
    }


def _extract_entity_terms(text: str) -> list[str]:
    """
    提取实体词 (替代原 entityTerms 抽取)
    使用结巴分词进行粗略抽取，实际生产中可更换为 NLP 实体识别模型
    """
    import jieba
    import jieba.analyse

    if not text:
        return []
    # 使用 TextRank 或 TF-IDF 提取关键词
    keywords = jieba.analyse.extract_tags(text, topK=10)
    return [str(k) for k in keywords]


from datetime import datetime


async def sync_all_routes(updated_after: datetime | None = None) -> None:
    """
    全量/增量同步 MySQL 中的 Scope / Topic / Document 至 ES 路由索引
    """
    logger.info("start syncing knowledge routes to es", updated_after=updated_after)
    es = get_es()
    engine = get_engine()

    actions = []

    async with AsyncSession(engine) as session:
        # 1. Sync Scopes
        stmt_scope = select(KnowledgeScope).where(KnowledgeScope.status == BusinessStatus.YES.value)
        if updated_after:
            stmt_scope = stmt_scope.where(KnowledgeScope.updated_at >= updated_after)
        scopes = (await session.execute(stmt_scope)).scalars().all()
        for scope in scopes:
            aliases = getattr(scope, "aliases", "") or ""
            examples = getattr(scope, "examples", "") or ""
            text = f"{scope.scope_name} {scope.description or ''} {aliases} {examples}"
            terms = _extract_entity_terms(text)
            actions.append(
                {
                    "_op_type": "index",
                    "_index": ROUTE_INDEX,
                    "_id": f"scope_{scope.scope_code}",
                    "_source": {
                        "routeId": f"scope_{scope.scope_code}",
                        "tenantId": getattr(scope, "tenant_id", "default"),
                        "entityType": "SCOPE",
                        "entityCode": scope.scope_code,
                        "scopeCode": scope.scope_code,
                        "scopeName": scope.scope_name,
                        "displayName": scope.scope_name,
                        "descriptionText": scope.description or "",
                        "aliasesText": aliases,
                        "examplesText": examples,
                        "summaryText": scope.description or "",
                        "routeText": text,
                        "entityTerms": terms,
                        "tags": [],
                    },
                }
            )

        # 2. Sync Topics
        from sqlalchemy.orm import aliased

        stmt_topic = (
            select(KnowledgeTopic, KnowledgeScope.scope_code)
            .join(KnowledgeScope, KnowledgeTopic.scope_code == KnowledgeScope.scope_code)
            .where(KnowledgeTopic.status == BusinessStatus.YES.value)
        )
        if updated_after:
            stmt_topic = stmt_topic.where(KnowledgeTopic.updated_at >= updated_after)
        topics = (await session.execute(stmt_topic)).all()

        for topic, scope_code in topics:
            text = f"{topic.topic_name}"
            terms = _extract_entity_terms(text)
            actions.append(
                {
                    "_op_type": "index",
                    "_index": ROUTE_INDEX,
                    "_id": f"topic_{topic.topic_code}",
                    "_source": {
                        "routeId": f"topic_{topic.topic_code}",
                        "tenantId": getattr(topic, "tenant_id", "default"),
                        "entityType": "TOPIC",
                        "entityCode": topic.topic_code,
                        "scopeCode": scope_code,
                        "topicCode": topic.topic_code,
                        "topicName": topic.topic_name,
                        "displayName": topic.topic_name,
                        "routeText": text,
                        "entityTerms": terms,
                        "tags": [],
                    },
                }
            )

        # 3. Sync Documents (As Document Routes)
        ScopeAlias = aliased(KnowledgeScope)
        TopicAlias = aliased(KnowledgeTopic)

        stmt_doc = (
            select(Document, ScopeAlias.scope_code, ScopeAlias.scope_name, TopicAlias.topic_code)
            .outerjoin(ScopeAlias, Document.knowledge_scope_code == ScopeAlias.scope_code)
            .outerjoin(TopicAlias, TopicAlias.scope_code == ScopeAlias.scope_code)
            .where(Document.status == BusinessStatus.YES.value)
        )
        if updated_after:
            stmt_doc = stmt_doc.where(Document.updated_at >= updated_after)
        docs = (await session.execute(stmt_doc)).all()

        for doc, scope_code, scope_name, topic_code in docs:
            text = f"{doc.document_name} {doc.document_tags or ''}"
            terms = _extract_entity_terms(text)
            actions.append(
                {
                    "_op_type": "index",
                    "_index": ROUTE_INDEX,
                    "_id": f"doc_{doc.doc_id}",
                    "_source": {
                        "routeId": f"doc_{doc.doc_id}",
                        "tenantId": getattr(doc, "tenant_id", "default"),
                        "entityType": "DOCUMENT",
                        "entityCode": doc.doc_id,
                        "documentId": safe_int(doc.doc_id),
                        "scopeCode": scope_code or "",
                        "scopeName": scope_name or "",
                        "topicCode": topic_code or "",
                        "documentName": doc.document_name,
                        "businessCategory": doc.business_category or "",
                        "displayName": doc.document_name,
                        "summaryText": doc.document_tags or "",
                        "routeText": text,
                        "entityTerms": terms,
                        "tags": (doc.document_tags or "").split(",") if doc.document_tags else [],
                    },
                }
            )

    if actions:
        success, _ = await async_bulk(es, actions)
        logger.info("sync routes completed", success_count=success)
        for idx in [ROUTE_INDEX]:
            await es.indices.refresh(index=idx)
    else:
        logger.info("no routes to sync")
