"""
数据库会话管理 — SQLAlchemy 2.0 async
提供：AsyncEngine、AsyncSessionLocal、依赖注入 get_db()
"""

from collections.abc import AsyncGenerator

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

