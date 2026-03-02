"""Stage 2/11 — 时间感知查询检测"""

from __future__ import annotations

from datetime import date

from app.chat.schema import ExecutionPlan
from app.common.pipeline import Stage, StageResult, StageSignal
from app.orchestrator.context import PrepareContext
from app.orchestrator.time_helper import TimeSensitiveQueryHelper


class TimeSensitivityStage(Stage[PrepareContext, "ExecutionPlan"]):

    async def process(self, ctx: PrepareContext) -> StageResult[PrepareContext, ExecutionPlan]:
        ctx.requires_current_date_anchoring = (
            TimeSensitiveQueryHelper.requires_current_date_anchoring(ctx.question)
        )
        ctx.requires_fresh_search = TimeSensitiveQueryHelper.requires_fresh_search(ctx.question)
        ctx.question = TimeSensitiveQueryHelper.enrich(ctx.question)
        ctx.current_date = date.today()
        ctx.current_date_text = TimeSensitiveQueryHelper.get_current_time_context()
        ctx.is_time_sensitive = TimeSensitiveQueryHelper.is_time_sensitive(ctx.question)
        return StageResult(signal=StageSignal.CONTINUE, context=ctx)
