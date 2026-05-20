"""Stage 6/11 — 意图分类（由 .when() 守卫，仅当 AUTO_DOCUMENT 模式执行）

用 LLM 识别开放性提问 → 分流到 REACT_AGENT。
"""

from __future__ import annotations

import structlog

from app.chat.schema import ExecutionPlan
from app.common.pipeline import Stage, StageResult, StageSignal
from app.orchestrator.classifier import IntentClassifier
from app.orchestrator.context import PrepareContext
from app.orchestrator.plan_builder import PlanBuilder

logger = structlog.get_logger(__name__)


class IntentClassifyStage(Stage[PrepareContext, "ExecutionPlan"]):
    async def process(self, ctx: PrepareContext) -> StageResult[PrepareContext, ExecutionPlan]:
        classifier = IntentClassifier()
        intent = await classifier.classify(ctx.question, ctx.memory_ctx)
        if intent == "open":
            logger.info(
                "intent classified as open, redirecting to open_chat",
                question=ctx.question[:80],
            )
            plan = PlanBuilder.build_open_chat_plan(ctx)
            return StageResult(signal=StageSignal.TERMINATE, plan=plan)
        elif intent == "ambiguous":
            logger.info(
                "intent ambiguous, fallback to knowledge routing", question=ctx.question[:80]
            )
        return StageResult(signal=StageSignal.CONTINUE, context=ctx)
