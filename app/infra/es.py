"""Elasticsearch 客户端（关键词检索 + IK 分词）"""

import structlog
from elasticsearch import AsyncElasticsearch

from app.config import get_settings
from app.infra.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerRegistry

logger = structlog.get_logger(__name__)
settings = get_settings()

_es: AsyncElasticsearch | None = None
_es_breaker = CircuitBreakerRegistry.get_or_register(
    "es",
    CircuitBreakerConfig(
        name="es",
        failure_threshold=settings.circuit_breaker.llm_failure_threshold,
        recovery_timeout=settings.circuit_breaker.llm_recovery_timeout,
        timeout=settings.circuit_breaker.default_timeout,
    ),
)

# 文档 Embedding 分块的 ES 索引名
CHUNK_INDEX = f"{settings.es.index_prefix}_document_chunk"


async def init_es() -> None:
    """在 lifespan 启动时调用"""
    global _es
    connect_timeout = settings.es.connect_timeout_ms / 1000.0
    # 用 httpx transport（项目已有 httpx 依赖）替代默认 aiohttp transport——
    # 修复「aiohttp 未安装导致 ES 客户端启动失败」（验证发现，生产同样会挂）
    from elastic_transport._node._http_httpx import HttpxAsyncHttpNode

    _es = AsyncElasticsearch(
        node_class=HttpxAsyncHttpNode,
        hosts=[settings.es.base_url],
        basic_auth=(settings.es.user, settings.es.password)
        if settings.es.user and settings.es.password
        else None,
        request_timeout=connect_timeout,
        retry_on_timeout=True,
        max_retries=settings.es.max_retries,
    )
    # 验证连接
    info = await _es.info()
    logger.info("elasticsearch connected", version=info["version"]["number"])

    # 确保索引存在（含 IK 分词器）
    await _ensure_chunk_index()

    # 确保路由索引存在
    from app.infra.route_indexer import ensure_route_indices

    await ensure_route_indices()

    # 确保导航索引存在（幂等）
    await _ensure_navigation_index()


async def close_es() -> None:
    global _es
    if _es:
        await _es.close()
        _es = None


def get_es() -> AsyncElasticsearch:
    if _es is None:
        raise RuntimeError("Elasticsearch not initialized. Call init_es() first.")
    return _es


def get_es_breaker() -> CircuitBreaker:
    return _es_breaker


async def _ensure_chunk_index() -> None:
    """创建文档分块索引（幂等），优先使用 IK 分词器，不可用时降级为 standard"""
    es = get_es()
    analyzer = settings.es.analyzer
    search_analyzer = settings.es.search_analyzer

    try:
        mapping = _build_chunk_mapping(analyzer, search_analyzer)
        if await es.indices.exists(index=CHUNK_INDEX):
            # 允许追加新字段，如 tenantId
            await es.indices.put_mapping(index=CHUNK_INDEX, body=mapping["mappings"])
            return
        await es.indices.create(index=CHUNK_INDEX, body=mapping)
        logger.info("elasticsearch chunk index created (IK)", index=CHUNK_INDEX)
    except Exception as e:
        logger.warning(
            "IK analyzer unavailable or mapping update failed",
            index=CHUNK_INDEX,
            error=str(e),
            exc_info=True,
        )
        if not await es.indices.exists(index=CHUNK_INDEX):
            mapping = _build_chunk_mapping("standard", "standard")
            await es.indices.create(index=CHUNK_INDEX, body=mapping)
            logger.info("elasticsearch chunk index created (standard)", index=CHUNK_INDEX)


def _build_chunk_mapping(analyzer: str, search_analyzer_str: str) -> dict:
    return {
        "settings": {
            "analysis": {
                "analyzer": {
                    "ik_smart_analyzer": {"type": "custom", "tokenizer": "ik_smart"},
                    "ik_max_word_analyzer": {"type": "custom", "tokenizer": "ik_max_word"},
                }
            }
        }
        if "ik" in analyzer
        else {},
        "mappings": {
            "dynamic": False,
            "properties": {
                "chunkId": {"type": "keyword"},
                "tenantId": {"type": "keyword"},
                "documentId": {"type": "long"},
                "taskId": {"type": "long"},
                "chunkNo": {"type": "integer"},
                "documentName": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "sectionPath": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "structureNodeId": {"type": "long"},
                "structureNodeType": {"type": "integer"},
                "canonicalPath": {"type": "keyword"},
                "itemIndex": {"type": "integer"},
                "knowledgeScopeCode": {"type": "keyword"},
                "knowledgeScopeName": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "businessCategory": {"type": "keyword"},
                "documentTags": {"type": "keyword"},
                "chunkText": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
            },
        },
    }


NAVIGATION_INDEX = "pipeline_rag_navigation_index"


async def _ensure_navigation_index() -> None:
    """创建文档章节导航索引（幂等），优先 IK，不可用降级 standard"""
    es = get_es()
    analyzer = settings.es.analyzer
    search_analyzer = settings.es.search_analyzer

    try:
        mapping = _build_navigation_mapping(analyzer, search_analyzer)
        if await es.indices.exists(index=NAVIGATION_INDEX):
            await es.indices.put_mapping(index=NAVIGATION_INDEX, body=mapping["mappings"])
            return
        await es.indices.create(index=NAVIGATION_INDEX, body=mapping)
        logger.info("elasticsearch navigation index created (IK)", index=NAVIGATION_INDEX)
    except Exception as e:
        logger.warning(
            "IK analyzer unavailable or mapping update failed for navigation index",
            error=str(e),
            exc_info=True,
        )
        if not await es.indices.exists(index=NAVIGATION_INDEX):
            mapping = _build_navigation_mapping("standard", "standard")
            await es.indices.create(index=NAVIGATION_INDEX, body=mapping)
            logger.info("elasticsearch navigation index created (standard)", index=NAVIGATION_INDEX)


def _build_navigation_mapping(analyzer: str, search_analyzer_str: str) -> dict:
    return {
        "settings": {
            "analysis": {
                "analyzer": {
                    "ik_smart_analyzer": {"type": "custom", "tokenizer": "ik_smart"},
                    "ik_max_word_analyzer": {"type": "custom", "tokenizer": "ik_max_word"},
                }
            }
        }
        if "ik" in analyzer
        else {},
        "mappings": {
            "dynamic": False,
            "properties": {
                "nodeId": {"type": "long"},
                "tenantId": {"type": "keyword"},
                "documentId": {"type": "long"},
                "parseTaskId": {"type": "long"},
                "nodeType": {"type": "keyword"},
                "nodeCode": {"type": "keyword"},
                "nodeNo": {"type": "integer"},
                "depth": {"type": "integer"},
                "parentNodeId": {"type": "long"},
                "title": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "anchorText": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "sectionPath": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "canonicalPath": {"type": "keyword"},
                "contentText": {
                    "type": "text",
                    "analyzer": analyzer,
                    "search_analyzer": search_analyzer_str,
                },
                "itemIndex": {"type": "integer"},
            },
        },
    }
