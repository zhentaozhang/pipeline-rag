from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_engine
from app.orchestrator.models import KnowledgeRouteDecision
from app.orchestrator.route_repository import RouteRepository
from app.orchestrator.route_scorer import RouteScorer
from app.orchestrator.route_trace_store import RouteTraceStore

logger = structlog.get_logger(__name__)


class KnowledgeRouteService:
    def __init__(self) -> None:
        self.scorer = RouteScorer()
        self.repo = RouteRepository()
        self.trace_store = RouteTraceStore()

    async def route(
        self, question: str, rewrite_question: str, tenant_id: str = "default"
    ) -> KnowledgeRouteDecision:
        ctx = await self.repo.build_query_context(question, rewrite_question, self.scorer.tokenize)
        if not ctx.query_terms:
            return KnowledgeRouteDecision(route_status="FAILED")

        async with AsyncSession(get_engine()) as session:
            scopes = await self.repo.get_ranked_scopes(session, ctx, self.scorer, tenant_id)
            topics = await self.repo.get_ranked_topics(session, ctx, scopes, self.scorer, tenant_id)
            docs = await self.repo.get_ranked_documents(
                session, ctx, scopes, topics, self.scorer, tenant_id
            )

        return self.scorer.build_decision(scopes, topics, docs)

    async def record_shadow_route(
        self,
        conversation_id: str,
        exchange_id: int,
        selected_document_id: int | None,
        question: str,
        rewrite_question: str,
        tenant_id: str = "default",
    ) -> None:
        try:
            decision = await self.route(question, rewrite_question, tenant_id)
            await self.trace_store.save_trace(
                conversation_id,
                exchange_id,
                selected_document_id,
                question,
                rewrite_question,
                "shadow",
                decision,
            )
        except Exception as e:
            logger.warning(
                "记录知识路由影子结果失败",
                conversation_id=conversation_id,
                exchange_id=exchange_id,
                error=str(e),
                exc_info=True,
            )

    async def record_auto_route(
        self,
        conversation_id: str,
        exchange_id: int,
        question: str,
        rewrite_question: str,
        decision: KnowledgeRouteDecision,
    ) -> None:
        try:
            top_doc = decision.top_document()
            selected_document_id = (
                int(top_doc.document_id) if top_doc and top_doc.document_id else None
            )
            await self.trace_store.save_trace(
                conversation_id,
                exchange_id,
                selected_document_id,
                question,
                rewrite_question,
                "auto",
                decision,
            )
        except Exception as e:
            logger.warning(
                "记录知识路由 AUTO 结果失败",
                conversation_id=conversation_id,
                exchange_id=exchange_id,
                error=str(e),
                exc_info=True,
            )
