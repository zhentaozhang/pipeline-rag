"""Stage 9/11 — 文档导航分析

根据路由结果执行 Neo4j/ES 导航分析，决定执行模式（GRAPH_ONLY / GRAPH_THEN_EVIDENCE / RETRIEVAL）。
"""

from __future__ import annotations

import structlog

from app.chat.schema import ExecutionPlan
from app.common.enums import ExecutionMode
from app.common.pipeline import Stage, StageResult, StageSignal
from app.orchestrator.context import PrepareContext
from app.orchestrator.navigation_analyzer import RewriteResult as NavRewriteResult
from app.orchestrator.navigation_analyzer import analyze as nav_analyze

logger = structlog.get_logger(__name__)


class NavigationAnalysisStage(Stage[PrepareContext, ExecutionPlan]):
    async def process(self, ctx: PrepareContext) -> StageResult[PrepareContext, ExecutionPlan]:
        doc_id = (
            ctx.routed_document_id
            or (ctx.original_doc_ids[0] if ctx.original_doc_ids else None)
            or ctx.original_selected_document_id
        )

        nav_rewrite = NavRewriteResult(
            rewritten_question=ctx.rewritten_question,
            sub_questions=ctx.rewrite_sub_questions,
        )
        nav_result = await nav_analyze(
            doc_id=doc_id,
            original_question=ctx.question,
            rewrite_result=nav_rewrite,
        )

        if nav_result:
            try:
                ctx.execution_mode = ExecutionMode(nav_result.execution_mode)
            except ValueError:
                ctx.execution_mode = ExecutionMode.RETRIEVAL
            ctx.navigation_decision = nav_result
            ctx.retrieval_question = ctx.rewritten_question
            ctx.retrieval_sub_questions = ctx.rewrite_sub_questions
        else:
            ctx.execution_mode = ExecutionMode.RETRIEVAL
            ctx.retrieval_question = ctx.rewritten_question
            ctx.retrieval_sub_questions = ctx.rewrite_sub_questions

        return StageResult(signal=StageSignal.CONTINUE, context=ctx)
