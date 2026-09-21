"""LangfuseSettings / OtelSettings 配置测试"""

from app.config.langfuse import LangfuseSettings
from app.config.otel import OtelSettings


class TestLangfuseSettings:
    def test_defaults_disabled(self):
        s = LangfuseSettings(_env_file=None)
        assert s.enabled is False
        assert s.public_key == ""
        assert s.secret_key == ""
        assert s.host == ""
        assert s.public_url == ""
        assert s.sample_rate == 1.0
        assert s.flush_at == 15
        assert s.flush_interval == 0.5
        assert s.release is None

    def test_env_prefix_override(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_ENABLED", "true")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
        monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")
        monkeypatch.setenv("LANGFUSE_SAMPLE_RATE", "0.5")
        s = LangfuseSettings(_env_file=None)
        assert s.enabled is True
        assert s.public_key == "pk-test"
        assert s.secret_key == "sk-test"
        assert s.host == "http://localhost:3000"
        assert s.sample_rate == 0.5


class TestOtelSettings:
    def test_defaults_disabled(self):
        s = OtelSettings(_env_file=None)
        assert s.enabled is False
        assert s.exporter_otlp_endpoint == "http://localhost:4318/v1/traces"
        assert s.service_name == "pipeline-rag"

    def test_env_prefix_override(self, monkeypatch):
        monkeypatch.setenv("OTEL_ENABLED", "true")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel:4318/v1/traces")
        monkeypatch.setenv("OTEL_SERVICE_NAME", "pipeline-rag-worker")
        s = OtelSettings(_env_file=None)
        assert s.enabled is True
        assert s.exporter_otlp_endpoint == "http://otel:4318/v1/traces"
        assert s.service_name == "pipeline-rag-worker"
