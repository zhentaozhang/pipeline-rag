"""MCP 装配测试。

回归背景：`fastmcp 2.9.x` 的 `Settings` 类与 `pydantic>=2.13` 不兼容
（pydantic 抛 `TypeError: cannot specify both default and default_factory`），
导致 `import app.mcp.server` 直接失败、MCP 服务无法启动；而当时没有任何测试
导入该模块，CI 因此长期未发现。

同时锁定「MCP 工具实现单一来源」这一约定：FastMCP 暴露的工具必须委托给
SkillRegistry 中已注册的同名工具，不得各自重复实现检索逻辑。
"""

from __future__ import annotations

import pytest

from app.mcp import server as mcp_server


def test_mcp_server_module_importable():
    """依赖组合必须能成功导入 MCP 服务模块（fastmcp × pydantic 兼容性护栏）。"""
    assert mcp_server.mcp is not None


def test_skill_registry_discovers_builtin_skills():
    """三个内置 Skill 应可被自动发现并注册其工具。"""
    tools = mcp_server.list_registered_tools()
    assert {
        "search_knowledge_base",
        "rag_search",
        "get_document_structure",
        "tavily_search",
    } <= set(tools)


@pytest.mark.asyncio
async def test_fastmcp_tools_are_subset_of_skill_registry():
    """FastMCP 暴露的每个工具都必须在 SkillRegistry 中有对应实现（单一来源）。"""
    exposed = set((await mcp_server.mcp.get_tools()).keys())
    registered = set(mcp_server.list_registered_tools().keys())

    assert exposed, "FastMCP 至少应暴露一个工具"
    assert exposed <= registered, f"存在无 SkillRegistry 实现的 MCP 工具: {exposed - registered}"


@pytest.mark.asyncio
async def test_unknown_skill_tool_returns_readable_message():
    """调用未注册工具时返回可读文本，不向 MCP 客户端抛栈。"""
    msg = await mcp_server._invoke_skill_tool("__not_a_tool__", {})
    assert "__not_a_tool__" in msg
    assert "未注册工具" in msg
