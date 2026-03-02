from __future__ import annotations

import json

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.routing import KnowledgeRouteTrace
from app.db.session import get_engine
from app.infra.id_generator import next_id_int
from app.orchestrator.models import (
    KnowledgeRouteDecision,
    ScopeRouteCandidate,
    TopicRouteCandidate,
)

logger = structlog.get_logger(__name__)

ROUTE_STATUS_SUCCESS = 1
ROUTE_STATUS_LOW_CONFIDENCE = 2
ROUTE_STATUS_FAILED = 3


class RouteTraceStore:
    async def save_trace(
        self,
        conversation_id: str,
        exchange_id: int,
        selected_document_id: int | None,
        question: str,
        rewrite_question: str,
        mode: str,
        decision: KnowledgeRouteDecision,
    ) -> None:
        trace = KnowledgeRouteTrace(
            id=next_id_int(),
            conversation_id=conversation_id,
            exchange_id=exchange_id,
            question=question,
            rewrite_question=rewrite_question,
            mode=mode,
            top_scopes_json=self._write_scope_json(decision.scopes if decision else []),
            top_topics_json=self._write_topic_json(decision.topics if decision else []),
            top_documents_json=self._write_document_json(decision.documents if decision else []),
            selected_document_id=selected_document_id,
            hit_selected_document=self._resolve_hit_selected_document(
                selected_document_id, decision
            ),
            confidence=float(decision.confidence) if decision else 0.0,
            route_status=self._resolve_route_status(decision),
            error_msg=decision.reason if decision else "",
            status=1,
        )
        async with AsyncSession(get_engine()) as session:
            session.add(trace)
            await session.commit()

    def _write_scope_json(self, candidates: list[ScopeRouteCandidate]) -> str:
        return json.dumps(
            [
                {
                    "scopeCode": c.scope_code,
                    "scopeName": c.scope_name,
                    "score": str(c.score),
                    "reason": c.reason,
                }
                for c in candidates
            ],
            ensure_ascii=False,
        )

    def _write_topic_json(self, candidates: list[TopicRouteCandidate]) -> str:
        return json.dumps(
            [
                {
                    "topicCode": c.topic_code,
                    "topicName": c.topic_name,
                    "scopeCode": c.scope_code,
                    "score": str(c.score),
                    "reason": c.reason,
                }
                for c in candidates
            ],
            ensure_ascii=False,
        )

    def _write_document_json(self, candidates: list) -> str:
        return json.dumps(
            [
                {
                    "documentId": c.document_id,
                    "documentName": c.document_name,
                    "score": str(c.score),
                    "reason": c.reason,
                }
                for c in candidates
            ],
            ensure_ascii=False,
        )

    def _resolve_route_status(self, decision: KnowledgeRouteDecision) -> int:
        if not decision:
            return ROUTE_STATUS_FAILED
        if decision.route_status == "SUCCESS":
            return ROUTE_STATUS_SUCCESS
        if decision.route_status == "LOW_CONFIDENCE":
            return ROUTE_STATUS_LOW_CONFIDENCE
        return ROUTE_STATUS_FAILED

    def _resolve_hit_selected_document(
        self, selected_document_id: int | None, decision: KnowledgeRouteDecision
    ) -> int | None:
        if not selected_document_id or not decision or not decision.documents:
            return None
        hit = any(str(selected_document_id) == d.document_id for d in decision.documents[:3])
        return 1 if hit else 0
