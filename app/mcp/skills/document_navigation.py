"""
DocumentNavigation Skill — 文档结构导航

查询文档的章节层级结构（Neo4j 图），返回文档大纲和标题树。
"""

import json

import structlog
from langchain_core.tools import tool

from app.mcp.skill_base import BaseSkill, SkillTool
from app.safety.enums import ToolRisk

logger = structlog.get_logger(__name__)


@tool
async def get_document_structure(doc_id: str) -> str:
    """获取文档的章节结构（目录导航树）。

    Args:
        doc_id: 文档 ID

    Returns:
        文档层级结构 JSON
    """
    from app.config import get_settings
    from app.rag.graph.composite_graph_service import CompositeGraphService

    if not get_settings().neo4j.enabled:
        return "文档图谱功能当前未启用，请开启 Neo4j 后重试。"

    logger.info("skill tool: get_document_structure", doc_id=doc_id)

    engine = CompositeGraphService()
    tree = await engine.get_document_tree(doc_id)

    if not tree:
        return "未找到文档结构或文档不存在。"

    return json.dumps(tree, ensure_ascii=False, indent=2)


class DocumentNavigationSkill(BaseSkill):
    name = "document_navigation"
    description = "查询知识库文档的章节结构与目录导航"
    risk = ToolRisk.LOW
    system_prompt_fragment = (
        "- get_document_structure: 获取文档的章节结构。"
        "传入 doc_id（文档 ID）。"
        "返回文档的目录层级树，当用户想了解文档结构或定位特定章节时使用。"
    )

    def get_tools(self) -> list[SkillTool]:
        return [
            SkillTool(
                name="get_document_structure",
                fn=get_document_structure,
                description="获取文档的章节结构（目录导航树）。传入 doc_id。",
            )
        ]
