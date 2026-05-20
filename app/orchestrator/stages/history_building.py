"""Stage 1/11 — 历史上下文构建"""

from __future__ import annotations

import structlog

from app.chat.schema import ExecutionPlan
from app.common.pipeline import Stage, StageResult, StageSignal
from app.orchestrator.context import PrepareContext
from app.orchestrator.history_builder import HistoryBuilder

logger = structlog.get_logger(__name__)


class HistoryBuildingStage(Stage[PrepareContext, "ExecutionPlan"]):
    async def process(self, ctx: PrepareContext) -> StageResult[PrepareContext, ExecutionPlan]:
        ctx.history_planning_ctx = HistoryBuilder.build_planning_context(ctx.memory_ctx)
        ctx.history_summary = HistoryBuilder.build_planning_history(
            ctx.memory_ctx, ctx.history_planning_ctx
        )
        ctx.answer_history_ctx = HistoryBuilder.build_answer_context(
            ctx.question,
            getattr(ctx.memory_ctx, "answer_recent_transcript", ""),
        )
        return StageResult(signal=StageSignal.CONTINUE, context=ctx)
