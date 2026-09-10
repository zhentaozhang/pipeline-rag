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


def test_get_trace_url_disabled_returns_none(monkeypatch):
    class FakeSettings:
        langfuse = type("S", (), {"enabled": False})()

    monkeypatch.setattr(langfuse_client, "get_settings", lambda: FakeSettings())
    langfuse_client._client = None
    assert langfuse_client.get_trace_url("t1") is None


def test_get_trace_url_delegates_to_client(monkeypatch):
    class FakeClient:
        def get_trace_url(self, *, trace_id=None):
            return f"http://langfuse/trace/{trace_id}"

    monkeypatch.setattr(langfuse_client, "get_langfuse", lambda: FakeClient())
    assert langfuse_client.get_trace_url("t1") == "http://langfuse/trace/t1"


def test_record_standalone_generation_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(langfuse_client, "get_langfuse", lambda: None)
    # 未启用时不抛异常
    langfuse_client.record_standalone_generation("x", model="m")


def test_record_standalone_generation_creates_trace_and_generation(monkeypatch):
    class FakeGen:
        def __init__(self):
            self.calls: list[tuple[str, dict]] = []

        def update(self, **kwargs):
            self.calls.append(("update", kwargs))

        def end(self, **kwargs):
            self.calls.append(("end", kwargs))

    class FakeClient:
        def __init__(self):
            self.calls: list[tuple[str, dict]] = []
            self.gen = FakeGen()

        def create_trace_id(self, *, seed=None):
            return "tid-1"

        def start_observation(self, **kwargs):
            self.calls.append(("start_observation", kwargs))
            return self.gen

    client = FakeClient()
    monkeypatch.setattr(langfuse_client, "get_langfuse", lambda: client)

    langfuse_client.record_standalone_generation(
        "fact_extraction_llm",
        model="deepseek-chat",
        input="q",
        output="a",
        prompt_tokens=10,
        completion_tokens=5,
        metadata={"conversation_id": "c1"},
    )

    start = client.calls[0][1]
    assert start["trace_context"] == {"trace_id": "tid-1"}
    assert start["name"] == "fact_extraction_llm"
    assert start["as_type"] == "generation"
    assert start["model"] == "deepseek-chat"
    assert start["metadata"] == {"conversation_id": "c1"}
    assert client.gen.calls[0][0] == "update"
    assert client.gen.calls[0][1]["usage_details"] == {"input": 10, "output": 5, "total": 15}
    assert client.gen.calls[1][0] == "end"
