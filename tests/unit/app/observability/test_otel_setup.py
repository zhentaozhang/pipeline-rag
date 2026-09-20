"""otel_setup 初始化/关闭行为测试"""

import base64

from app.observability import otel_setup


def _fake_settings(enabled: bool, headers: str = ""):
    class FakeOtelSettings:
        pass

    FakeOtelSettings.enabled = enabled
    FakeOtelSettings.exporter_otlp_endpoint = "http://otel:4318/v1/traces"
    FakeOtelSettings.exporter_otlp_headers = headers
    FakeOtelSettings.service_name = "pipeline-rag-test"
    FakeOtelSettings.sample_rate = 1.0

    class FakeSettings:
        otel = FakeOtelSettings()

    return FakeSettings()


class _FakeLangfuse:
    enabled = False
    public_key = ""
    secret_key = ""


def _patch_settings(monkeypatch, otel_settings, langfuse_settings=None):
    class FakeSettings:
        otel = otel_settings.otel
        langfuse = langfuse_settings or _FakeLangfuse()

    monkeypatch.setattr(otel_setup, "get_settings", lambda: FakeSettings())


def test_build_otlp_headers_derives_langfuse_basic_auth():
    headers = otel_setup.build_otlp_headers("", True, "pk-lf-1", "sk-lf-2")
    expected = base64.b64encode(b"pk-lf-1:sk-lf-2").decode()
    assert headers["Authorization"] == f"Basic {expected}"
    assert headers["x-langfuse-ingestion-version"] == "4"


def test_build_otlp_headers_explicit_raw_wins():
    headers = otel_setup.build_otlp_headers("Authorization=Bearer x,Foo=bar", True, "pk", "sk")
    assert headers == {"Authorization": "Bearer x", "Foo": "bar"}


def test_build_otlp_headers_empty_without_langfuse():
    assert otel_setup.build_otlp_headers("", False, "pk", "sk") == {}


def test_init_otel_disabled_returns_none(monkeypatch):
    _patch_settings(monkeypatch, _fake_settings(False))
    otel_setup._provider = None
    assert otel_setup.init_otel() is None


def test_shutdown_otel_noop_when_not_initialized(monkeypatch):
    _patch_settings(monkeypatch, _fake_settings(False))
    otel_setup._provider = None
    otel_setup.shutdown_otel()  # 未初始化时调用不抛异常


def test_init_otel_enabled_wires_provider_and_instrumentors(monkeypatch):
    calls: dict = {}

    class FakeResource:
        @staticmethod
        def create(attrs):
            calls["resource_attrs"] = attrs
            return "RESOURCE"

    class FakeProvider:
        def __init__(self, resource=None, sampler=None):
            calls["resource"] = resource
            calls["sampler"] = sampler

        def add_span_processor(self, processor):
            calls["processor"] = processor

        def shutdown(self):
            calls["shutdown"] = True

    class FakeExporter:
        def __init__(self, endpoint=None, headers=None):
            calls["endpoint"] = endpoint
            calls["headers"] = headers

    class FakeBatchProcessor:
        def __init__(self, exporter):
            calls["exporter"] = exporter

    class FakeInstrumentor:
        _name = ""

        def instrument(self, **kwargs):
            calls.setdefault("instrumented", []).append(self._name)

        def instrument_app(self, app):
            calls.setdefault("instrumented", []).append("fastapi_app")
            calls["app"] = app

    class FakeFastAPI(FakeInstrumentor):
        _name = "fastapi"

    class FakeSQLAlchemy(FakeInstrumentor):
        _name = "sqlalchemy"

    class FakeRedis(FakeInstrumentor):
        _name = "redis"

    class FakeHTTPX(FakeInstrumentor):
        _name = "httpx"

    class FakeLangfuse:
        enabled = True
        public_key = "pk-lf-1"
        secret_key = "sk-lf-2"

    _patch_settings(monkeypatch, _fake_settings(True), FakeLangfuse)
    monkeypatch.setattr(otel_setup, "Resource", FakeResource)
    monkeypatch.setattr(otel_setup, "TracerProvider", FakeProvider)
    monkeypatch.setattr(otel_setup, "OTLPSpanExporter", FakeExporter)
    monkeypatch.setattr(otel_setup, "BatchSpanProcessor", FakeBatchProcessor)
    monkeypatch.setattr(
        otel_setup.trace, "set_tracer_provider", lambda p: calls.setdefault("global_provider", p)
    )

    import opentelemetry.instrumentation.fastapi as m_fastapi
    import opentelemetry.instrumentation.httpx as m_httpx
    import opentelemetry.instrumentation.redis as m_redis
    import opentelemetry.instrumentation.sqlalchemy as m_sqlalchemy

    monkeypatch.setattr(m_fastapi, "FastAPIInstrumentor", FakeFastAPI)
    monkeypatch.setattr(m_sqlalchemy, "SQLAlchemyInstrumentor", FakeSQLAlchemy)
    monkeypatch.setattr(m_redis, "RedisInstrumentor", FakeRedis)
    monkeypatch.setattr(m_httpx, "HTTPXClientInstrumentor", FakeHTTPX)

    otel_setup._provider = None
    provider = otel_setup.init_otel(app="APP")

    assert isinstance(provider, FakeProvider)
    assert calls["resource"] == "RESOURCE"
    assert calls["resource_attrs"] == {"service.name": "pipeline-rag-test"}
    assert calls["endpoint"] == "http://otel:4318/v1/traces"
    assert calls["headers"]["Authorization"].startswith("Basic ")
    assert calls["headers"]["x-langfuse-ingestion-version"] == "4"
    assert isinstance(calls["processor"], FakeBatchProcessor)
    assert calls["global_provider"] is provider
    assert calls["app"] == "APP"

    instrumented = calls["instrumented"]
    assert "fastapi_app" in instrumented
    assert {"sqlalchemy", "redis", "httpx"}.issubset(set(instrumented))

    # 幂等：再次调用返回同一 provider，不重复初始化
    assert otel_setup.init_otel(app="APP") is provider

    otel_setup.shutdown_otel()
    assert calls["shutdown"] is True
    assert otel_setup._provider is None
