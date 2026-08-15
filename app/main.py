"""
Pipeline RAG Python — FastAPI 应用入口
负责：应用初始化、lifespan 生命周期管理、中间件挂载、路由注册
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
import structlog.stdlib
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.config import get_settings
from app.db.session import close_db, init_db
from app.infra.es import close_es, init_es
from app.infra.health import mark_startup_complete
from app.infra.middleware import request_id_middleware
from app.infra.minio import close_minio, init_minio
from app.infra.redis_lease import close_redis, init_redis
from app.infra.tracing import init_tracing

# ── 全局 structlog 配置 ──────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
        if get_settings().app.debug
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)
settings = get_settings()


async def _seed_admin_user() -> None:
    """启动时确保管理员用户存在，密码使用 bcrypt 哈希"""
    import bcrypt
    from sqlalchemy import select

    from app.db.models.auth import AdminUser
    from app.db.session import _session_factory as sf

    username = settings.jwt.admin_username
    password = settings.jwt.admin_password

    if sf is None:
        raise RuntimeError("session factory not initialized")
    async with sf() as session:
        result = await session.execute(select(AdminUser).where(AdminUser.username == username))
        if result.scalar_one_or_none() is None:
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            session.add(AdminUser(username=username, password=hashed, nickname="Admin"))
            await session.commit()
            logger.info("admin user created", username=username)
        else:
            logger.debug("admin user already exists", username=username)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    应用生命周期管理。
    启动顺序：日志 → OTel → DB → Redis → ES → Neo4j → MinIO
    关闭顺序：逆序
    """
    # ── 启动阶段 ──────────────────────────────────────────────────────────
    logger.info("pipeline-rag starting", env=settings.app.env)

    # 事件总线默认监听者（指标 + 结构化日志），先于业务启动注册
    from app.eventbus.listeners.metrics_listener import register_listeners

    register_listeners()

    # 可观测性（最先初始化，确保后续日志/Trace 可用）
    if settings.otel.enabled:
        init_tracing()

    from app.infra.pg import close_pg, init_pg

    # 数据库连接池 (MySQL + Postgres)
    await init_db()
    await init_pg()
    logger.info("database pools initialized (mysql & postgres)")

    # 确保管理员用户存在（首次启动自动创建）
    await _seed_admin_user()
    logger.info("admin user ensured")

    # Redis（分布式锁 + Celery Broker）
    await init_redis()
    logger.info("redis connected")

    # Elasticsearch
    await init_es()
    logger.info("elasticsearch connected")

    # 同步知识路由索引（一次性全量同步）
    from app.infra.route_indexer import sync_all_routes

    try:
        await sync_all_routes()
        logger.info("knowledge route index synced")
    except Exception:
        logger.warning("knowledge route index sync failed, will retry at next query", exc_info=True)

    # Neo4j
    if settings.neo4j.enabled:
        from app.infra.neo4j import init_neo4j

        await init_neo4j()
        logger.info("neo4j driver initialized")
    else:
        logger.info("neo4j disabled, skipping initialization")

    # MinIO
    init_minio()
    logger.info("minio client initialized")

    logger.info("pipeline-rag started", host=settings.app.host, port=settings.app.port)
    mark_startup_complete()

    yield  # ── 应用运行中 ────────────────────────────────────────────────

    # ── 关闭阶段 ──────────────────────────────────────────────────────────
    logger.info("pipeline-rag shutting down")
    close_minio()
    if settings.neo4j.enabled:
        from app.infra.neo4j import close_neo4j

        await close_neo4j()
    await close_es()
    await close_redis()
    await close_pg()
    await close_db()
    logger.info("pipeline-rag stopped")


def create_app() -> FastAPI:
    """工厂函数，创建并配置 FastAPI 实例"""

    app = FastAPI(
        title="Pipeline RAG",
        description="Enterprise-grade AI Agent + RAG platform built with FastAPI and LangGraph. "
        "Provides streaming conversation, RAG retrieval, document processing pipeline, "
        "ReAct agent with web search, and full observability.",
        version="0.1.0",
        docs_url="/docs" if settings.app.debug else None,
        redoc_url="/redoc" if settings.app.debug else None,
        lifespan=lifespan,
    )

    # ── 中间件 ────────────────────────────────────────────────────────────
    cors_origins = settings.app.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials="*" not in cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(request_id_middleware)

    # Redis 滑动窗口限流（/api/chat/, /admin/auth/, /manage/）
    if settings.rate_limit.enabled:
        from app.infra.rate_limiter import rate_limit_middleware

        app.middleware("http")(rate_limit_middleware)

    # 自动认证中间件：拦截 /manage/** 所有请求
    from app.api.admin_auth import auth_middleware_for_manage, preview_mode_middleware

    app.middleware("http")(auth_middleware_for_manage)
    app.middleware("http")(preview_mode_middleware)

    # 自动认证中间件：APP_API_KEY 非空时拦截 /api/chat/** 请求
    if settings.app.api_key:
        from app.api.admin_auth import chat_auth_middleware

        app.middleware("http")(chat_auth_middleware)

    # ── 路由注册 ──────────────────────────────────────────────────────────
    from app.api.health import router as health_router
    from app.api.router import api_router

    app.include_router(health_router)
    app.include_router(api_router)

    # ── 全局异常处理 ──────────────────────────────────────────────────────
    from app.api.exception_handlers import register_exception_handlers

    register_exception_handlers(app)

    return app


# 供 uvicorn / fastapi dev 使用的应用实例
app = create_app()


@app.get("/", tags=["system"])
async def root() -> JSONResponse:
    """根路径：返回服务基本信息（便于 Docker/K8s 健康探测）"""
    return JSONResponse(
        {
            "name": "pipeline-rag",
            "version": "0.1.0",
            "status": "ok",
            "docs": "/docs",
        }
    )


@app.get("/metrics", tags=["system"])
async def metrics() -> PlainTextResponse:
    """Prometheus 指标暴露端点"""
    from prometheus_client import generate_latest

    return PlainTextResponse(
        generate_latest(), media_type="text/plain; version=0.0.4; charset=utf-8"
    )
