"""
知识路由 — 三级漏斗 Scope → Topic → Document + 文档内路由

三级漏斗：
1. Scope  — 语义匹配知识域（全局过滤）
2. Topic  — 在命中 Scope 内匹配主题
3. Document — 混合打分（语义 + 词法 + 关键词实体）锁定文档

同时提供文档内路由 (route_by_document)，使用 NavigationAnalyzer 执行文档内结构导航。
"""

import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

from app.orchestrator.models import DocumentRouteDecision


async def route(
    question: str,
    rewrite_question: str = "",
    conversation_id: str | None = None,
    exchange_id: int | None = None,
) -> DocumentRouteDecision:
    """
    根据问题路由到最相关的文档（Scope→Topic→Document 漏斗）。
    如果分差过小且跨领域，触发 CLARIFICATION。
    """
    import uuid

    conversation_id = conversation_id or str(uuid.uuid4())
    exchange_id = exchange_id or 1

    logger.debug(
        "knowledge routing (es funnel)", question=question[:50], conversation_id=conversation_id
    )
    from app.orchestrator.route_service import KnowledgeRouteService

    route_svc = KnowledgeRouteService()

    decision = await route_svc.route(question, rewrite_question or question)

    candidates = decision.documents
    if not candidates:
        return DocumentRouteDecision(execution_mode="REACT_AGENT")

    await route_svc.record_auto_route(
        conversation_id, exchange_id, question, rewrite_question or question, decision
    )

    if len(candidates) >= 2:
        top_score = float(candidates[0].score) if candidates[0].score else 0.0
        second_score = float(candidates[1].score) if candidates[1].score else 0.0
        top_scope = candidates[0].scope_code
        second_scope = candidates[1].scope_code

        if (top_score - second_score) <= 3 and top_scope != second_scope:
            options = []
            for _idx, c in enumerate(candidates[:3]):
                options.append(f"我想问《{c.document_name}》")
            reply = "这个问题目前存在文档范围歧义，我先确认你想问哪一份："
            return DocumentRouteDecision(
                execution_mode="CLARIFICATION",
                clarification_reply=reply,
                clarification_options=options,
            )

    return DocumentRouteDecision(
        execution_mode="RETRIEVAL",
        doc_ids=[candidates[0].document_id],
    )


async def route_by_document(
    document_id: str | None,
    question: str,
    rewrite_question: str = "",
) -> DocumentRouteDecision | None:
    """
    文档内路由（使用 NavigationAnalyzer 执行文档内结构导航）。

    在已知文档 ID 前提下，判断是走 GRAPH_ONLY / GRAPH_THEN_EVIDENCE / RETRIEVAL，
    返回带有 execution_mode 的决策。
    """
    if not document_id:
        return DocumentRouteDecision(execution_mode="RETRIEVAL")

    from app.orchestrator.navigation_analyzer import analyze as nav_analyze

    nav_decision = await nav_analyze(doc_id=document_id, original_question=question)

    if nav_decision is None:
        return DocumentRouteDecision(execution_mode="RETRIEVAL", doc_ids=[document_id])

    if (
        nav_decision.action == "SECTION_ADJACENCY_LOOKUP"
        or nav_decision.action == "CHILD_SECTION_DESCEND"
    ):
        return DocumentRouteDecision(execution_mode="GRAPH_ONLY", doc_ids=[document_id])
    if (
        nav_decision.action == "ITEM_REFERENCE"
        and nav_decision.item_anchor
        and nav_decision.item_anchor.item_index is not None
    ):
        return DocumentRouteDecision(execution_mode="GRAPH_THEN_EVIDENCE", doc_ids=[document_id])

    return DocumentRouteDecision(execution_mode="RETRIEVAL", doc_ids=[document_id])
