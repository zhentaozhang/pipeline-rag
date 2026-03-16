"""
KnowledgeRetrieval Skill — 知识库向量检索

将用户问题在已索引的知识库中进行向量语义搜索，返回相关文档段落。
"""

import structlog
from langchain_core.tools import tool

from app.chat.schema import SubQuestion
from app.mcp.skill_base import BaseSkill, SkillTool
from app.safety.enums import ToolRisk

logger = structlog.get_logger(__name__)


@tool
async def search_knowledge_base(query: str, scope_code: str = "") -> str:
    """在知识库中搜索相关信息。

    Args:
        query: 搜索查询
        scope_code: 知识域编码（为空时全库搜索）

    Returns:
        搜索结果文本
    """
    from app.rag.channels.vector import VectorRetrievalChannel

    logger.info("skill tool: search_knowledge_base", query=query[:50], scope=scope_code)

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


@tool
async def rag_search(query: str, doc_ids: list[str] | None = None, top_k: int = 5) -> str:
    """从企业内部知识库中检索相关文档内容。支持基于文档 ID 的定向检索，返回最匹配的原文片段。适用于回答关于内部文档、政策流程、专业知识、技术手册等方面的问题。"""
    from app.agent.tools.rag_search import rag_search as _rag_search_fn

    return await _rag_search_fn(query, doc_ids=doc_ids, top_k=top_k)


class KnowledgeRetrievalSkill(BaseSkill):
    name = "knowledge_retrieval"
    description = "在知识库中进行向量语义搜索，检索相关文档内容"
    risk = ToolRisk.LOW
    system_prompt_fragment = (
        "- search_knowledge_base: 在内部知识库中搜索相关信息。"
        "传入 query（搜索内容）和可选的 scope_code（知识域编码）。"
        "当用户询问公司内部文档、制度、规范等内容时，优先使用此工具。\n"
        "- rag_search: 从企业内部知识库中检索相关文档内容。"
        "支持基于文档 ID 的定向检索和 top_k 控制，返回最匹配的原文片段。"
    )

    def get_tools(self) -> list[SkillTool]:
        return [
            SkillTool(
                name="search_knowledge_base",
                fn=search_knowledge_base,
                description="在知识库中搜索相关信息。传入 query 和可选的 scope_code。",
            ),
            SkillTool(
                name="rag_search",
                fn=rag_search,
                description="从企业内部知识库中检索相关文档内容。"
                "支持基于文档 ID 的定向检索和 top_k 控制。",
            ),
        ]
