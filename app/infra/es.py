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


def _analyzer_chain(preferred: str, search: str) -> list[tuple[str, str]]:
    """分词器降级链：配置值 → cjk 二元组 → standard。

    为什么必须经过 cjk：standard analyzer 把中文切成**单字**，关键词通道因此退化成
    "字符重叠"搜索（`match_phrase` 整句几乎不可能命中，`minimum_should_match` 被虚词
    稀释）。`cjk` 是 ES 内建 analyzer（cjk_bigram），不装 IK 插件也能拿到接近
    ik_max_word 的中文召回，是这里唯一正确的降级档位。
    """
    candidates: list[tuple[str, str]] = []
    pref = (preferred or "").strip()
    srch = (search or "").strip()
    if not pref:
        # 未配置：中文优先走 cjk，而不是把中文切单字的 standard
        candidates = [("cjk", "cjk"), ("standard", "standard")]
    elif "ik" in pref:
        candidates = [(pref, srch or pref), ("cjk", "cjk"), ("standard", "standard")]
    elif pref == "cjk":
        candidates = [("cjk", "cjk"), ("standard", "standard")]
    else:
        # 显式配置了别的 analyzer：尊重用户选择，只保留 standard 兜底
        candidates = [(pref, srch or pref), ("standard", "standard")]
    seen: set[tuple[str, str]] = set()
    chain: list[tuple[str, str]] = []
    for pair in candidates:
        if pair in seen:
            continue
        seen.add(pair)
        chain.append(pair)
    return chain


async def _analyzer_available(es: AsyncElasticsearch, analyzer: str) -> bool:
    """用 _analyze 探针确认 analyzer 真的可用（IK 插件缺失时这里会抛异常）。"""
    try:
        await es.indices.analyze(analyzer=analyzer, text="试用期")
        return True
    except Exception as e:  # noqa: BLE001 - 探测失败即降级，任何异常都等价
        logger.info("es analyzer unavailable", analyzer=analyzer, error=str(e))
        return False


async def _ensure_chunk_index() -> None:
    """创建文档分块索引（幂等），按 ik → cjk → standard 顺序择优。"""
    es = get_es()
    exists = await es.indices.exists(index=CHUNK_INDEX)

    for analyzer, search_analyzer in _analyzer_chain(
        settings.es.analyzer, settings.es.search_analyzer
    ):
        if not await _analyzer_available(es, analyzer):
            continue
        mapping = _build_chunk_mapping(analyzer, search_analyzer)
        if exists:
            # 允许追加新字段，如 tenantId
            try:
                await es.indices.put_mapping(index=CHUNK_INDEX, body=mapping["mappings"])
            except Exception as e:
                logger.warning(
                    "elasticsearch chunk index mapping update failed",
                    index=CHUNK_INDEX,
                    error=str(e),
                    exc_info=True,
                )
            await _warn_if_index_analyzer_mismatch(es, analyzer)
            return
        await es.indices.create(index=CHUNK_INDEX, body=mapping)
        logger.info("elasticsearch chunk index created", index=CHUNK_INDEX, analyzer=analyzer)
        return

    logger.error("no usable analyzer for chunk index", index=CHUNK_INDEX)


async def _warn_if_index_analyzer_mismatch(
    es: AsyncElasticsearch, desired: str, *, index: str = CHUNK_INDEX
) -> None:
    """索引 analyzer 无法在线修改；不一致时必须喊出来，否则关键词通道静默劣化。"""
    try:
        current = await es.indices.get_mapping(index=index)
        props = current[index]["mappings"]["properties"]
        actual = (props.get("chunkText") or {}).get("analyzer")
    except Exception:  # noqa: BLE001 - 只为告警，任何异常都不影响主流程
        return
    if actual and actual != desired:
        logger.warning(
            "es index analyzer mismatch (index is immutable; reindex to apply)",
            index=index,
            actual=actual,
            desired=desired,
        )


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
    """创建文档章节导航索引（幂等），按 ik → cjk → standard 顺序择优。"""
    es = get_es()
    exists = await es.indices.exists(index=NAVIGATION_INDEX)

    for analyzer, search_analyzer in _analyzer_chain(
        settings.es.analyzer, settings.es.search_analyzer
    ):
        if not await _analyzer_available(es, analyzer):
            continue
        mapping = _build_navigation_mapping(analyzer, search_analyzer)
        if exists:
            try:
                await es.indices.put_mapping(index=NAVIGATION_INDEX, body=mapping["mappings"])
            except Exception as e:
                logger.warning(
                    "elasticsearch navigation index mapping update failed",
                    index=NAVIGATION_INDEX,
                    error=str(e),
                    exc_info=True,
                )
            await _warn_if_index_analyzer_mismatch(es, analyzer, index=NAVIGATION_INDEX)
            return
        await es.indices.create(index=NAVIGATION_INDEX, body=mapping)
        logger.info(
            "elasticsearch navigation index created",
            index=NAVIGATION_INDEX,
            analyzer=analyzer,
        )
        return

    logger.error("no usable analyzer for navigation index", index=NAVIGATION_INDEX)


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
