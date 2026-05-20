"""Stage 8/11 — 知识路由（由 .when() 守卫，仅当 AUTO_DOCUMENT / DOCUMENT 模式执行）

AUTO_DOCUMENT 模式做完整路由（含澄清决策），DOCUMENT 模式只做影子路由记录。
可能 TERMINATE → CLARIFICATION 计划。
"""

from __future__ import annotations

import structlog

from app.chat.schema import ExecutionPlan
from app.common.enums import ChatQueryMode, ExecutionMode
from app.common.pipeline import Stage, StageResult, StageSignal
from app.common.utils import safe_int
from app.config import get_settings
from app.orchestrator.context import PrepareContext
from app.orchestrator.fallback_router import FallbackRouter
from app.orchestrator.plan_builder import PlanBuilder
from app.orchestrator.route_service import KnowledgeRouteService

logger = structlog.get_logger(__name__)


class KnowledgeRoutingStage(Stage[PrepareContext, ExecutionPlan]):
    async def process(self, ctx: PrepareContext) -> StageResult[PrepareContext, ExecutionPlan]:
        settings = get_settings()
        is_auto_doc = ctx.chat_mode == ChatQueryMode.AUTO_DOCUMENT
        is_doc_mode = ctx.chat_mode == ChatQueryMode.DOCUMENT

        route_svc = KnowledgeRouteService()
        routed_document_id: str | None = (
            ctx.original_doc_ids[0] if ctx.original_doc_ids else ctx.original_selected_document_id
        )

        if is_auto_doc:
            plan = await self._handle_auto_doc_route(ctx, route_svc, settings)
            if plan is not None:
                return StageResult(signal=StageSignal.TERMINATE, plan=plan)
        elif is_doc_mode:
            await self._record_shadow_route(ctx, route_svc, routed_document_id)

        return StageResult(signal=StageSignal.CONTINUE, context=ctx)

    async def _handle_auto_doc_route(
        self,
        ctx: PrepareContext,
        route_svc: KnowledgeRouteService,
        settings,
    ) -> ExecutionPlan | None:
        route_decision = await route_svc.route(ctx.question, ctx.rewritten_question, ctx.tenant_id)
        await route_svc.record_auto_route(
            ctx.conversation_id,
            ctx.exchange_id,
            ctx.question,
            ctx.rewritten_question,
            route_decision,
        )
        candidate_documents = await FallbackRouter.select_auto_candidates(
            route_decision, ctx.question, ctx.rewritten_question
        )

        if PlanBuilder.should_ask_clarification(
            route_decision,
            candidate_documents,
            settings.rag.knowledge_route_confidence_threshold,
            ctx.question,
        ):
            return ExecutionPlan(
                mode=ExecutionMode.CLARIFICATION,
                chat_mode=ChatQueryMode.AUTO_DOCUMENT,
                retrieval_document_ids=[c.document_id for c in candidate_documents],
                retrieval_task_ids=[
                    c.last_index_task_id for c in candidate_documents if c.last_index_task_id
                ],
                clarification_reply=PlanBuilder.build_clarification_reply(
                    ctx.question, route_decision, candidate_documents
                ),
                clarification_options=PlanBuilder.build_clarification_options(candidate_documents),
                clarification_reason=PlanBuilder.build_clarification_reason(
                    route_decision, candidate_documents
                ),
                no_evidence_reply=settings.rag.no_evidence_reply,
                **PlanBuilder.build_common_kwargs(ctx),
            )

        # Top doc selection → write to context
        ctx.top_doc_ids = [
            c.document_id
            for c in candidate_documents
            if c.document_id and str(c.document_id).strip()
        ]
        ctx.top_task_ids = [
            c.last_index_task_id
            for c in candidate_documents
            if c.last_index_task_id and str(c.last_index_task_id).strip()
        ]

        confidence = float(route_decision.confidence) if route_decision.confidence else 0.0
        confident_top_document = (
            confidence >= settings.rag.knowledge_route_confidence_threshold
            and bool(candidate_documents)
        )
        top_doc = candidate_documents[0] if confident_top_document else None
        if (
            top_doc
            and top_doc.document_id
            and top_doc.last_index_task_id
            and str(top_doc.document_id).strip()
            and str(top_doc.last_index_task_id).strip()
        ):
            ctx.routed_document_id = top_doc.document_id
            ctx.routed_document_name = top_doc.document_name
            ctx.routed_task_id = top_doc.last_index_task_id
        else:
            ctx.routed_document_id = None
            ctx.routed_document_name = ""
            ctx.routed_task_id = None

        return None

    async def _record_shadow_route(
        self,
        ctx: PrepareContext,
        route_svc: KnowledgeRouteService,
        routed_document_id: str | None,
    ) -> None:
        selected_id_int = safe_int(routed_document_id, default=None)
        await route_svc.record_shadow_route(
            ctx.conversation_id,
            ctx.exchange_id,
            selected_id_int,
            ctx.question,
            ctx.rewritten_question,
            ctx.tenant_id,
        )
