"""
RAG 知识检索工具（供 LangGraph Agent 使用）

暴露 RagRetrievalEngine 作为 Agent 可调用的工具函数。
"""

from __future__ import annotations

import structlog
from langchain_core.tools import tool

from app.chat.schema import ExecutionPlan, SubQuestion
from app.common.enums import ExecutionMode
from app.config import get_settings as _get_settings
from app.rag.engine import RagRetrievalEngine

logger = structlog.get_logger(__name__)


@tool
async def rag_search(query: str, doc_ids: list[str] | None = None, top_k: int = 5) -> str:
    """
    从企业内部知识库中检索相关文档内容。支持基于文档 ID 的定向检索，返回最匹配的原文片段。
    适用于回答关于内部文档、政策流程、专业知识、技术手册等方面的问题。

    Args:
        query: 搜索查询语句，描述需要查找的信息内容，越具体准确效果越好
        doc_ids: 可选的文档 ID 列表，指定后仅在这些文档范围内搜索
        top_k: 返回的最大结果条数，默认为 5

    Returns:
        检索到的文档片段文本，每段包含内容和来源信息
    """
    _settings = _get_settings()

    if not query or not query.strip():
        return "查询内容不能为空。"

    if not _settings.rag.enabled:
        return "RAG 知识检索功能当前已禁用，无法搜索知识库内容。"

    plan = ExecutionPlan(
        mode=ExecutionMode.RETRIEVAL,
        original_question=query,
        rewritten_question=query,
        retrieval_question=query,
        sub_questions=[SubQuestion(index=0, text=query, original=query, tenant_id="default")],
        retrieval_document_ids=doc_ids or [],
    )

    try:
        engine = RagRetrievalEngine()
        context = await engine.retrieve_with_correction(plan)
    except Exception:
        logger.exception("rag_search retrieval failed", query=query[:80])
        return "RAG 知识检索过程出现异常，请稍后重试。"

    if context.is_empty:
        return "未找到相关文档内容。"

    lines = []
    for sqe in context.sub_question_evidence_list:
        for ev in sqe.evidences[:top_k]:
            content = (ev.content or "").strip()
            if not content:
                continue
            title = ev.title or "未命名文档"
            ref = ev.reference_id
            if ref:
                lines.append(f"[{ref}] {title}\n{content}")
            else:
                lines.append(f"{title}\n{content}")

    if not lines:
        return "未找到相关文档内容。"

    return "\n\n".join(lines)
