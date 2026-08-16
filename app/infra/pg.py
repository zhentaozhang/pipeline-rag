import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.infra.circuit_breaker import CircuitBreakerConfig, CircuitBreakerRegistry

settings = get_settings()

_pool: asyncpg.Pool | None = None
_engine = None
async_session_maker: async_sessionmaker[AsyncSession] | None = None
_pg_breaker = CircuitBreakerRegistry.get_or_register(
    "pg",
    CircuitBreakerConfig(
        name="pg",
        failure_threshold=settings.circuit_breaker.llm_failure_threshold,
        recovery_timeout=settings.circuit_breaker.llm_recovery_timeout,
        timeout=settings.circuit_breaker.default_timeout,
    ),
)


async def init_pg() -> None:
    global _pool, _engine, async_session_maker
    if _pool is not None:
        return  # 已初始化，避免泄漏旧连接池
    _pool = await asyncpg.create_pool(
        user=settings.postgres.user,
        password=settings.postgres.password,
        database=settings.postgres.db,
        host=settings.postgres.host,
        port=settings.postgres.port,
        min_size=settings.postgres.asyncpg_min_size,
        max_size=settings.postgres.asyncpg_max_size,
    )
    _engine = create_async_engine(
        settings.postgres.url,
        pool_size=settings.postgres.sqlalchemy_pool_size,
        max_overflow=settings.postgres.sqlalchemy_max_overflow,
        pool_pre_ping=True,
    )
    async_session_maker = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    # 确保 PGVector 所需的表存在
    await _ensure_pg_tables()


async def _ensure_pg_tables() -> None:
    """自动创建 PGVector 所需的表（幂等，容错）"""
    async with _pool.acquire() as conn:
        with contextlib.suppress(Exception):
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

        _embed_dim = getattr(settings.llm, "embedding_dimensions", 1536) or 1536

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS public.document_chunk (
                chunk_id VARCHAR(64) NOT NULL,
                tenant_id VARCHAR(64) DEFAULT 'default' NOT NULL,
                doc_id VARCHAR(64) NOT NULL,
                parent_chunk_id VARCHAR(64),
                chunk_index INTEGER NOT NULL DEFAULT 0,
                content TEXT NOT NULL,
                chunk_type VARCHAR(32) NOT NULL DEFAULT 'child',
                token_count INTEGER DEFAULT 0,
                section_title VARCHAR(512),
                PRIMARY KEY (chunk_id)
            )
        """)
        with contextlib.suppress(Exception):
            await conn.execute(
                "ALTER TABLE public.document_chunk ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64) DEFAULT 'default' NOT NULL"
            )
        with contextlib.suppress(Exception):
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_document_chunk_doc_id ON public.document_chunk (doc_id)"
            )
        with contextlib.suppress(Exception):
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_document_chunk_tenant_id ON public.document_chunk (tenant_id)"
            )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS public.pipeline_rag_document_embedding (
                id BIGINT NOT NULL,
                tenant_id VARCHAR(64) DEFAULT 'default' NOT NULL,
                document_id BIGINT NOT NULL,
                task_id BIGINT NOT NULL,
                plan_id BIGINT,
                parent_block_id BIGINT NOT NULL,
                chunk_no INTEGER NOT NULL,
                source_type SMALLINT DEFAULT 1,
                section_path VARCHAR(1000),
                structure_node_id BIGINT,
                structure_node_type SMALLINT,
                canonical_path VARCHAR(1000),
                item_index INTEGER,
                chunk_text TEXT NOT NULL,
                char_count INTEGER DEFAULT 0,
                token_count INTEGER DEFAULT 0,
                embedding_model VARCHAR(128),
                metadata_json JSONB DEFAULT '{}'::jsonb,
                embedding VECTOR(__EMB_DIM__) NOT NULL,
                create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                edit_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status SMALLINT DEFAULT 1,
                PRIMARY KEY (id)
            )
            """
            .replace("__EMB_DIM__", str(_embed_dim))
        )
        with contextlib.suppress(Exception):
            await conn.execute(
                "ALTER TABLE public.pipeline_rag_document_embedding ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64) DEFAULT 'default' NOT NULL"
            )

        for idx_col in (
            "tenant_id",
            "document_id",
            "task_id",
            "plan_id",
            "parent_block_id",
            "status",
        ):
            with contextlib.suppress(Exception):
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_embedding_{idx_col} ON public.pipeline_rag_document_embedding ({idx_col})"
                )

        # vectorizer.py 使用 ON CONFLICT (document_id, chunk_no) DO UPDATE 做 UPSERT，
        # PostgreSQL 要求冲突目标必须匹配唯一索引，否则执行期报 42P10（历史 Bug A1，实测确认）。
        with contextlib.suppress(Exception):
            await conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uk_embedding_document_chunk "
                "ON public.pipeline_rag_document_embedding (document_id, chunk_no)"
            )

        # 第三轮优化 #1：HNSW 向量索引——embedding <=> $1 检索此前为全表扫描，
        # 数据量增长后线性退化；HNSW（pgvector 0.5+）高维向量召回率/速度优于 IVFFlat。
        # 注意：大数据量首次建索引耗时较长（HNSW 构建慢），可在低峰期执行。
        if settings.postgres.hnsw_index_enabled:
            # 旧表 embedding 列可能为无维度 VECTOR，HNSW 要求固定维度 → 幂等 ALTER
            _emb_dim = getattr(settings.llm, "embedding_dimensions", 1536) or 1536
            with contextlib.suppress(Exception):
                await conn.execute(
                    "ALTER TABLE public.pipeline_rag_document_embedding "
                    f"ALTER COLUMN embedding TYPE VECTOR({_emb_dim})"
                )
            with contextlib.suppress(Exception):
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_embedding_hnsw "
                    "ON public.pipeline_rag_document_embedding "
                    "USING hnsw (embedding vector_cosine_ops)"
                )


async def close_pg() -> None:
    global _pool, _engine
    if _pool:
        await _pool.close()
        _pool = None
    if _engine:
        await _engine.dispose()
        _engine = None


def get_pg_pool() -> asyncpg.Pool:
    if not _pool:
        raise RuntimeError("Postgres pool not initialized")
    return _pool


@asynccontextmanager
async def _acquire() -> AsyncIterator[asyncpg.Connection]:
    """从连接池获取连接（自动释放）；池未初始化时懒初始化（验证发现：
    Celery worker 进程不会走 FastAPI lifespan，首次使用自动建池）"""
    if _pool is None:
        await init_pg()
    conn = await _pool.acquire()
    try:
        yield conn
    finally:
        await _pool.release(conn)


async def fetch(sql: str, *args: object) -> list[asyncpg.Record]:
    """带熔断保护的查询"""
    async with _pg_breaker, _acquire() as conn:
        return await conn.fetch(sql, *args)


async def execute(sql: str, *args: object) -> str:
    """带熔断保护的写入"""
    async with _pg_breaker, _acquire() as conn:
        return await conn.execute(sql, *args)


async def fetchval(sql: str, *args: object) -> object:
    """带熔断保护的标量查询"""
    async with _pg_breaker, _acquire() as conn:
        return await conn.fetchval(sql, *args)


async def executemany(sql: str, args: list[tuple]) -> None:
    """带熔断保护的批量写入"""
    async with _pg_breaker, _acquire() as conn:
        await conn.executemany(sql, args)


@asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:
    """带熔断保护的数据库事务"""
    async with _pg_breaker, _acquire() as conn, conn.transaction():
        yield conn
