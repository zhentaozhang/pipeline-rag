"""Stage 10/11 — 最终 ExecutionPlan 构建"""

from __future__ import annotations

from app.chat.schema import ExecutionPlan
from app.common.pipeline import Stage, StageResult, StageSignal
from app.orchestrator.context import PrepareContext
from app.orchestrator.plan_builder import PlanBuilder


class FinalPlanBuildingStage(Stage[PrepareContext, "ExecutionPlan"]):
    async def process(self, ctx: PrepareContext) -> StageResult[PrepareContext, ExecutionPlan]:
        plan = PlanBuilder.build_final_plan(ctx)
        return StageResult(signal=StageSignal.TERMINATE, plan=plan)
