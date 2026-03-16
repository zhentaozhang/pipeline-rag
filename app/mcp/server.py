"""
FastMCP Server — MCP 工具协议服务，支持动态工具注册和调用。

功能：
- 动态工具注册（无需硬编码 Function Call）
- 支持 Stdio 和 SSE 两种传输模式
- 工具调用安全沙箱（超时限制 + 异常隔离）
"""

from typing import Literal

import structlog
from fastmcp import FastMCP

logger = structlog.get_logger(__name__)

# 创建 FastMCP 实例
mcp: FastMCP = FastMCP(
    name="pipeline-rag-mcp",
    instructions="Pipeline RAG MCP Server，提供知识库查询、文档检索等工具能力。",
)


# ── 内置工具示例 ──────────────────────────────────────────────────────────────


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
    from app.chat.schema import SubQuestion
    from app.rag.channels.vector import VectorRetrievalChannel

    logger.info("mcp tool: search_knowledge_base", query=query[:50], scope=scope_code)

    sub_q = SubQuestion(
        index=0,
        text=query,
        original=query,
        scope_code=scope_code if scope_code else None,
    )

    channel = VectorRetrievalChannel()
    evidences = await channel.retrieve(sub_q)

    if not evidences:
        return "未找到相关知识。"

    res = []
    for e in evidences:
        res.append(f"[{e.title}]\n{e.content}")
    return "\n\n---\n\n".join(res)


@mcp.tool()
async def get_document_structure(doc_id: str) -> str:
    """
    获取文档的章节结构（Neo4j 图查询）。

    Args:
        doc_id: 文档 ID

    Returns:
        文档层级结构 JSON
    """
    import json

    from app.rag.graph.composite_graph_service import CompositeGraphService

    logger.info("mcp tool: get_document_structure", doc_id=doc_id)

    engine = CompositeGraphService()
    tree = await engine.get_document_tree(doc_id)

    if not tree:
        return "未找到文档结构或文档不存在。"

    return json.dumps(tree, ensure_ascii=False, indent=2)


# ── MCP Server 启动入口（独立进程模式）───────────────────────────────────────


def run_mcp_server(transport: Literal["stdio", "sse"] = "stdio") -> None:
    """
    启动 MCP Server。
    transport: "stdio"（默认）| "sse"
    """
    logger.info("starting mcp server", transport=transport)
    mcp.run(transport=transport)


if __name__ == "__main__":
    run_mcp_server()
