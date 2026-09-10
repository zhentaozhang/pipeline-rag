"""langfuse_client 单例与 shutdown 行为测试"""

from app.observability import langfuse_client


def test_get_langfuse_disabled_returns_none(monkeypatch):
    class FakeLangfuseSettings:
        enabled = False

    class FakeSettings:
        langfuse = FakeLangfuseSettings()

    monkeypatch.setattr(langfuse_client, "get_settings", lambda: FakeSettings())
    langfuse_client._client = None
    assert langfuse_client.get_langfuse() is None


def test_get_langfuse_enabled_builds_singleton_and_shutdown_flushes(monkeypatch):
    calls: dict = {}

    class FakeLangfuse:
        def __init__(self, **kwargs):
            calls["kwargs"] = kwargs

        def flush(self):
            calls["flushed"] = True

    class FakeLangfuseSettings:
        enabled = True
        public_key = "pk-test"
        secret_key = "sk-test"
        host = "http://localhost:3000"
        sample_rate = 0.5
        flush_at = 10
        flush_interval = 1.0
        release = "test"

    class FakeSettings:
        langfuse = FakeLangfuseSettings()

    monkeypatch.setattr(langfuse_client, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(langfuse_client, "Langfuse", FakeLangfuse)
    langfuse_client._client = None

    c1 = langfuse_client.get_langfuse()
    c2 = langfuse_client.get_langfuse()
    assert c1 is c2  # 进程内单例

    kwargs = calls["kwargs"]
    assert kwargs["public_key"] == "pk-test"
    assert kwargs["secret_key"] == "sk-test"
    assert kwargs["host"] == "http://localhost:3000"
    assert kwargs["sample_rate"] == 0.5
    assert kwargs["flush_at"] == 10
    assert kwargs["flush_interval"] == 1.0
    assert kwargs["release"] == "test"

    langfuse_client.shutdown_langfuse()
    assert calls["flushed"] is True
    assert langfuse_client._client is None
