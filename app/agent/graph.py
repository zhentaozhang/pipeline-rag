"""
LangGraph ReAct Agent 构建
"""

import asyncio
import json as _json
import logging
import random as _random
from functools import cache
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langchain_core.tools import tool
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages

from app.agent.tools.tavily import tavily_search as _tavily_search_api
from app.common.llm_client import llm_breaker
from app.config import get_settings
from app.safety.tool_registry import ApprovalPolicy

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Tavily 工具入参兜底 ─────────────────────────────────────────────────────


def _extract_fallback_query(messages: list[BaseMessage]) -> str:
    """从消息历史中提取用户原始问题作为工具入参兜底"""
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def _normalise_tool_args(args: dict | str, fallback_query: str) -> dict:
    """规范化工具入参：缺失 query 时用原始问题兜底"""
    if not isinstance(args, dict):
        if isinstance(args, str) and args.strip():
            try:
                args = _json.loads(args)
            except Exception:
                logger.debug("tool args json parse failed, using raw string: %s", args[:80])
                args = {"query": args.strip()}
        else:
            args = {}
    if (not args.get("query") or not str(args.get("query", "")).strip()) and fallback_query:
        args = dict(args)
        args["query"] = fallback_query
    return args


# ── 工具重试拦截器 ───────────────────────────────────────────────────────────


async def _call_with_retry(tool_fn: Any, args: dict, max_retries: int = 2) -> str:
    """200ms→1200ms 指数退避 + jitter"""
    last_error = ""
    for attempt in range(1 + max_retries):
        try:
            result = await tool_fn.ainvoke(args)
            return str(result)
        except Exception as e:
            last_error = str(e)
            logger.debug("tool call attempt failed: attempt=%s max_retries=%s error=%s", attempt + 1, max_retries, str(e))
            if attempt < max_retries:
                delay_ms = min(200 * (2**attempt), 1200)
                delay_ms += _random.randint(0, 100)
                await asyncio.sleep(delay_ms / 1000)
    logger.warning("tool call exhausted retries: max_retries=%s error=%s", max_retries, last_error)
    return f"工具执行失败（已重试{max_retries}次）：{last_error}"


async def _tavily_fallback(
    query: str, topic: str | None = None, max_results: int | None = None
) -> str:
    """Tavily 回退：主调用失败后的备用搜索"""
    try:
        return await _tavily_search_api(query, topic=topic, max_results=max_results)
    except Exception as e:
        logger.warning("tavily fallback search failed: query=%s error=%s", query[:80], str(e))
        return f"搜索服务不可用：{str(e)}"


# ── 模型实例（provider-aware）────────────────────────────────────────────────

_shared_model: Any | None = None


def _get_model() -> Any:
    """懒加载工厂函数，返回全局共享模型实例"""
    global _shared_model
    if _shared_model is None:
        from app.common.llm_client import get_langchain_chat_model

        _shared_model = get_langchain_chat_model()
    return _shared_model


# ── Agent 状态定义 ────────────────────────────────────────────────────────────


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    tool_call_count: int
    model_call_count: int
    session_call_count: int
    session_tool_call_count: int


# ── 工具定义 ──────────────────────────────────────────────────────────────────


@tool
async def tavily_search(
    query: str, topic: str | None = None, max_results: int | None = None
) -> str:
    """联网搜索最新信息、事实资料和网页来源。调用时必须传 JSON 参数，且至少包含非空 query；可选 topic 和 maxResults，其中 topic 仅允许 general、news、finance。"""
    res = await _tavily_fallback(query, topic=topic, max_results=max_results)
    if isinstance(res, dict) and res.get("error"):
        return f"搜索失败: {res['error']}"

    parts = []
    if isinstance(res, dict):
        if res.get("answer"):
            parts.append(f"AI 摘要: {res['answer']}")
        for item in res.get("results", []):
            parts.append(
                f"来源: {item.get('title', '')} ({item.get('url', '')})\n内容: {item.get('content', '')}"
            )
    else:
        parts.append(str(res))

    return "\n\n".join(parts) if parts else "未找到相关结果。"


def _get_agent_tools():
    from app.mcp.skill_registry import SkillRegistry

    SkillRegistry.discover()
    return SkillRegistry.get_tools()


# ── 节点逻辑 ──────────────────────────────────────────────────────────────────


async def call_model(state: AgentState):
    """调用 LLM 并决定下一步（含调用限制钩子 + DashScope 兼容）"""
    run_count = state.get("model_call_count", 0)
    session_count = state.get("session_call_count", 0)

    if run_count >= settings.agent.max_model_calls_per_run:
        return {
            "messages": [
                BaseMessage(
                    content=f"已到达单轮最大调用次数（{settings.agent.max_model_calls_per_run}），请精简问题后重试。",
                    type="ai",
                )
            ]
        }
    if session_count >= settings.agent.max_model_calls_per_session:
        return {
            "messages": [
                BaseMessage(
                    content=f"已到达会话最大调用次数（{settings.agent.max_model_calls_per_session}），请开始新会话。",
                    type="ai",
                )
            ]
        }

    model = _get_model().bind_tools(_get_agent_tools())
    if settings.circuit_breaker.enabled:
        async with llm_breaker():
            response = await model.ainvoke(state["messages"])
    else:
        response = await model.ainvoke(state["messages"])

    return {
        "messages": [response],
        "model_call_count": run_count + 1,
        "session_call_count": session_count + 1,
    }


async def call_tool(state: AgentState):
    """执行工具调用（含审批策略 + 重试拦截器 + 并行执行 + 入参兜底）"""
    from langchain_core.messages import ToolMessage

    from app.mcp.skill_registry import SkillRegistry

    messages = state["messages"]
    last_message = messages[-1]
    tool_messages = []

    fallback_query = _extract_fallback_query(messages)
    tool_calls = getattr(last_message, "tool_calls", [])

    approval_policy = ApprovalPolicy()
    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]

        if await approval_policy.require_approval(tool_name, tool_args):
            logger.warning("tool_approval_required, blocking tool: %s", tool_name)
            tool_messages.append(
                ToolMessage(
                    content=f"工具 {tool_name} 需要人工审批，当前模式不支持自动执行。",
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                )
            )
            continue

        tool_entry = SkillRegistry.resolve(tool_name)
        if tool_entry:
            fn = tool_entry.fn
            has_query = hasattr(fn, "args") and "query" in fn.args
            normalised_args = (
                _normalise_tool_args(tool_args, fallback_query)
                if has_query
                else (tool_args if isinstance(tool_args, dict) else {})
            )
            result = await _call_with_retry(fn, normalised_args)
        else:
            logger.warning("unknown tool: %s", tool_name)
            tool_messages.append(
                ToolMessage(
                    content=f"未知工具 {tool_name}，当前可用工具：{', '.join(SkillRegistry.list_tools().keys())}",
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                )
            )
            continue

        tool_messages.append(
            ToolMessage(
                content=result,
                tool_call_id=tool_call["id"],
                name=tool_name,
            )
        )

    return {
        "messages": tool_messages,
        "tool_call_count": state.get("tool_call_count", 0) + len(tool_messages),
        "session_tool_call_count": state.get("session_tool_call_count", 0) + len(tool_messages),
    }


def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    """条件边：根据 LLM 输出决定是否继续调用工具"""
    messages = state.get("messages", [])
    if not messages:
        return "__end__"
    last_message = messages[-1]

    run_count = state.get("tool_call_count", 0)
    session_count = state.get("session_tool_call_count", 0)

    if getattr(last_message, "tool_calls", None):
        if run_count >= settings.agent.max_tool_calls_per_run:
            return "__end__"
        if session_count >= settings.agent.max_tool_calls_per_session:
            return "__end__"
        return "tools"
    return "__end__"


# ── 构建图 ────────────────────────────────────────────────────────────────────


@cache
def build_react_graph() -> StateGraph:
    """构建并返回未编译的 LangGraph 实例"""

    workflow = StateGraph(AgentState)

    workflow.add_node("agent", call_model)
    workflow.add_node("tools", call_tool)

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")

    return workflow
