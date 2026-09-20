"""trace id 生成与 OTel trace 上下文中间件测试"""

from types import SimpleNamespace

import app.observability.otel_setup as otel_setup
from app.observability.tracer import new_trace_id


def test_new_trace_id_is_32_lower_hex():
    tid = new_trace_id()
    assert len(tid) == 32
    assert tid == tid.lower()
    int(tid, 16)  # 合法 hex


async def test_middleware_sets_app_trace_id(monkeypatch):
    monkeypatch.setattr(otel_setup, "current_otel_trace_id", lambda: "a" * 32)
    req = SimpleNamespace(state=SimpleNamespace())

    async def call_next(_r):
        return "resp"

    out = await otel_setup.otel_trace_context_middleware(req, call_next)
    assert out == "resp"
    assert req.state.app_trace_id == "a" * 32


async def test_middleware_sets_none_without_span(monkeypatch):
    monkeypatch.setattr(otel_setup, "current_otel_trace_id", lambda: None)
    req = SimpleNamespace(state=SimpleNamespace())

    async def call_next(_r):
        return None

    await otel_setup.otel_trace_context_middleware(req, call_next)
    assert req.state.app_trace_id is None
