"""OpenTelemetry 初始化（OTLP HTTP 导出）

Langfuse 只支持 HTTP（protobuf/JSON），不支持 gRPC，因此 exporter 固定用
otlp-proto-http。OTel 用于基础设施级分布式追踪（DB/Redis/HTTP/Celery）。

注意：OTel 的 trace_id 由 SDK 独立生成，与应用层 Tracer/Langfuse 的 trace_id
**并不相同**，因此基础设施 span 在 Langfuse 中是**独立 trace**，不是 exchange
trace 的子 span。两条链路通过 span 属性关联（``app.trace_id`` /
``app.conversation_id`` / ``app.exchange_id``，由 ``tag_current_otel_span`` 注入），
而非 trace_id 相同。
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from app.config import get_settings

logger = logging.getLogger(__name__)

_provider: TracerProvider | None = None


def tag_current_otel_span(
    *,
    trace_id: str,
    conversation_id: str | None = None,
    exchange_id: int | None = None,
) -> None:
    """给当前 OTel span 打上应用层标识，供 Langfuse 里关联基础设施 trace。

    未启用 OTel（无 provider / 非 recording span）时静默 no-op。
    """
    try:
        span = trace.get_current_span()
        if span is None or not span.is_recording():
            return
        span.set_attribute("app.trace_id", trace_id)
        if conversation_id:
            span.set_attribute("app.conversation_id", conversation_id)
        if exchange_id is not None:
            span.set_attribute("app.exchange_id", exchange_id)
    except Exception:
        logger.debug("tag_current_otel_span failed", exc_info=True)


def build_otlp_headers(
    raw: str,
    langfuse_enabled: bool,
    public_key: str,
    secret_key: str,
) -> dict[str, str]:
    """构造 OTLP HTTP 头。

    - 显式 `OTEL_EXPORTER_OTLP_HEADERS`（raw，逗号分隔 k=v）优先；
    - 否则在 Langfuse 启用时派生 Basic auth + v4 ingestion 版本头
      （x-langfuse-ingestion-version=4，否则 v4 数据模型下 ingestion 延迟可达 10 分钟）。
    """
    if raw.strip():
        headers: dict[str, str] = {}
        for part in raw.split(","):
            part = part.strip()
            if "=" in part:
                key, value = part.split("=", 1)
                headers[key.strip()] = value.strip()
        return headers
    if langfuse_enabled and public_key and secret_key:
        token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        return {
            "Authorization": f"Basic {token}",
            "x-langfuse-ingestion-version": "4",
        }
    return {}


def init_otel(app: Any = None) -> TracerProvider | None:
    global _provider
    settings = get_settings().otel
    if not settings.enabled:
        return None
    if _provider is not None:
        return _provider
    resource = Resource.create({"service.name": settings.service_name})
    langfuse = get_settings().langfuse
    headers = build_otlp_headers(
        settings.exporter_otlp_headers,
        langfuse.enabled,
        langfuse.public_key,
        langfuse.secret_key,
    )
    exporter = OTLPSpanExporter(
        endpoint=settings.exporter_otlp_endpoint, headers=headers or None
    )
    # 采样可配置：默认 1.0（全采）。低流量/高并发热点可按比例降采样。
    ratio = min(max(settings.sample_rate, 0.0), 1.0)
    provider = TracerProvider(
        resource=resource, sampler=ParentBased(TraceIdRatioBased(ratio))
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _provider = provider

    # 基础设施 auto-instrumentation（使用全局 tracer provider）
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    if app is not None:
        FastAPIInstrumentor().instrument_app(app)
    SQLAlchemyInstrumentor().instrument()
    RedisInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()

    logger.info("otel initialized: %s", settings.exporter_otlp_endpoint)
    return provider


def shutdown_otel() -> None:
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None
