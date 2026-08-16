"""
数据库会话管理 — SQLAlchemy 2.0 async
提供：AsyncEngine、AsyncSessionLocal、依赖注入 get_db()
"""

import re as _re
import time as _time
from collections.abc import AsyncGenerator

import structlog as _slog
from prometheus_client import Histogram as _Histogram
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# 第三轮 #6：慢查询监控（模块级，仅注册一次；init_db 可多次调用）
_DB_SLOW_QUERY_MS = max(100, settings.mysql.slow_query_ms)
_DB_QUERY_DURATION = _Histogram(
    "db_query_duration_seconds",
    "DB query duration in seconds",
    ["table"],
)
_slow_query_installed = False

# ── 引擎（全局单例）──────────────────────────────────────────────────────────
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""

    pass


async def init_db() -> None:
    """在 lifespan 启动时调用，初始化连接池"""
    global _engine, _session_factory
    _engine = create_async_engine(
        settings.mysql.url,
        pool_size=settings.mysql.pool_size,
        max_overflow=settings.mysql.max_overflow,
        pool_pre_ping=False,  # aiomysql 的 ping() 签名不兼容 SQLAlchemy 的 do_ping
        pool_recycle=3600,  # 1 小时回收连接，替代 pre_ping
        echo=settings.app.debug,
    )

    # 强制连接 collation 为 utf8mb4_unicode_ci 以匹配表 collation
    @event.listens_for(_engine.sync_engine, "connect")
    def _set_collation(dbapi_con, connection_record):
        cursor = dbapi_con.cursor()
        cursor.execute("SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci")
        cursor.close()

    # 第三轮 #6：慢查询监控——超过阈值记录告警日志 + Prometheus 直方图
    global _slow_query_installed
    if not _slow_query_installed:
        _slow_query_installed = True

        @event.listens_for(_engine.sync_engine, "before_cursor_execute")
        def _before_cursor(conn, cursor, statement, parameters, context, executemany):
            conn.info.setdefault("_query_start", []).append(_time.monotonic())

        @event.listens_for(_engine.sync_engine, "after_cursor_execute")
        def _after_cursor(conn, cursor, statement, parameters, context, executemany):
            start_times = conn.info.get("_query_start")
            if not start_times:
                return
            start = start_times.pop()
            elapsed_ms = (_time.monotonic() - start) * 1000
            _DB_QUERY_DURATION.labels(table=_guess_table(statement)).observe(elapsed_ms / 1000.0)
            if elapsed_ms >= _DB_SLOW_QUERY_MS:
                _slog.get_logger(__name__).warning(
                    "slow query detected",
                    elapsed_ms=round(elapsed_ms, 1),
                    threshold_ms=_DB_SLOW_QUERY_MS,
                    statement=statement[:300],
                )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def close_db() -> None:
    """在 lifespan 关闭时调用"""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_db() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """获取 AsyncSession factory（Celery task / 评估等非 web 上下文使用）"""
    return _session_factory


def _guess_table(statement: str) -> str:
    """从 SQL 猜测主要表名（慢查询指标 label）"""
    m = _re.search(r"(?:FROM|INTO|UPDATE|JOIN)\s+([\w.`]+)", statement, _re.I)
    if m:
        return m.group(1).strip("`").split(".")[-1]
    return "unknown"


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入：获取 AsyncSession，用完自动关闭"""
    if _session_factory is None:
        raise RuntimeError("Session factory not initialized.")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

