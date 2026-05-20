"""Stage 5/11 — OPEN_CHAT 早期短路（由 .when() 守卫，仅当 OPEN_CHAT 模式执行）"""

from __future__ import annotations

import structlog

from app.chat.schema import ExecutionPlan
from app.common.pipeline import Stage, StageResult, StageSignal
from app.orchestrator.context import PrepareContext
from app.orchestrator.plan_builder import PlanBuilder

logger = structlog.get_logger(__name__)


class OpenChatShortcutStage(Stage[PrepareContext, "ExecutionPlan"]):
    async def process(self, ctx: PrepareContext) -> StageResult[PrepareContext, ExecutionPlan]:
        logger.info("open_chat shortcut triggered", question=ctx.question[:80])
        plan = PlanBuilder.build_open_chat_plan(ctx)
        return StageResult(signal=StageSignal.TERMINATE, plan=plan)
