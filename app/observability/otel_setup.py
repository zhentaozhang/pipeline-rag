"""OpenTelemetry 初始化（OTLP HTTP 导出）

Langfuse 只支持 HTTP（protobuf/JSON），不支持 gRPC，因此 exporter 固定用
otlp-proto-http。OTel 用于基础设施级分布式追踪（DB/Redis/HTTP/Celery），
与应用层 Langfuse SDK trace 通过 trace_id 关联。
"""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import get_settings

logger = logging.getLogger(__name__)

_provider: TracerProvider | None = None


def init_otel() -> TracerProvider | None:
    global _provider
    settings = get_settings().otel
    if not settings.enabled:
        return None
    if _provider is not None:
        return _provider
    resource = Resource.create({"service.name": settings.service_name})
    exporter = OTLPSpanExporter(endpoint=settings.exporter_otlp_endpoint)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _provider = provider
    logger.info("otel initialized", endpoint=settings.exporter_otlp_endpoint)
    return provider


def shutdown_otel() -> None:
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None
