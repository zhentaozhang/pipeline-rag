"""
集成测试环境（P3-2）

依赖真实基础设施（MySQL / Postgres+pgvector / ES / Redis / MinIO），
由主 docker-compose 提供。LLM 层统一 mock。

运行方式：
    docker compose up -d            # 起基础设施（或复用已有环境）
    pytest tests/integration -v     # 服务不可达时自动 skip
"""

import socket

import pytest

# ── 服务可达性探测：不可达 → skip（避免 CI/无环境时误报）──────────────


def _probe(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def integration_env():
    """全部集成测试的会话级前置：基础设施可达性检查"""
    from app.config import get_settings

    settings = get_settings()
    required = [
        ("mysql", settings.mysql.host, settings.mysql.port),
        ("postgres", settings.postgres.host, settings.postgres.port),
        ("redis", settings.redis.host, settings.redis.port),
    ]
    unreachable = [name for name, h, p in required if not _probe(h, p)]
    if unreachable:
        pytest.skip(
            f"集成测试需要基础设施可达（缺失: {', '.join(unreachable)}）。"
            "请先 docker compose up -d"
        )
    return settings


@pytest.fixture
async def redis_client():
    """真实 Redis 客户端（独立探测：仅需 Redis 可达；每测试连接 + 清库）"""
    from app.config import get_settings

    s = get_settings()
    if not _probe(s.redis.host, s.redis.port):
        pytest.skip(f"Redis 不可达: {s.redis.host}:{s.redis.port}")

    import redis.asyncio as aioredis

    from app.infra.redis_lease import close_redis, init_redis

    await init_redis()
    client = aioredis.from_url(s.redis.url, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()
    await close_redis()


@pytest.fixture(scope="session")
def mysql_tables(integration_env):
    """测试环境专用建表：绕过历史迁移在全新 MySQL 上的不可重放问题（alembic 已 stamp）"""
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.db.session import Base

    s = get_settings()
    engine = create_engine(s.mysql.sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return True
