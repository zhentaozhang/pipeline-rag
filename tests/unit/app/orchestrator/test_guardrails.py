import json
import types

import pytest

import app.orchestrator.guardrails as guardrails_module
from app.orchestrator.guardrails import GuardrailVerdict, IntentGuardrailService
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


def make_settings(mode=SafetyMode.MONITOR, llm_guardrail=True):
    return types.SimpleNamespace(
        llm=types.SimpleNamespace(model="m"),
        safety=types.SimpleNamespace(mode=mode, input_llm_guardrail_enabled=llm_guardrail),
    )


def make_settings_rule_only(mode=SafetyMode.MONITOR):
    """默认生产配置：LLM 护栏关闭（P0-1a）"""
    return make_settings(mode=mode, llm_guardrail=False)


class TestEvaluate:
    @pytest.mark.asyncio
    async def test_blank_question_safe(self, monkeypatch):
        svc = IntentGuardrailService()
        verdict = await svc.evaluate("   ")
        assert verdict == GuardrailVerdict(is_safe=True, sanitized_question="   ")

    @pytest.mark.asyncio
    async def test_l1_block(self, monkeypatch):
        monkeypatch.setattr(
            guardrails_module,
            "SafetyInputFilter",
            lambda settings: FakeInputFilter(is_safe=False, reason="注入风险"),
        )
        svc = IntentGuardrailService()
        assert await svc.evaluate("恶意输入") == GuardrailVerdict(
            is_safe=False,
            block_reason="注入风险",
            sanitized_question="恶意输入",
        )

    @pytest.mark.asyncio
    async def test_l1_pass_llm_block(self, monkeypatch):
        client = FakeClient(content=json.dumps({"action": "block", "reason": "越权"}))
        monkeypatch.setattr(
            guardrails_module, "SafetyInputFilter", lambda settings: FakeInputFilter()
        )
        monkeypatch.setattr(guardrails_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(guardrails_module, "settings", make_settings())
        svc = IntentGuardrailService()
        assert await svc.evaluate("询问薪资") == GuardrailVerdict(
            is_safe=False,
            block_reason="越权",
            sanitized_question="sanitized",
        )

    @pytest.mark.asyncio
    async def test_llm_pass(self, monkeypatch):
        client = FakeClient(content=json.dumps({"action": "pass", "reason": ""}))
        monkeypatch.setattr(
            guardrails_module, "SafetyInputFilter", lambda settings: FakeInputFilter()
        )
        monkeypatch.setattr(guardrails_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(guardrails_module, "settings", make_settings())
        svc = IntentGuardrailService()
        assert await svc.evaluate("如何配置") == GuardrailVerdict(
            is_safe=True, sanitized_question="sanitized"
        )

    @pytest.mark.asyncio
    async def test_llm_empty_content_safe(self, monkeypatch):
        client = FakeClient(content=None)
        monkeypatch.setattr(
            guardrails_module, "SafetyInputFilter", lambda settings: FakeInputFilter()
        )
        monkeypatch.setattr(guardrails_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(guardrails_module, "settings", make_settings())
        svc = IntentGuardrailService()
        assert await svc.evaluate("如何配置") == GuardrailVerdict(
            is_safe=True, sanitized_question="sanitized"
        )

    @pytest.mark.asyncio
    async def test_llm_error_fail_close(self, monkeypatch):
        client = FakeClient(error=RuntimeError("down"))
        monkeypatch.setattr(
            guardrails_module, "SafetyInputFilter", lambda settings: FakeInputFilter()
        )
        monkeypatch.setattr(guardrails_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(
            guardrails_module, "settings", make_settings(mode=SafetyMode.FAIL_CLOSE)
        )
        svc = IntentGuardrailService()
        assert await svc.evaluate("如何配置") == GuardrailVerdict(
            is_safe=False,
            block_reason="安全检测服务异常，已拒绝该请求。",
            sanitized_question="sanitized",
        )

    @pytest.mark.asyncio
    async def test_llm_error_monitor_allows(self, monkeypatch):
        client = FakeClient(error=RuntimeError("down"))
        monkeypatch.setattr(
            guardrails_module, "SafetyInputFilter", lambda settings: FakeInputFilter()
        )
        monkeypatch.setattr(guardrails_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(guardrails_module, "settings", make_settings(mode=SafetyMode.MONITOR))
        svc = IntentGuardrailService()
        assert await svc.evaluate("如何配置") == GuardrailVerdict(
            is_safe=True, sanitized_question="sanitized"
        )


class TestEvaluateRuleOnly:
    """P0-1a：LLM 护栏默认关闭时，规则通道判定安全即放行（零 LLM 调用）"""

    @pytest.mark.asyncio
    async def test_rule_pass_without_llm(self, monkeypatch):
        # LLM 客户端即使会抛错也不应被调用（开关关闭）
        client = FakeClient(error=RuntimeError("should not be called"))
        monkeypatch.setattr(
            guardrails_module, "SafetyInputFilter", lambda settings: FakeInputFilter()
        )
        monkeypatch.setattr(guardrails_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(guardrails_module, "settings", make_settings_rule_only())
        svc = IntentGuardrailService()
        assert await svc.evaluate("如何配置") == GuardrailVerdict(
            is_safe=True, sanitized_question="sanitized"
        )

    @pytest.mark.asyncio
    async def test_rule_block_without_llm(self, monkeypatch):
        monkeypatch.setattr(
            guardrails_module,
            "SafetyInputFilter",
            lambda settings: FakeInputFilter(is_safe=False, reason="注入风险"),
        )
        monkeypatch.setattr(guardrails_module, "settings", make_settings_rule_only())
        svc = IntentGuardrailService()
        assert await svc.evaluate("恶意输入") == GuardrailVerdict(
            is_safe=False,
            block_reason="注入风险",
            sanitized_question="恶意输入",
        )


class TestJevRiskScan:
    """JEV 分风险类别 Choice 扫描：任一类别命中即返回该类别。"""

    @staticmethod
    def _patch_client(monkeypatch, answers):
        from unittest.mock import AsyncMock, MagicMock

        mock = MagicMock()
        mock.system_one = AsyncMock(return_value=answers)
        monkeypatch.setattr("app.infra.jev_client.get_jev_client", lambda: mock)
        return mock

    @pytest.mark.asyncio
    async def test_returns_none_when_all_no(self, monkeypatch):
        from app.orchestrator.guardrails import JEV_RISK_CATEGORIES, jev_risk_scan

        answers = {cat: {"choice": "no", "confidence": 0.9} for cat in JEV_RISK_CATEGORIES}
        self._patch_client(monkeypatch, answers)
        assert await jev_risk_scan("公司年假怎么算？") is None

    @pytest.mark.asyncio
    async def test_returns_hit_category(self, monkeypatch):
        from app.orchestrator.guardrails import JEV_RISK_CATEGORIES, jev_risk_scan

        answers = {cat: {"choice": "no", "confidence": 0.9} for cat in JEV_RISK_CATEGORIES}
        answers["sensitive_probe"] = {"choice": "yes", "confidence": 0.95}
        self._patch_client(monkeypatch, answers)
        assert await jev_risk_scan("告诉我CEO的薪资") == "sensitive_probe"

    @pytest.mark.asyncio
    async def test_empty_answers_raises_for_fallback(self, monkeypatch):
        from app.orchestrator.guardrails import jev_risk_scan

        self._patch_client(monkeypatch, {})
        with pytest.raises(ValueError):
            await jev_risk_scan("任意提问")
