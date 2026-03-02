"""Stage 3/11 — 企业意图护栏拦截"""

from __future__ import annotations

import structlog

from app.chat.schema import ExecutionPlan
from app.common.pipeline import Stage, StageResult, StageSignal
from app.orchestrator.context import PrepareContext
from app.orchestrator.guardrails import IntentGuardrailService
from app.orchestrator.plan_builder import PlanBuilder

logger = structlog.get_logger(__name__)


class GuardrailStage(Stage[PrepareContext, "ExecutionPlan"]):

    async def process(self, ctx: PrepareContext) -> StageResult[PrepareContext, ExecutionPlan]:
        guardrail = IntentGuardrailService()
        is_safe, block_reason = await guardrail.evaluate(ctx.question)
        if not is_safe:
            logger.info("guardrail blocked", question=ctx.question[:80], reason=block_reason)
            plan = PlanBuilder.build_refusal_plan(ctx, block_reason)
            return StageResult(signal=StageSignal.TERMINATE, plan=plan)
        return StageResult(signal=StageSignal.CONTINUE, context=ctx)
