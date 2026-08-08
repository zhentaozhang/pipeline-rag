import asyncio

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import graph as graph_module
from app.agent.graph import (
    _call_with_retry,
    _extract_fallback_query,
    _normalise_tool_args,
    _tavily_fallback,
    should_continue,
)


class TestExtractFallbackQuery:
    def test_latest_human_message(self):
        messages = [
            HumanMessage(content="旧问题"),
            AIMessage(content="回答"),
            HumanMessage(content="最新问题"),
        ]
        assert _extract_fallback_query(messages) == "最新问题"

    def test_no_human_message(self):
        assert _extract_fallback_query([AIMessage(content="hi")]) == ""

    def test_empty_content_skipped(self):
        messages = [HumanMessage(content="   "), HumanMessage(content="有效")]
        assert _extract_fallback_query(messages) == "有效"


class TestNormaliseToolArgs:
    def test_dict_kept(self):
        assert _normalise_tool_args({"query": "q"}, "fb") == {"query": "q"}

    def test_json_string_parsed(self):
        assert _normalise_tool_args('{"query": "q1"}', "fb") == {"query": "q1"}

    def test_invalid_json_falls_back_to_raw(self):
        assert _normalise_tool_args("not json", "fb") == {"query": "not json"}

    def test_empty_args_gets_fallback_query(self):
        assert _normalise_tool_args({}, "fb") == {"query": "fb"}

    def test_missing_query_gets_fallback(self):
        assert _normalise_tool_args({"other": 1}, "fb") == {"other": 1, "query": "fb"}

    def test_empty_query_gets_fallback(self):
        assert _normalise_tool_args({"query": "  "}, "fb") == {"query": "fb"}

    def test_non_dict_str_empty(self):
        assert _normalise_tool_args("", "fb") == {"query": "fb"}

    def test_original_not_mutated(self):
        args = {"query": "q"}
        _normalise_tool_args(args, "fb")
        assert args == {"query": "q"}


async def _fake_sleep(_):
    pass


class TestCallWithRetry:
    async def test_success_first_try(self):
        class FakeTool:
            def __init__(self):
                self.calls = 0

            async def ainvoke(self, args):
                self.calls += 1
                return "ok"

        tool = FakeTool()
        result = await _call_with_retry(tool, {"query": "q"}, max_retries=2)
        assert result == "ok"
        assert tool.calls == 1

    async def test_success_after_retry(self, monkeypatch):
        calls = {"n": 0}

        class FlakyTool:
            async def ainvoke(self, args):
                calls["n"] += 1
                if calls["n"] < 2:
                    raise RuntimeError("boom")
                return "recovered"

        monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
        result = await _call_with_retry(FlakyTool(), {}, max_retries=2)
        assert result == "recovered"
        assert calls["n"] == 2

    async def test_exhausted_returns_error_message(self, monkeypatch):
        class BrokenTool:
            async def ainvoke(self, args):
                raise RuntimeError("always fails")

        monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
        result = await _call_with_retry(BrokenTool(), {}, max_retries=1)
        assert "已重试1次" in result
        assert "always fails" in result

    async def test_max_retries_zero_single_try(self):
        class BrokenTool:
            async def ainvoke(self, args):
                raise RuntimeError("x")

        result = await _call_with_retry(BrokenTool(), {}, max_retries=0)
        assert "工具执行失败" in result


class TestTavilyFallback:
    async def test_delegates(self, monkeypatch):
        async def fake_search(query, topic=None, max_results=None):
            return {"answer": "a", "results": []}

        monkeypatch.setattr(graph_module, "_tavily_search_api", fake_search)
        result = await _tavily_fallback("q")
        assert result == {"answer": "a", "results": []}

    async def test_error_returns_unavailable(self, monkeypatch):
        async def broken_search(query, topic=None, max_results=None):
            raise RuntimeError("down")

        monkeypatch.setattr(graph_module, "_tavily_search_api", broken_search)
        result = await _tavily_fallback("q")
        assert result == "搜索服务不可用：down"


class FakeAIMessage:
    def __init__(self, tool_calls=None):
        self.tool_calls = tool_calls


class TestShouldContinue:
    def test_no_messages_ends(self):
        assert should_continue({"messages": []}) == "__end__"

    def test_no_tool_calls_ends(self):
        state = {"messages": [FakeAIMessage(None)], "tool_call_count": 0}
        assert should_continue(state) == "__end__"

    def test_tool_calls_continue(self):
        state = {
            "messages": [FakeAIMessage([{"id": "1", "name": "t", "args": {}}])],
            "tool_call_count": 0,
            "session_tool_call_count": 0,
        }
        assert should_continue(state) == "tools"

    def test_run_limit_reached_ends(self, monkeypatch):
        settings = graph_module.settings
        monkeypatch.setattr(settings.agent, "max_tool_calls_per_run", 2)
        state = {
            "messages": [FakeAIMessage([{"id": "1", "name": "t", "args": {}}])],
            "tool_call_count": 2,
            "session_tool_call_count": 0,
        }
        assert should_continue(state) == "__end__"

    def test_session_limit_reached_ends(self, monkeypatch):
        settings = graph_module.settings
        monkeypatch.setattr(settings.agent, "max_tool_calls_per_session", 3)
        state = {
            "messages": [FakeAIMessage([{"id": "1", "name": "t", "args": {}}])],
            "tool_call_count": 0,
            "session_tool_call_count": 3,
        }
        assert should_continue(state) == "__end__"


class TestCallModelLimits:
    async def test_run_limit_short_circuit(self, monkeypatch):
        settings = graph_module.settings
        monkeypatch.setattr(settings.agent, "max_model_calls_per_run", 1)
        result = await graph_module.call_model(
            {"messages": [], "model_call_count": 1, "session_call_count": 0}
        )
        assert "单轮最大调用次数" in result["messages"][0].content

    async def test_session_limit_short_circuit(self, monkeypatch):
        settings = graph_module.settings
        monkeypatch.setattr(settings.agent, "max_model_calls_per_session", 1)
        result = await graph_module.call_model(
            {"messages": [], "model_call_count": 0, "session_call_count": 1}
        )
        assert "会话最大调用次数" in result["messages"][0].content


class TestCallTool:
    async def test_unknown_tool(self, monkeypatch):
        class FakeRegistry:
            @staticmethod
            def resolve(name):
                return None

            @staticmethod
            def list_tools():
                return {"known_tool": None}

        monkeypatch.setattr("app.mcp.skill_registry.SkillRegistry", FakeRegistry)
        state = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"id": "call_1", "name": "ghost", "args": {}}],
                )
            ],
            "tool_call_count": 0,
            "session_tool_call_count": 0,
        }
        result = await graph_module.call_tool(state)
        (msg,) = result["messages"]
        assert isinstance(msg, ToolMessage)
        assert "未知工具 ghost" in msg.content
        assert msg.tool_call_id == "call_1"

    async def test_approval_blocks(self, monkeypatch):
        class FakePolicy:
            async def require_approval(self, name, args):
                return True

        class FakeRegistry:
            @staticmethod
            def resolve(name):
                return None

            @staticmethod
            def list_tools():
                return {}

        monkeypatch.setattr(graph_module, "ApprovalPolicy", FakePolicy)
        monkeypatch.setattr("app.mcp.skill_registry.SkillRegistry", FakeRegistry)
        state = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"id": "c2", "name": "risky", "args": {}}],
                )
            ],
            "tool_call_count": 0,
            "session_tool_call_count": 0,
        }
        result = await graph_module.call_tool(state)
        (msg,) = result["messages"]
        assert "需要人工审批" in msg.content

    async def test_successful_tool_execution(self, monkeypatch):
        class FakePolicy:
            async def require_approval(self, name, args):
                return False

        class FakeEntry:
            def __init__(self):
                self.fn = FakeFn()

        class FakeFn:
            args = {"query": "str"}

            async def ainvoke(self, args):
                return "工具结果"

        class FakeRegistry:
            @staticmethod
            def resolve(name):
                return FakeEntry()

        monkeypatch.setattr(graph_module, "ApprovalPolicy", FakePolicy)
        monkeypatch.setattr("app.mcp.skill_registry.SkillRegistry", FakeRegistry)
        state = {
            "messages": [
                HumanMessage(content="帮我搜下天气"),
                AIMessage(
                    content="",
                    tool_calls=[{"id": "c3", "name": "search", "args": {}}],
                ),
            ],
            "tool_call_count": 0,
            "session_tool_call_count": 0,
        }
        result = await graph_module.call_tool(state)
        (msg,) = result["messages"]
        assert msg.content == "工具结果"
        assert result["tool_call_count"] == 1
        assert result["session_tool_call_count"] == 1
