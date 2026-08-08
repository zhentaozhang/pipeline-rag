import json
import types

import pytest

import app.orchestrator.guardrails as guardrails_module
from app.orchestrator.guardrails import IntentGuardrailService
from app.safety.enums import SafetyMode


class FakeResponse:
    def __init__(self, content):
        self.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=content))]


class FakeClient:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    async def create(self, **kwargs):
        if self.error:
            raise self.error
        return FakeResponse(self.content)


class FakeInputFilter:
    def __init__(self, is_safe=True, sanitized_text="sanitized", reason=""):
        self.is_safe = is_safe
        self.sanitized_text = sanitized_text
        self.reason = reason

    async def filter(self, question):
        return self


def make_settings(mode=SafetyMode.MONITOR):
    return types.SimpleNamespace(
        llm=types.SimpleNamespace(model="m"),
        safety=types.SimpleNamespace(mode=mode),
    )


class TestEvaluate:
    @pytest.mark.asyncio
    async def test_blank_question_safe(self, monkeypatch):
        svc = IntentGuardrailService()
        assert await svc.evaluate("   ") == (True, "")

    @pytest.mark.asyncio
    async def test_l1_block(self, monkeypatch):
        monkeypatch.setattr(
            guardrails_module,
            "SafetyInputFilter",
            lambda settings: FakeInputFilter(is_safe=False, reason="注入风险"),
        )
        svc = IntentGuardrailService()
        assert await svc.evaluate("恶意输入") == (False, "注入风险")

    @pytest.mark.asyncio
    async def test_l1_pass_llm_block(self, monkeypatch):
        client = FakeClient(content=json.dumps({"action": "block", "reason": "越权"}))
        monkeypatch.setattr(guardrails_module, "SafetyInputFilter", lambda settings: FakeInputFilter())
        monkeypatch.setattr(guardrails_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(guardrails_module, "settings", make_settings())
        svc = IntentGuardrailService()
        assert await svc.evaluate("询问薪资") == (False, "越权")

    @pytest.mark.asyncio
    async def test_llm_pass(self, monkeypatch):
        client = FakeClient(content=json.dumps({"action": "pass", "reason": ""}))
        monkeypatch.setattr(guardrails_module, "SafetyInputFilter", lambda settings: FakeInputFilter())
        monkeypatch.setattr(guardrails_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(guardrails_module, "settings", make_settings())
        svc = IntentGuardrailService()
        assert await svc.evaluate("如何配置") == (True, "")

    @pytest.mark.asyncio
    async def test_llm_empty_content_safe(self, monkeypatch):
        client = FakeClient(content=None)
        monkeypatch.setattr(guardrails_module, "SafetyInputFilter", lambda settings: FakeInputFilter())
        monkeypatch.setattr(guardrails_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(guardrails_module, "settings", make_settings())
        svc = IntentGuardrailService()
        assert await svc.evaluate("如何配置") == (True, "")

    @pytest.mark.asyncio
    async def test_llm_error_fail_close(self, monkeypatch):
        client = FakeClient(error=RuntimeError("down"))
        monkeypatch.setattr(guardrails_module, "SafetyInputFilter", lambda settings: FakeInputFilter())
        monkeypatch.setattr(guardrails_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(guardrails_module, "settings", make_settings(mode=SafetyMode.FAIL_CLOSE))
        svc = IntentGuardrailService()
        assert await svc.evaluate("如何配置") == (False, "安全检测服务异常，已拒绝该请求。")

    @pytest.mark.asyncio
    async def test_llm_error_monitor_allows(self, monkeypatch):
        client = FakeClient(error=RuntimeError("down"))
        monkeypatch.setattr(guardrails_module, "SafetyInputFilter", lambda settings: FakeInputFilter())
        monkeypatch.setattr(guardrails_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(guardrails_module, "settings", make_settings(mode=SafetyMode.MONITOR))
        svc = IntentGuardrailService()
        assert await svc.evaluate("如何配置") == (True, "")
