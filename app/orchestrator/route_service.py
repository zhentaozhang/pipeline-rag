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
        # 019 延迟优化 #2：路由决策缓存（同 question+rewrite+tenant 短 TTL 命中，省整个 1343ms）
        cached = await self._decision_cache_get(question, rewrite_question, tenant_id)
        if cached is not None:
            return cached

        ctx = await self.repo.build_query_context(question, rewrite_question, self.scorer.tokenize)
        if not ctx.query_terms:
            return KnowledgeRouteDecision(route_status="FAILED")

        async with AsyncSession(get_engine()) as session:
            scopes = await self.repo.get_ranked_scopes(session, ctx, self.scorer, tenant_id)
            topics = await self.repo.get_ranked_topics(session, ctx, scopes, self.scorer, tenant_id)
            docs = await self.repo.get_ranked_documents(
                session, ctx, scopes, topics, self.scorer, tenant_id
            )

        decision = self.scorer.build_decision(scopes, topics, docs)
        await self._decision_cache_set(question, rewrite_question, tenant_id, decision)
        return decision

    async def _decision_cache_key(
        self, question: str, rewrite_question: str, tenant_id: str
    ) -> str:
        import hashlib

        raw = f"{question}|{rewrite_question}|{tenant_id}"
        return "pipeline_rag:route_decision:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()

    async def _decision_cache_get(
        self, question: str, rewrite_question: str, tenant_id: str
    ) -> KnowledgeRouteDecision | None:
        try:

            import json

            from app.infra.redis_lease import get_redis

            redis = get_redis()
            raw = await redis.get(await self._decision_cache_key(question, rewrite_question, tenant_id))
            if not raw:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = json.loads(raw)
            from app.orchestrator.models import (
                DocumentRouteCandidate,
                KnowledgeRouteDecision,
                ScopeRouteCandidate,
                TopicRouteCandidate,
            )

            return KnowledgeRouteDecision(
                scopes=[ScopeRouteCandidate(**s) for s in data.get("scopes", [])],
                topics=[TopicRouteCandidate(**t) for t in data.get("topics", [])],
                documents=[DocumentRouteCandidate(**d) for d in data.get("documents", [])],
                confidence=data.get("confidence", "0.0"),
                route_status=data.get("route_status", "FAILED"),
                reason=data.get("reason", ""),
            )
        except Exception:
            return None

    async def _decision_cache_set(
        self,
        question: str,
        rewrite_question: str,
        tenant_id: str,
        decision: KnowledgeRouteDecision,
    ) -> None:
        try:
            import json
            from dataclasses import asdict

            from app.infra.redis_lease import get_redis

            redis = get_redis()
            payload = {
                "scopes": [asdict(s) for s in decision.scopes],
                "topics": [asdict(t) for t in decision.topics],
                "documents": [asdict(d) for d in decision.documents],
                "confidence": str(decision.confidence),
                "route_status": decision.route_status,
                "reason": decision.reason,
            }
            await redis.set(
                await self._decision_cache_key(question, rewrite_question, tenant_id),
                json.dumps(payload, ensure_ascii=False, default=str),
                ex=300,
            )
        except Exception:
            pass

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
