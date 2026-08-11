"""Stage 7/11 — 查询改写"""

from __future__ import annotations

import structlog

from app.chat.schema import ExecutionPlan
from app.common.pipeline import Stage, StageResult, StageSignal
from app.common.text_utils import safe_text
from app.orchestrator.context import PrepareContext
from app.orchestrator.query_rewriter import ChatQueryRewriteService

logger = structlog.get_logger(__name__)


class QueryRewriteStage(Stage[PrepareContext, "ExecutionPlan"]):
    async def process(self, ctx: PrepareContext) -> StageResult[PrepareContext, ExecutionPlan]:
        rewrite_service = ChatQueryRewriteService()
        rewrite_result = await rewrite_service.rewrite(
            question=ctx.question,
            memory_ctx=ctx.memory_ctx,
            history_summary=ctx.history_summary,
        )
        if rewrite_result is None or not rewrite_result.needs_rewrite:
            # 问题无需改写：返回 SKIP 跳过本阶段（不更新上下文，继续下一 Stage）。
            # 下游对 ctx.rewritten_question 均有原问题兜底：
            #   plan_builder.py:20 `ctx.rewritten_question or ctx.question`
            #   navigation_analyzer first_non_blank(rewrote, original_question)
            #   route_service._build_routing_text 空 rewr 时回退 orig
            return StageResult(signal=StageSignal.SKIP)

        ctx.rewritten_question = (
            rewrite_result.rewritten
            if rewrite_result and rewrite_result.rewritten
            else safe_text(ctx.question)
        )
        sub_qs = (
            rewrite_result.sub_questions
            if rewrite_result and rewrite_result.sub_questions
            else None
        )
        ctx.rewrite_sub_questions = sub_qs if sub_qs else [ctx.rewritten_question]
        return StageResult(signal=StageSignal.CONTINUE, context=ctx)
