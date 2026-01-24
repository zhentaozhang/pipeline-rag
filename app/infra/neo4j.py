"""Neo4j 图数据库客户端（文档结构图谱）"""

import structlog
from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

_driver: AsyncDriver | None = None


async def init_neo4j() -> None:
    """在 lifespan 启动时调用"""
    global _driver
    query_timeout = getattr(settings.neo4j, "query_timeout_seconds", 60)
    _driver = AsyncGraphDatabase.driver(
        settings.neo4j.uri,
        auth=(settings.neo4j.user, settings.neo4j.password),
        max_connection_pool_size=20,
        connection_timeout=query_timeout,
    )
    await _driver.verify_connectivity()
    logger.info(
        "neo4j driver initialized",
        uri=settings.neo4j.uri,
        database=settings.neo4j.database,
        query_timeout_seconds=query_timeout,
    )


async def close_neo4j() -> None:
    """在 lifespan 关闭时调用"""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


def get_neo4j() -> AsyncDriver:
    if _driver is None:
        raise RuntimeError("Neo4j not initialized. Call init_neo4j() first.")
    return _driver
