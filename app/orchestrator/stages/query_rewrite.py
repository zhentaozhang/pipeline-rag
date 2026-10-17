"""Stage 6 — 查询改写 + 意图分流（合并原 IntentClassifyStage）

职责：
1. 意图分流（原 IntentClassifyStage）：AUTO_DOCUMENT 模式下开放提问 → REACT_AGENT。
   - 规则快速路径零 LLM：looks_like_open_chat_question 命中即分流
   - LLM 路径：改写请求同时输出 intent，intent=open 时分流
2. 查询改写：指代消解 + 子问题拆分（复用 ChatQueryRewriteService）
"""

from __future__ import annotations

import structlog

from app.chat.schema import ExecutionPlan
from app.common.enums import ChatQueryMode
from app.common.pipeline import Stage, StageResult, StageSignal
from app.common.text_utils import safe_text
from app.orchestrator.context import PrepareContext
from app.orchestrator.plan_builder import PlanBuilder
from app.orchestrator.query_rewriter import ChatQueryRewriteService

logger = structlog.get_logger(__name__)


class QueryRewriteStage(Stage[PrepareContext, "ExecutionPlan"]):
    async def process(self, ctx: PrepareContext) -> StageResult[PrepareContext, ExecutionPlan]:
        # ── P0-1b 意图分流 · 规则快速路径（0ms）───────────────────────────
        if ctx.chat_mode == ChatQueryMode.AUTO_DOCUMENT:
            from app.orchestrator.intent_detector import (
                looks_like_capability_question,
                looks_like_open_chat_question,
            )

            # 快路径：规则特征命中（0ms）
            if looks_like_capability_question(ctx.question) or looks_like_open_chat_question(
                ctx.question, ctx.requires_fresh_search
            ):
                logger.info(
                    "intent rule-redirected to open_chat",
                    question=ctx.question[:80],
                    path="rule_fast_path",
                )
                plan = PlanBuilder.build_open_chat_plan(ctx)
                return StageResult(signal=StageSignal.TERMINATE, plan=plan)

        # ── 查询改写与语义意图判定（统一由 ChatQueryRewriteService 完成）───────
        rewrite_service = ChatQueryRewriteService()
        rewrite_result = await rewrite_service.rewrite(
            question=ctx.question,
            memory_ctx=ctx.memory_ctx,
            history_summary=ctx.history_summary,
        )

        # ── P0-1b 意图分流 · LLM/JEV 判定路径（无论是否改写，均优先检查是否命中开放意图）──────────
        if (
            ctx.chat_mode == ChatQueryMode.AUTO_DOCUMENT
            and rewrite_result
            and rewrite_result.intent in ("open", "capability")
        ):
            logger.info(
                "intent redirected to open_chat",
                question=ctx.question[:80],
                intent=rewrite_result.intent,
                path="rewrite_intent_open",
            )
            plan = PlanBuilder.build_open_chat_plan(ctx)
            return StageResult(signal=StageSignal.TERMINATE, plan=plan)

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
