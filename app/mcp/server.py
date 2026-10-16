"""
FastMCP Server — 对外 MCP 工具协议服务。

定位（重要）：本模块是**独立进程**的对外集成入口，供外部 MCP 客户端连接；
主应用内的 Agent 工具注册走 `app/mcp/skill_registry.py`（SkillRegistry）。
两者共用同一份工具实现，避免逻辑分叉：

- 工具实现归属 SkillRegistry（`app/mcp/skills/`）
- 本文件只做 MCP 协议适配（显式声明参数 schema 以便外部客户端发现），
  具体执行统一委托给 SkillRegistry 中已注册的工具

功能：
- Stdio / SSE 两种传输模式
- 工具调用异常隔离（失败返回可读文本，不向客户端抛栈）
"""

from typing import Any, Literal

import structlog
from fastmcp import FastMCP

logger = structlog.get_logger(__name__)

# 创建 FastMCP 实例
mcp: FastMCP = FastMCP(
    name="pipeline-rag-mcp",
    instructions="Pipeline RAG MCP Server，提供知识库查询、文档检索等工具能力。",
)


async def _invoke_skill_tool(tool_name: str, args: dict[str, Any]) -> str:
    """调用 SkillRegistry 中注册的工具。

    工具实现可能是 langchain BaseTool（需 ainvoke）或普通协程函数（需直接调用），
    此处统一分发；失败时返回可读文本而非抛异常，避免污染 MCP 客户端。
    """
    from app.mcp.skill_registry import SkillRegistry

    entry = SkillRegistry.resolve(tool_name)
    if entry is None:
        available = ", ".join(sorted(SkillRegistry.list_tools().keys()))
        return f"未注册工具 {tool_name}。当前可用工具：{available}"

    fn = entry.fn
    try:
        if hasattr(fn, "ainvoke"):
            result = await fn.ainvoke(args)
        elif hasattr(fn, "invoke"):
            result = fn.invoke(args)
        else:
            result = await fn(**args)
    except Exception as exc:
        logger.warning("mcp tool execution failed", tool=tool_name, error=str(exc), exc_info=True)
        return f"工具 {tool_name} 执行失败：{exc}"
    return str(result)


# ── 工具定义（实现统一委托给 SkillRegistry）───────────────────────────────────


@mcp.tool()
async def search_knowledge_base(query: str, scope_code: str = "") -> str:
    """
    在知识库中搜索相关信息。

    Args:
        query: 搜索查询
        scope_code: 知识域编码（为空时全库搜索）

    Returns:
        搜索结果文本
    """
    logger.info("mcp tool: search_knowledge_base", query=query[:50], scope=scope_code)
    return await _invoke_skill_tool(
        "search_knowledge_base", {"query": query, "scope_code": scope_code}
    )


@mcp.tool()
async def get_document_structure(doc_id: str) -> str:
    """
    获取文档的章节结构（目录导航树）。

    Args:
        doc_id: 文档 ID

    Returns:
        文档层级结构 JSON
    """
    logger.info("mcp tool: get_document_structure", doc_id=doc_id)
    return await _invoke_skill_tool("get_document_structure", {"doc_id": doc_id})


@mcp.tool()
async def rag_search(query: str, top_k: int = 5) -> str:
    """
    从企业内部知识库中检索相关文档内容，返回最匹配的原文片段。

    Args:
        query: 检索查询语句
        top_k: 返回的最大结果条数

    Returns:
        检索到的文档片段文本
    """
    logger.info("mcp tool: rag_search", query=query[:50], top_k=top_k)
    return await _invoke_skill_tool("rag_search", {"query": query, "top_k": top_k})


def list_registered_tools() -> dict[str, str]:
    """返回 SkillRegistry 中已注册的工具（名称 → 描述），便于运维核对。"""
    from app.mcp.skill_registry import SkillRegistry

    SkillRegistry.discover()
    return SkillRegistry.list_tools()


# ── MCP Server 启动入口（独立进程模式）───────────────────────────────────────


def run_mcp_server(transport: Literal["stdio", "sse"] = "stdio") -> None:
    """
    启动 MCP Server。
    transport: "stdio"（默认）| "sse"
    """
    from app.mcp.skill_registry import SkillRegistry

    SkillRegistry.discover()
    logger.info(
        "starting mcp server",
        transport=transport,
        skill_tools=sorted(SkillRegistry.list_tools().keys()),
    )
    mcp.run(transport=transport)


if __name__ == "__main__":
    run_mcp_server()
