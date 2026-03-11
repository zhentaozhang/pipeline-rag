"""
图查询执行器（GraphOnly + GraphThenEvidence）

GraphOnly:         仅走 Neo4j 图遍历直接回答
GraphThenEvidence: 图遍历定位 → 取证召回 → 渲染回答
"""

from collections.abc import AsyncIterator
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.schema import ExecutionPlan
from app.chat.task_info import ChatTaskInfo
from app.common.enums import ExecutionMode
from app.common.sse import SSEEventType
from app.config import get_settings
from app.executors.base import ConversationExecutor
from app.rag.graph.models import (
    GraphQueryResult,
)

logger = structlog.get_logger(__name__)
settings = get_settings()

NAV_ACTION_ADJACENCY = "SECTION_ADJACENCY_LOOKUP"


class GraphExecutor(ConversationExecutor):
    """纯图查询执行器：仅走 Neo4j 图遍历回答"""

    mode = ExecutionMode.GRAPH_ONLY

    def __init__(self, db: AsyncSession, task: ChatTaskInfo) -> None:
        self.db = db
        self.task = task

    async def execute(self, plan: ExecutionPlan) -> AsyncIterator[str]:
        from app.observability import SpanKind
        from app.observability.tracer import _DummySpan as _NoopSpan
        from app.rag.graph.graph_engine import StructureGraphQueryEngine
        from app.rag.graph_renderer import GraphAnswerRenderer

        tracer = self.task.tracer
        logger.debug("graph executor run", conversation_id=self.task.conversation_id)

        no_evidence = plan.no_evidence_reply or settings.rag.no_evidence_reply

        nav_decision = plan.navigation_decision if plan else None
        if (
            not plan
            or not nav_decision
            or not nav_decision.structure_anchor
            or not nav_decision.structure_anchor.structure_node_id
        ):
            logger.info(
                "GRAPH_ONLY 执行器直接返回无证据: planPresent=%s, decisionPresent=%s, structureNodeId=%s",
                plan is not None,
                nav_decision is not None,
                nav_decision.structure_anchor.structure_node_id
                if nav_decision and nav_decision.structure_anchor
                else None,
            )
            yield self._emit(SSEEventType.TEXT, no_evidence)
            return

        yield self._emit(SSEEventType.THINKING, "正在通过结构图直接查询章节关系。")
        self.task.thinking_steps.append("正在通过结构图直接查询章节关系。")
        doc_id = plan.selected_document_id
        section_node_id = nav_decision.structure_anchor.structure_node_id

        engine = StructureGraphQueryEngine()
        renderer = GraphAnswerRenderer()

        logger.info(
            "GRAPH_ONLY 执行开始: documentId=%s, sectionNodeId=%s, action=%s, navigationSummary='%s'",
            doc_id,
            section_node_id,
            nav_decision.action,
            nav_decision.summary_text,
        )

        async with (tracer.span("graph_query", kind=SpanKind.RETRIEVAL) if tracer else _NoopSpan()):
            graph_result: GraphQueryResult
            if nav_decision.action == NAV_ACTION_ADJACENCY:
                result = await engine.find_section_with_siblings(doc_id, section_node_id)
                graph_result = GraphQueryResult(
                    target_section=result.section,
                    parent_section=result.parent,
                    prev_sibling=result.previous_sibling,
                    next_sibling=result.next_sibling,
                )
            else:
                result = await engine.find_section_with_children(doc_id, section_node_id)
                graph_result = GraphQueryResult(
                    target_section=result.section,
                    children=result.children,
                )

            target_section = graph_result.target_section
            answer = renderer.render_graph_answer(
                mode=self.mode.value,
                graph_result=graph_result,
                question=plan.original_question,
                navigation_action=nav_decision.action,
            )

            logger.info(
                "GRAPH_ONLY 执行完成: documentId=%s, sectionNodeId=%s, targetSection='%s', answerLength=%s",
                doc_id,
                section_node_id,
                target_section.display_title() if target_section else "",
                len(answer) if answer else 0,
            )

        if not answer.strip():
            yield self._emit(SSEEventType.TEXT, no_evidence)
        else:
            yield self._emit(SSEEventType.TEXT, answer)


class GraphThenEvidenceExecutor(ConversationExecutor):
    """
    图查询 + 证据召回混合执行器。
    先走图查询定位文档结构节点，再基于节点范围取证并渲染。
    """

    mode = ExecutionMode.GRAPH_THEN_EVIDENCE

    def __init__(self, db: AsyncSession, task: ChatTaskInfo) -> None:
        self.db = db
        self.task = task

    def extract_item_keyword(self, question: str, _nav_decision: Any = None) -> str:
        """从关键词中提取条目关键字（取最后一个分隔符后的部分）"""
        normalized = question or ""
        if "哪一步" in normalized or "哪一项" in normalized:
            sep = "哪一步" if "哪一步" in normalized else "哪一项"
            idx = normalized.index(sep) + len(sep)
            keyword = normalized[idx:]
            keyword = (
                keyword.replace("要求", "")
                .replace("需要", "")
                .replace("执行", "")
                .replace("进行", "")
                .replace("包含", "")
                .replace("的是", "")
                .replace("是什么", "")
                .replace("什么", "")
                .replace("？", "")
                .replace("?", "")
                .replace("。", "")
                .replace("，", "")
                .strip()
            )
            if keyword:
                return keyword
        return ""

    async def execute(self, plan: ExecutionPlan) -> AsyncIterator[str]:
        from app.observability import SpanKind
        from app.observability.tracer import _DummySpan as _NoopSpan
        from app.rag.graph.graph_engine import StructureGraphQueryEngine
        from app.rag.graph_renderer import GraphAnswerRenderer

        tracer = self.task.tracer
        logger.info("graph-then-evidence executor run", conversation_id=self.task.conversation_id)

        no_evidence = plan.no_evidence_reply or settings.rag.no_evidence_reply

        nav_decision = plan.navigation_decision if plan else None
        if (
            not plan
            or not nav_decision
            or not nav_decision.structure_anchor
            or not nav_decision.structure_anchor.structure_node_id
        ):
            logger.info(
                "GRAPH_THEN_EVIDENCE 执行器直接返回无证据: planPresent=%s, decisionPresent=%s, structureNodeId=%s",
                plan is not None,
                nav_decision is not None,
                nav_decision.structure_anchor.structure_node_id
                if nav_decision and nav_decision.structure_anchor
                else None,
            )
            yield self._emit(SSEEventType.TEXT, no_evidence)
            return

        yield self._emit(SSEEventType.THINKING, "正在通过结构图定位目标章节和编号项。")
        self.task.thinking_steps.append("正在通过结构图定位目标章节和编号项。")
        doc_id = plan.selected_document_id
        section_node_id = nav_decision.structure_anchor.structure_node_id

        item_anchor = nav_decision.item_anchor
        item_index = item_anchor.item_index if item_anchor else None
        item_keyword = self.extract_item_keyword(plan.original_question, nav_decision)

        logger.info(
            "GRAPH_THEN_EVIDENCE 执行开始: documentId=%s, sectionNodeId=%s, itemIndex=%s, navigationSummary='%s'",
            doc_id,
            section_node_id,
            item_index,
            nav_decision.summary_text,
        )

        engine = StructureGraphQueryEngine()
        async with (tracer.span("graph_query", kind=SpanKind.RETRIEVAL) if tracer else _NoopSpan()):
            graph_result = await engine.build_graph_result(
                doc_id=doc_id,
                target_section_node_id=section_node_id,
                target_item_index=item_index,
                item_keyword=item_keyword,
            )

            if not self._hasGraphEvidence(graph_result, nav_decision):
                logger.info(
                    "GRAPH_THEN_EVIDENCE 证据校验失败: documentId=%s, sectionNodeId=%s, notes=%s",
                    doc_id,
                    section_node_id,
                    ["结构图未定位到满足条件的章节或编号项。"],
                )
                yield self._emit(SSEEventType.TEXT, no_evidence)
                return

            renderer = GraphAnswerRenderer()
            answer = renderer.render_graph_answer(
                mode=self.mode.value,
                graph_result=graph_result,
            )

            logger.info(
                "GRAPH_THEN_EVIDENCE 执行完成: documentId=%s, sectionNodeId=%s, targetSection='%s', targetItemIndex=%s, answerLength=%s",
                doc_id,
                section_node_id,
                graph_result.target_section.display_title() if graph_result.target_section else "",
                graph_result.target_item.item_index if graph_result.target_item else None,
                len(answer) if answer else 0,
            )

        if not answer.strip():
            yield self._emit(SSEEventType.TEXT, no_evidence)
        else:
            yield self._emit(SSEEventType.TEXT, answer)

    @staticmethod
    def _hasGraphEvidence(graph_result: GraphQueryResult | None, nav_decision: Any) -> bool:
        if not graph_result or not graph_result.target_section:
            return False
        item_anchor = getattr(nav_decision, "item_anchor", None) if nav_decision else None
        item_index = item_anchor.item_index if item_anchor else None
        if nav_decision and item_index is not None:
            return graph_result.target_item is not None or (
                graph_result.matched_items is not None and len(graph_result.matched_items) > 0
            )
        return bool(graph_result.target_section.content_text) or (
            graph_result.matched_items is not None and len(graph_result.matched_items) > 0
        )
