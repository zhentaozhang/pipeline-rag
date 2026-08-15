"""
OpenTelemetry 全链路追踪初始化

⚠️ DEPRECATED（体检 C1 决策）：生产可观测性以自研体系为准
（app/observability/ 下的 MySQL Trace + LLM-as-Judge），OTEL 默认关闭
（OTEL_ENABLED=false）。本模块与 opentelemetry 依赖保留为预留，不再迭代；
如需接入 OTLP Collector 再重新启用。

通过 OTLP gRPC 导出 Trace 到 OpenTelemetry Collector。
支持自动 instrument FastAPI / httpx / Redis / SQLAlchemy / aiohttp。
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


def _try_instrument(instrumentor_name: str, instrumentor: object) -> None:
    """尝试 instrument 组件，失败时仅记录警告不影响启动"""
    try:
        if hasattr(instrumentor, "instrument"):
            instrumentor.instrument()  # type: ignore[union-attr]
            logger.info("otel: instrumented", component=instrumentor_name)
        else:
            logger.warning("otel: no instrument() method", component=instrumentor_name)
    except Exception as e:
        logger.warning("otel: failed to instrument", component=instrumentor_name, error=str(e))


def init_tracing() -> None:
    """初始化 OTel SDK，在 lifespan 中调用"""
    from app.config import get_settings

    settings = get_settings()

    if not settings.otel.enabled:
        logger.info("opentelemetry disabled, skipping instrumentation")
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource(attributes={SERVICE_NAME: settings.otel.service_name})
    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(endpoint=settings.otel.exporter_otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)

    # ── FastAPI ──
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        _try_instrument("fastapi", FastAPIInstrumentor())
    except ImportError:
        logger.warning("otel: fastapi instrumentor not available")

    # ── httpx ──
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        _try_instrument("httpx", HTTPXClientInstrumentor())
    except ImportError:
        logger.info("otel: httpx instrumentor not available, skipping")

    # ── Redis ──
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        _try_instrument("redis", RedisInstrumentor())
    except ImportError:
        logger.info("otel: redis instrumentor not available, skipping")

    # ── SQLAlchemy ──
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        _try_instrument("sqlalchemy", SQLAlchemyInstrumentor())
    except ImportError:
        logger.info("otel: sqlalchemy instrumentor not available, skipping")

    # ── aiohttp ──
    try:
        from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor

        _try_instrument("aiohttp_client", AioHttpClientInstrumentor())
    except ImportError:
        logger.info("otel: aiohttp client instrumentor not available, skipping")

    logger.info(
        "opentelemetry initialized",
        service=settings.otel.service_name,
        endpoint=settings.otel.exporter_otlp_endpoint,
    )


def get_tracer(name: str) -> object:
    """获取 OTel Tracer 实例"""
    from opentelemetry import trace

    return trace.get_tracer(name)
