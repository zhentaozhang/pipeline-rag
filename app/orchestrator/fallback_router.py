from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

import structlog

from app.common.text_utils import safe_text
from app.config import get_settings

logger = structlog.get_logger(__name__)


class FallbackRouter:
    @staticmethod
    async def select_auto_candidates(route_decision, question: str, rewrite_question: str) -> list:
        if not route_decision or not route_decision.documents:
            return await FallbackRouter.fallback_documents(question, rewrite_question, 5)
        confidence = float(route_decision.confidence) if route_decision.confidence else 0.0
        candidate_limit = 3 if confidence >= 0.80 else 5
        candidates = [
            d for d in route_decision.documents if d.document_id and d.last_index_task_id
        ][:candidate_limit]
        if not candidates:
            return await FallbackRouter.fallback_documents(
                question, rewrite_question, candidate_limit
            )
        settings = get_settings()
        if confidence < settings.rag.knowledge_route_confidence_threshold:
            fallback = await FallbackRouter.fallback_documents(
                question, rewrite_question, candidate_limit
            )
            return FallbackRouter.merge_candidates(candidates, fallback, candidate_limit)
        return candidates

    @staticmethod
    async def fallback_documents(question: str, rewrite_question: str, limit: int) -> list:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.common.enums import DocumentIndexStatusEnum
        from app.db.models.document import Document
        from app.db.session import get_engine
        from app.orchestrator.models import DocumentRouteCandidate

        async with AsyncSession(get_engine()) as session:
            result = await session.execute(
                select(Document).where(
                    Document.index_status == DocumentIndexStatusEnum.BUILD_SUCCESS.value,
                )
            )
            descriptors = result.scalars().all()

        if not descriptors:
            return []

        query_terms = FallbackRouter.extract_fallback_terms(question, rewrite_question)
        scored = []
        for d in descriptors:
            score = FallbackRouter.fallback_descriptor_score(d, query_terms)
            scored.append((score, d))

        scored.sort(key=lambda x: x[0], reverse=True)
        min_score = 1.0
        filtered = [(s, d) for s, d in scored if s >= min_score]
        if not filtered:
            return []
        limit = max(1, limit)
        return [
            DocumentRouteCandidate(
                document_id=str(d.id),
                document_name=d.document_name or "",
                last_index_task_id=str(d.last_index_task_id) if d.last_index_task_id else "",
                scope_code=d.knowledge_scope_code or "",
                scope_name=d.knowledge_scope_name or "",
                business_category=d.business_category or "",
                document_tags=d.document_tags or "",
                score=Decimal(str(round(score, 4))),
                reason="低置信度时基于文档元数据进行保守扩范围候选",
            )
            for score, d in filtered[:limit]
        ]

    @staticmethod
    def merge_candidates(primary: list, secondary: list, limit: int) -> list:
        merged = {}
        for c in primary:
            merged[c.document_id] = c
        for c in secondary:
            if c.document_id not in merged:
                merged[c.document_id] = c
        return list(merged.values())[: max(1, limit)]

    @staticmethod
    def extract_keywords_from_doc_name(doc_name: str) -> list[str]:
        name = doc_name.replace(".md", "").replace(".pdf", "")
        tokens = re.split(r"[/\\\s.\-–—:：,，、()（）\[\]【】]+", name)
        result = []
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            cjk = re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]", token)
            result.extend(cjk)
            eng = re.findall(r"[a-zA-Z]{3,}", token)
            result.extend(eng)
        return [k.lower() for k in result]

    @staticmethod
    def extract_fallback_terms(question: str, rewrite_question: str) -> list[str]:
        routing_text = f"{safe_text(question)} {safe_text(rewrite_question)}".strip()
        terms = []
        seen = set()
        for segment in re.split(r"[\s、，,；;：:（）()\-的和及与或]+", routing_text):
            trimmed = segment.strip()
            if len(trimmed) >= 2 and trimmed not in seen:
                seen.add(trimmed)
                terms.append(trimmed)
                if len(trimmed) >= 4:
                    max_gram = min(6, len(trimmed))
                    for gram in range(2, max_gram + 1):
                        for start in range(len(trimmed) - gram + 1):
                            g = trimmed[start : start + gram]
                            if g not in seen:
                                seen.add(g)
                                terms.append(g)
        return terms[:40]

    @staticmethod
    def fallback_descriptor_score(descriptor: Any, query_terms: list[str]) -> float:
        content = FallbackRouter.normalize_fallback_text(
            " ".join(
                [
                    safe_text(getattr(descriptor, "document_name", "")),
                    safe_text(getattr(descriptor, "knowledge_scope_code", "")),
                    safe_text(getattr(descriptor, "knowledge_scope_name", "")),
                    safe_text(getattr(descriptor, "business_category", "")),
                    safe_text(getattr(descriptor, "document_tags", "")),
                ]
            )
        )
        if not query_terms or not content:
            return 0.0
        sorted_terms = sorted(
            [FallbackRouter.normalize_fallback_text(t) for t in query_terms if t],
            key=len,
            reverse=True,
        )
        seen_terms: set[str] = set()
        unique: list[str] = []
        for t in sorted_terms:
            if t and t not in seen_terms:
                seen_terms.add(t)
                unique.append(t)
        sorted_terms = unique
        score = 0.0
        matched: list[str] = []
        for term in sorted_terms:
            if len(term) < 2:
                continue
            if any(existing.find(term) >= 0 for existing in matched):
                continue
            if term in content:
                matched.append(term)
                if len(term) >= 8:
                    score += 12.0
                elif len(term) >= 5:
                    score += 8.0
                elif len(term) >= 3:
                    score += 4.0
                else:
                    score += 2.0
        return score

    @staticmethod
    def normalize_fallback_text(value: str) -> str:
        return re.sub(r"[\s>`*#_\-，,。；;：:（）()" "''\[\]]+", "", value).lower()
