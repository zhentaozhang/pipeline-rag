from __future__ import annotations

import decimal
import json
from collections.abc import Callable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import BusinessStatus, DocumentIndexStatusEnum
from app.common.text_utils import first_non_blank
from app.db.models.document import Document, DocumentProfile
from app.db.models.knowledge import KnowledgeScope, KnowledgeTopic, TopicDocumentRelation
from app.infra.embedding import get_embedding_provider
from app.infra.route_indexer import DOCUMENT_ROUTE_INDEX, SCOPE_ROUTE_INDEX, TOPIC_ROUTE_INDEX
from app.orchestrator.models import (
    DocumentRouteCandidate,
    RouteQueryContext,
    ScopeRouteCandidate,
    TopicRouteCandidate,
)
from app.orchestrator.route_es_repository import RouteESRepository
from app.orchestrator.route_scorer import (
    DocumentRouteMaterial,
    RouteScorer,
    ScopeAccumulator,
    TopicAccumulator,
    _join,
    _normalize_code,
)

logger = structlog.get_logger(__name__)
ROUTE_EMBEDDING_BATCH_SIZE = 10


class RouteRepository:
    def __init__(self) -> None:
        self.embedding_provider = get_embedding_provider()
        self.es_repo = RouteESRepository()

    async def build_query_context(
        self,
        question: str,
        rewrite_question: str,
        tokenize_fn: Callable[[str], list[str]] | None = None,
    ) -> RouteQueryContext:
        routing_text = self._build_routing_text(question, rewrite_question)
        query_terms = tokenize_fn(routing_text) if tokenize_fn else []
        query_embedding: list[float] | None = None
        if routing_text:
            query_embedding = await self._embed_with_cache(routing_text)
        return RouteQueryContext(
            question=question or "",
            rewrite_question=rewrite_question or "",
            routing_text=routing_text,
            query_terms=query_terms,
            query_embedding=query_embedding,
        )

    async def _embed_with_cache(self, routing_text: str) -> list[float] | None:
        """路由 query 向量化（019 延迟优化 #1：Redis 哈希缓存，省 ~300-800ms/轮）"""
        import hashlib

        from app.infra.redis_lease import get_redis

        key = "pipeline_rag:route_embed:" + hashlib.sha1(routing_text.encode("utf-8")).hexdigest()
        try:
            redis = get_redis()
            cached = await redis.get(key)
            if cached:
                if isinstance(cached, bytes):
                    cached = cached.decode("utf-8")
                return [float(x) for x in cached.split(",")]
        except Exception:
            pass  # 缓存不可用时直接调 API

        try:
            embeddings = await self.embedding_provider.embed_batch([routing_text])
            query_embedding = embeddings[0] if embeddings else None
            if query_embedding:
                try:
                    redis = get_redis()
                    await redis.set(
                        key, ",".join(str(f) for f in query_embedding), ex=86400
                    )
                except Exception:
                    pass
            return query_embedding
        except Exception:
            logger.warning("Route embedding failed for text", exc_info=True)
            return None

    def _build_routing_text(self, question: str, rewrite_question: str) -> str:
        orig = (question or "").strip()
        rewr = (rewrite_question or "").strip()
        if not orig:
            return rewr
        if not rewr or orig == rewr:
            return orig
        return f"{orig} {rewr}"

    def _build_document_route_material(
        self, doc: Document, profile: DocumentProfile | None
    ) -> DocumentRouteMaterial:
        route_text = _join(
            doc.document_name,
            str(doc.knowledge_scope_code or ""),
            doc.document_tags,
            profile.document_summary if profile else "",
            profile.core_topics if profile else "",
            profile.example_questions if profile else "",
            profile.document_type if profile else "",
        )
        return DocumentRouteMaterial(doc.id, route_text)

    def _parse_json_array(self, raw: str) -> list[str]:
        if not raw or raw == "[]":
            return []
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                return [str(a).strip() for a in arr if str(a).strip()]
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse route JSON array", raw_preview=raw[:100], exc_info=True)
        return []

    async def list_retrievable_documents(
        self, session: AsyncSession, tenant_id: str = "default"
    ) -> list[Document]:
        result = await session.execute(
            select(Document)
            .where(
                Document.index_status == DocumentIndexStatusEnum.BUILD_SUCCESS.value,
                Document.tenant_id == tenant_id,
            )
            .order_by(Document.id)
        )
        return list(result.scalars().all())

    async def _compute_semantic_scores(
        self, ctx: RouteQueryContext, route_texts: list[str], scorer: RouteScorer
    ) -> list[float]:
        if not ctx.query_embedding or not route_texts:
            return [0.0] * len(route_texts)
        try:
            scores: list[float] = [0.0] * len(route_texts)
            for i in range(0, len(route_texts), ROUTE_EMBEDDING_BATCH_SIZE):
                batch = route_texts[i : i + ROUTE_EMBEDDING_BATCH_SIZE]
                embeddings = await self.embedding_provider.embed_batch(batch)
                for j, emb in enumerate(embeddings):
                    scores[i + j] = scorer.cosine_similarity(ctx.query_embedding, emb)
            return scores
        except Exception:
            logger.warning(
                "Batch embedding computation failed",
                batch_count=len(route_texts),
                exc_info=True,
            )
            return [0.0] * len(route_texts)

    async def get_ranked_scopes(
        self,
        session: AsyncSession,
        ctx: RouteQueryContext,
        scorer: RouteScorer,
        tenant_id: str = "default",
    ) -> list[ScopeRouteCandidate]:
        result = await session.execute(
            select(KnowledgeScope).where(KnowledgeScope.status == BusinessStatus.YES.value)
        )
        nodes = result.scalars().all()

        if not nodes:
            return await self._derive_scopes_from_documents(session, ctx, scorer, tenant_id)

        route_texts = [_join(n.scope_name, n.description) for n in nodes]
        semantic_scores = await self._compute_semantic_scores(ctx, route_texts, scorer)

        lexical_hits = await self.es_repo.search_lexical_scores(
            ctx.routing_text, SCOPE_ROUTE_INDEX, 5, entity_type="SCOPE"
        )
        lexical_scores = {h["entityCode"]: h["score"] for h in lexical_hits}

        candidates: list[ScopeRouteCandidate] = []
        for i, node in enumerate(nodes):
            route_text = route_texts[i]
            final_score = (
                scorer.semantic_main_score(semantic_scores[i])
                + scorer.lexical_assist(lexical_scores.get(node.scope_code))
                + scorer.keyword_entity_assist(ctx.query_terms, route_text)
            )

            if final_score > 0 or semantic_scores[i] > 0:
                candidates.append(
                    ScopeRouteCandidate(
                        scope_code=node.scope_code,
                        scope_name=node.scope_name,
                        score=scorer.to_decimal(final_score),
                        reason=scorer.build_reason(ctx.query_terms, route_text, semantic_scores[i]),
                    )
                )

        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates[:5]

    async def _derive_scopes_from_documents(
        self,
        session: AsyncSession,
        ctx: RouteQueryContext,
        scorer: RouteScorer,
        tenant_id: str = "default",
    ) -> list[ScopeRouteCandidate]:
        documents = await self.list_retrievable_documents(session, tenant_id)

        entries: list[tuple[object, str, str, str]] = []
        for doc in documents:
            code = first_non_blank(doc.knowledge_scope_code, "general_document")
            name = first_non_blank(doc.knowledge_scope_name, "通用文档")
            route_text = _join(str(code), name, doc.document_tags)
            entries.append((doc, code, name, route_text))

        route_texts = [e[3] for e in entries]
        semantic_scores = await self._compute_semantic_scores(ctx, route_texts, scorer)

        accumulator_map: dict[str, ScopeAccumulator] = {}
        for (_, code, name, route_text), semantic_score in zip(
            entries, semantic_scores, strict=False
        ):
            score = scorer.keyword_entity_assist(ctx.query_terms, route_text)
            acc = accumulator_map.setdefault(str(code), ScopeAccumulator(str(code), name))
            final_score = score + scorer.semantic_main_score(semantic_score)
            if final_score > acc.max_score:
                acc.max_score = final_score
                acc.reason = scorer.build_reason(ctx.query_terms, route_text, semantic_score)

        candidates = [
            ScopeRouteCandidate(
                a.scope_code, a.scope_name, scorer.to_decimal(a.max_score), a.reason
            )
            for a in accumulator_map.values()
            if a.max_score > 0 or ctx.query_embedding
        ]
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates[:5]

    async def get_ranked_topics(
        self,
        session: AsyncSession,
        ctx: RouteQueryContext,
        scope_candidates: list[ScopeRouteCandidate],
        scorer: RouteScorer,
        tenant_id: str = "default",
    ) -> list[TopicRouteCandidate]:
        preferred_scopes = {s.scope_code for s in scope_candidates}
        result = await session.execute(
            select(KnowledgeTopic).where(KnowledgeTopic.status == BusinessStatus.YES.value)
        )
        nodes = result.scalars().all()

        if not nodes:
            return await self._derive_topics_from_profiles(
                session, ctx, preferred_scopes, scorer, tenant_id
            )

        route_texts = [_join(n.topic_name) for n in nodes]
        semantic_scores = await self._compute_semantic_scores(ctx, route_texts, scorer)

        lexical_hits = await self.es_repo.search_lexical_scores(
            ctx.routing_text, TOPIC_ROUTE_INDEX, 8, entity_type="TOPIC"
        )
        lexical_scores = {h["entityCode"]: h["score"] for h in lexical_hits}

        candidates: list[TopicRouteCandidate] = []
        for i, node in enumerate(nodes):
            route_text = route_texts[i]
            score = (
                scorer.semantic_main_score(semantic_scores[i])
                + scorer.lexical_assist(lexical_scores.get(node.topic_code))
                + scorer.keyword_entity_assist(ctx.query_terms, route_text)
            )

            if preferred_scopes and node.scope_code and node.scope_code in preferred_scopes:
                score += 8.0

            if score > 0 or ctx.query_embedding:
                candidates.append(
                    TopicRouteCandidate(
                        topic_code=node.topic_code,
                        topic_name=node.topic_name,
                        scope_code=node.scope_code or "",
                        score=scorer.to_decimal(score),
                        reason=scorer.build_reason(ctx.query_terms, route_text, semantic_scores[i]),
                    )
                )

        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates[:8]

    async def _derive_topics_from_profiles(
        self,
        session: AsyncSession,
        ctx: RouteQueryContext,
        preferred_scopes: set[str],
        scorer: RouteScorer,
        tenant_id: str = "default",
    ) -> list[TopicRouteCandidate]:
        profiles_res = await session.execute(
            select(DocumentProfile).where(
                DocumentProfile.status == 1, DocumentProfile.profile_status == 2
            )
        )
        profiles = profiles_res.scalars().all()

        docs = await self.list_retrievable_documents(session, tenant_id=tenant_id)
        doc_map = {d.id: d for d in docs}

        entries: list[tuple[str, str, str, float]] = []
        for profile in profiles:
            doc = doc_map.get(profile.document_id)
            if not doc:
                continue
            scope_code = str(doc.knowledge_scope_code) if doc.knowledge_scope_code else ""
            for topic in self._parse_json_array(profile.core_topics):
                route_text = _join(topic, profile.document_summary, profile.example_questions)
                keyword_score = scorer.keyword_entity_assist(ctx.query_terms, route_text)
                entries.append((topic, scope_code, route_text, keyword_score))

        semantic_scores = await self._compute_semantic_scores(ctx, [e[2] for e in entries], scorer)

        accumulator_map: dict[str, TopicAccumulator] = {}
        for (topic, scope_code, route_text, keyword_score), semantic_score in zip(
            entries, semantic_scores, strict=False
        ):
            if preferred_scopes and scope_code in preferred_scopes:
                keyword_score += 6.0

            acc = accumulator_map.setdefault(topic, TopicAccumulator(topic, scope_code))
            final_score = keyword_score + scorer.semantic_main_score(semantic_score)
            if final_score > acc.max_score:
                acc.max_score = final_score
                acc.reason = scorer.build_reason(ctx.query_terms, route_text, semantic_score)

        candidates = [
            TopicRouteCandidate(
                _normalize_code(a.topic_name),
                a.topic_name,
                a.scope_code,
                scorer.to_decimal(a.max_score),
                a.reason,
            )
            for a in accumulator_map.values()
            if a.max_score > 0 or ctx.query_embedding
        ]
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates[:8]

    async def get_ranked_documents(
        self,
        session: AsyncSession,
        ctx: RouteQueryContext,
        scope_candidates: list[ScopeRouteCandidate],
        topic_candidates: list[TopicRouteCandidate],
        scorer: RouteScorer,
        tenant_id: str = "default",
    ) -> list[DocumentRouteCandidate]:
        documents = await self.list_retrievable_documents(session, tenant_id)
        if not documents:
            return await self.es_repo.fallback_es_documents(ctx, tenant_id)

        profiles_res = await session.execute(
            select(DocumentProfile).where(
                DocumentProfile.status == 1, DocumentProfile.profile_status == 2
            )
        )
        profile_map = {p.document_id: p for p in profiles_res.scalars().all()}

        relations_res = await session.execute(
            select(TopicDocumentRelation).where(TopicDocumentRelation.status == 1)
        )
        topic_relation_map: dict[str, dict[int, object]] = {}
        for r in relations_res.scalars().all():
            topic_relation_map.setdefault(r.topic_code, {})[r.document_id] = r

        top_scope_code = scope_candidates[0].scope_code if scope_candidates else ""
        top_topic_code = topic_candidates[0].topic_code if topic_candidates else ""

        materials = [
            self._build_document_route_material(doc, profile_map.get(doc.id)) for doc in documents
        ]
        route_texts = [m.route_text for m in materials]
        semantic_scores = await self._compute_semantic_scores(ctx, route_texts, scorer)

        lexical_hits = await self.es_repo.search_lexical_scores(
            ctx.routing_text, DOCUMENT_ROUTE_INDEX, 5, entity_type="DOCUMENT"
        )
        lexical_scores = {
            str(h["documentId"]): h["score"]
            for h in lexical_hits
            if h.get("documentId") is not None
        }

        candidates: list[DocumentRouteCandidate] = []
        for i, doc in enumerate(documents):
            route_text = route_texts[i]
            semantic_score = semantic_scores[i]
            score = (
                scorer.semantic_main_score(semantic_score)
                + scorer.lexical_assist(lexical_scores.get(str(doc.id)))
                + scorer.keyword_entity_assist(ctx.query_terms, route_text)
                + scorer.lexical_score(ctx.query_terms, route_text)
            )

            if top_scope_code and top_scope_code == str(doc.knowledge_scope_code):
                score += 15.0

            if top_topic_code:
                rel_map = topic_relation_map.get(top_topic_code)
                if rel_map and doc.id in rel_map:
                    rel_score = getattr(rel_map[doc.id], "relation_score", None)
                    if rel_score is not None:
                        score += float(rel_score) * 20.0

            task_id = str(doc.last_index_task_id) if doc.last_index_task_id else ""

            if score <= 0 and not ctx.query_embedding:
                candidates.append(
                    DocumentRouteCandidate(
                        document_id=str(doc.id),
                        document_name=doc.document_name,
                        last_index_task_id=task_id,
                        scope_code=str(doc.knowledge_scope_code or ""),
                        scope_name="",
                        business_category="",
                        document_tags=doc.document_tags or "",
                        score=decimal.Decimal("0.0"),
                        reason="未命中路由关键词",
                    )
                )
            else:
                candidates.append(
                    DocumentRouteCandidate(
                        document_id=str(doc.id),
                        document_name=doc.document_name,
                        last_index_task_id=task_id,
                        scope_code=str(doc.knowledge_scope_code or ""),
                        scope_name="",
                        business_category="",
                        document_tags=doc.document_tags or "",
                        score=scorer.to_decimal(score),
                        reason=scorer.build_reason(ctx.query_terms, route_text, semantic_score),
                    )
                )

        filtered = [c for c in candidates if c.score > 0 or ctx.query_embedding]
        filtered.sort(key=lambda x: x.score, reverse=True)
        result = filtered[:5]
        if not result:
            return await self.es_repo.fallback_es_documents(ctx, tenant_id)
        return result
