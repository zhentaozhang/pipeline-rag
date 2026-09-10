"""otel_setup 初始化/关闭行为测试"""

from app.observability import otel_setup


def test_init_otel_disabled_returns_none(monkeypatch):
    class FakeOtelSettings:
        enabled = False

    class FakeSettings:
        otel = FakeOtelSettings()

    monkeypatch.setattr(otel_setup, "get_settings", lambda: FakeSettings())
    otel_setup._provider = None
    assert otel_setup.init_otel() is None


def test_shutdown_otel_noop_when_not_initialized(monkeypatch):
    class FakeOtelSettings:
        enabled = False

    class FakeSettings:
        otel = FakeOtelSettings()

    monkeypatch.setattr(otel_setup, "get_settings", lambda: FakeSettings())
    otel_setup._provider = None
    otel_setup.shutdown_otel()  # 未初始化时调用不抛异常
