"""
健康检查服务层

提供缓存化、可聚合的健康探测，支持：
- 6 个基础设施服务（MySQL / PG / Redis / ES / MinIO / Neo4j）
- LLM Provider（Chat + Embedding）
- 熔断器状态
- TTL 缓存（默认 15s）
- 启动完成标记
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ── 启动完成标记 ─────────────────────────────────────────────────────────
_startup_complete: bool = False


def mark_startup_complete() -> None:
    global _startup_complete
    _startup_complete = True
    logger.info("health.startup_complete")


def is_startup_complete() -> bool:
    return _startup_complete


# ── 缓存层 ──────────────────────────────────────────────────────────────

_health_cache: dict[str, Any] | None = None
_health_cache_time: float = 0.0
_HEALTH_CACHE_TTL: float = 15.0


def _is_cache_valid() -> bool:
    return _health_cache is not None and (time.monotonic() - _health_cache_time) < _HEALTH_CACHE_TTL


async def _probe_mysql() -> dict[str, Any]:
    from sqlalchemy import text

    from app.db.session import _session_factory

    if _session_factory is None:
        return {"status": "not_initialized"}
    try:
        async with _session_factory() as s:
            await s.execute(text("SELECT 1"))
        return {"status": "up"}
    except Exception as e:
        return {"status": "down", "error": str(e)}


async def _probe_postgresql() -> dict[str, Any]:
    from app.infra.pg import _pool

    if _pool is None:
        return {"status": "not_initialized"}
    try:
        conn = await _pool.acquire()
        await conn.fetchval("SELECT 1")
        await _pool.release(conn)
        return {"status": "up"}
    except Exception as e:
        return {"status": "down", "error": str(e)}


async def _probe_redis() -> dict[str, Any]:
    from app.infra.redis_lease import _redis

    if _redis is None:
        return {"status": "not_initialized"}
    try:
        await _redis.ping()
        return {"status": "up"}
    except Exception as e:
        return {"status": "down", "error": str(e)}


async def _probe_elasticsearch() -> dict[str, Any]:
    from app.infra.es import _es

    if _es is None:
        return {"status": "not_initialized"}
    try:
        await _es.ping()
        return {"status": "up"}
    except Exception as e:
        return {"status": "down", "error": str(e)}


async def _probe_minio() -> dict[str, Any]:
    from app.infra.minio import _client

    if _client is None:
        return {"status": "not_initialized"}
    try:
        await asyncio.to_thread(_client.list_buckets)
        return {"status": "up"}
    except Exception as e:
        return {"status": "down", "error": str(e)}


async def _probe_neo4j() -> dict[str, Any]:
    from app.infra.neo4j import get_neo4j

    driver = get_neo4j()
    if driver is None:
        return {"status": "disabled"}
    try:
        async with driver.session() as session:
            result = await session.run("RETURN 1 AS ok")
            await result.consume()
        return {"status": "up"}
    except Exception as e:
        return {"status": "down", "error": str(e)}


async def _probe_llm() -> dict[str, Any]:
    from app.common.llm_client import get_chat_client
    from app.config import get_settings

    settings = get_settings()
    if not settings.llm.base_url or not settings.llm.api_key:
        return {"status": "not_configured"}
    client = get_chat_client()
    if client is None:
        return {"status": "not_initialized"}
    try:
        await client.models.list()
        return {"status": "up"}
    except Exception as e:
        return {"status": "down", "error": str(e)}


async def _probe_embedding() -> dict[str, Any]:
    from app.common.llm_client import get_embedding_client
    from app.config import get_settings

    settings = get_settings()
    if not settings.llm.embedding_base_url and not settings.llm.base_url:
        return {"status": "not_configured"}
    client = get_embedding_client()
    if client is None:
        return {"status": "not_initialized"}
    try:
        await client.models.list()
        return {"status": "up"}
    except Exception as e:
        return {"status": "down", "error": str(e)}


def _collect_circuit_breakers() -> list[dict[str, Any]]:
    from app.infra.circuit_breaker import CircuitBreakerRegistry
    from app.safety.enums import CircuitState

    return [
        {
            "name": name,
            "state": state.value,
            "available": state != CircuitState.OPEN,
        }
        for name, state in CircuitBreakerRegistry.all_states().items()
    ]


async def check_all() -> dict[str, Any]:
    global _health_cache, _health_cache_time

    if _is_cache_valid():
        return _health_cache  # type: ignore[return-value]

    probe_defs: list[tuple[str, Any]] = [
        ("mysql", _probe_mysql()),
        ("postgresql", _probe_postgresql()),
        ("redis", _probe_redis()),
        ("elasticsearch", _probe_elasticsearch()),
        ("minio", _probe_minio()),
        ("neo4j", _probe_neo4j()),
        ("llm", _probe_llm()),
        ("embedding", _probe_embedding()),
    ]

    async def _run_one(name: str, coro: Any) -> tuple[str, dict[str, Any]]:
        try:
            return name, await coro
        except Exception as e:
            return name, {"status": "error", "error": str(e)}

    raw = await asyncio.gather(*[_run_one(n, c) for n, c in probe_defs])
    results: dict[str, Any] = dict(raw)

    degraded = any(
        v.get("status") in ("down", "error", "not_initialized") for v in results.values()
    )

    payload: dict[str, Any] = {
        "status": "degraded" if degraded else "ok",
        "startup_complete": _startup_complete,
        "checks": results,
        "circuit_breakers": _collect_circuit_breakers(),
    }

    _health_cache = payload
    _health_cache_time = time.monotonic()
    return payload


def invalidate_cache() -> None:
    global _health_cache, _health_cache_time
    _health_cache = None
    _health_cache_time = 0.0
