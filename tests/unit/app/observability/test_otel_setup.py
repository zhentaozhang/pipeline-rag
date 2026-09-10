"""otel_setup 初始化/关闭行为测试"""

from app.observability import otel_setup


def _fake_settings(enabled: bool):
    class FakeOtelSettings:
        pass

    FakeOtelSettings.enabled = enabled
    FakeOtelSettings.exporter_otlp_endpoint = "http://otel:4318/v1/traces"
    FakeOtelSettings.service_name = "pipeline-rag-test"

    class FakeSettings:
        otel = FakeOtelSettings()

    return FakeSettings()


def test_init_otel_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(otel_setup, "get_settings", lambda: _fake_settings(False))
    otel_setup._provider = None
    assert otel_setup.init_otel() is None


def test_shutdown_otel_noop_when_not_initialized(monkeypatch):
    monkeypatch.setattr(otel_setup, "get_settings", lambda: _fake_settings(False))
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
        def __init__(self, resource=None):
            calls["resource"] = resource

        def add_span_processor(self, processor):
            calls["processor"] = processor

        def shutdown(self):
            calls["shutdown"] = True

    class FakeExporter:
        def __init__(self, endpoint=None):
            calls["endpoint"] = endpoint

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

    monkeypatch.setattr(otel_setup, "get_settings", lambda: _fake_settings(True))
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
