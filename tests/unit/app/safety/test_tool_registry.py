import pytest

from app.safety.enums import ToolRisk
from app.safety.tool_registry import ApprovalPolicy, ToolRegistry, ToolSpec, _maybe_awaitable


@pytest.fixture(autouse=True)
def reset_registry():
    ToolRegistry.reset()
    yield
    ToolRegistry.reset()


class TestToolRegistry:
    def test_register_and_get(self):
        spec = ToolRegistry.register("search", ToolRisk.LOW, "搜索")
        assert isinstance(spec, ToolSpec)
        assert spec.name == "search"
        assert spec.risk == ToolRisk.LOW
        assert spec.description == "搜索"
        assert ToolRegistry.get("search") is spec

    def test_get_missing_returns_none(self):
        assert ToolRegistry.get("ghost") is None

    def test_get_risk_unknown_defaults_high(self):
        assert ToolRegistry.get_risk("ghost") == ToolRisk.HIGH
        ToolRegistry.register("safe", ToolRisk.LOW)
        assert ToolRegistry.get_risk("safe") == ToolRisk.LOW

    def test_enabled_defaults_true(self):
        ToolRegistry.register("t", ToolRisk.LOW)
        assert ToolRegistry.is_enabled("t") is True

    def test_is_enabled_unknown_false(self):
        assert ToolRegistry.is_enabled("ghost") is False

    def test_set_enabled(self):
        ToolRegistry.register("t", ToolRisk.LOW)
        ToolRegistry.set_enabled("t", False)
        assert ToolRegistry.is_enabled("t") is False

    def test_set_enabled_unknown_noop(self):
        ToolRegistry.set_enabled("ghost", False)

    def test_list_tools(self):
        ToolRegistry.register("a", ToolRisk.LOW)
        ToolRegistry.register("b", ToolRisk.CRITICAL)
        assert ToolRegistry.list_tools() == {"a": ToolRisk.LOW, "b": ToolRisk.CRITICAL}

    def test_reset(self):
        ToolRegistry.register("a", ToolRisk.LOW)
        ToolRegistry.reset()
        assert ToolRegistry.list_tools() == {}


class TestApprovalPolicy:
    async def test_critical_always_requires(self):
        ToolRegistry.register("rm", ToolRisk.CRITICAL)
        policy = ApprovalPolicy()
        assert await policy.require_approval("rm", {}) is True

    async def test_high_with_danger_keyword_requires(self):
        ToolRegistry.register("sql", ToolRisk.HIGH)
        policy = ApprovalPolicy()
        assert await policy.require_approval("sql", {"sql": "DELETE FROM users"}) is True

    async def test_high_safe_args_allowed(self):
        ToolRegistry.register("sql", ToolRisk.HIGH)
        policy = ApprovalPolicy()
        assert await policy.require_approval("sql", {"sql": "SELECT 1"}) is False

    async def test_high_keyword_case_insensitive(self):
        ToolRegistry.register("sql", ToolRisk.HIGH)
        policy = ApprovalPolicy()
        assert await policy.require_approval("sql", {"sql": "drop table x"}) is True

    async def test_medium_and_low_auto_allowed(self):
        ToolRegistry.register("mid", ToolRisk.MEDIUM)
        ToolRegistry.register("low", ToolRisk.LOW)
        policy = ApprovalPolicy()
        assert await policy.require_approval("mid", {}) is False
        assert await policy.require_approval("low", {}) is False

    async def test_unknown_tool_high_risk_requires(self):
        policy = ApprovalPolicy()
        assert await policy.require_approval("unknown_tool", {"x": "DROP"}) is True

    async def test_custom_policy_sync(self):
        policy = ApprovalPolicy(custom_policy=lambda name, args: name == "blocked")
        assert await policy.require_approval("blocked", {}) is True
        assert await policy.require_approval("free", {}) is False

    async def test_custom_policy_async(self):
        async def policy_fn(name, args):
            return True

        policy = ApprovalPolicy(custom_policy=policy_fn)
        assert await policy.require_approval("anything", {}) is True

    async def test_custom_policy_error_defaults_approve(self):
        def broken(name, args):
            raise RuntimeError("boom")

        policy = ApprovalPolicy(custom_policy=broken)
        assert await policy.require_approval("x", {}) is True

    async def test_custom_policy_skips_registry_check(self):
        ToolRegistry.register("low", ToolRisk.LOW)
        policy = ApprovalPolicy(custom_policy=lambda name, args: False)
        assert await policy.require_approval("low", {}) is False


class TestMaybeAwaitable:
    async def test_sync(self):
        assert await _maybe_awaitable(lambda: True) is True

    async def test_sync_falsy(self):
        assert await _maybe_awaitable(lambda: 0) is False

    async def test_async(self):
        async def f():
            return True

        assert await _maybe_awaitable(f) is True
