from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import BusinessStatus
from app.infra.id_generator import next_id

if TYPE_CHECKING:
    from app.db.models.knowledge import KnowledgeScope, KnowledgeTopic

logger = structlog.get_logger(__name__)


async def list_scopes(db: AsyncSession) -> list[KnowledgeScope]:
    from app.db.models.knowledge import KnowledgeScope
    result = await db.execute(
        select(KnowledgeScope)
        .where(KnowledgeScope.status == BusinessStatus.YES.value)
        .order_by(KnowledgeScope.created_at.asc())
    )
    return list(result.scalars().all())


async def save_scope(
    db: AsyncSession,
    scope_code: str,
    scope_name: str,
    description: str = "",
    parent_scope_code: str = "",
    aliases: str = "",
    examples: str = "",
    sort_order: int = 0,
) -> dict:
    from app.db.models.knowledge import KnowledgeScope
    stmt = select(KnowledgeScope).where(
        KnowledgeScope.scope_code == scope_code,
        KnowledgeScope.status == BusinessStatus.YES.value,
    )
    scope = (await db.execute(stmt)).scalar_one_or_none()

    if scope:
        scope.scope_name = scope_name
        scope.description = description
        scope.parent_scope_code = parent_scope_code
        scope.aliases = aliases
        scope.examples = examples
        scope.sort_order = sort_order
    else:
        scope = KnowledgeScope(
            id=next_id(),
            scope_code=scope_code,
            scope_name=scope_name,
            description=description,
            parent_scope_code=parent_scope_code,
            aliases=aliases,
            examples=examples,
            sort_order=sort_order,
            status=BusinessStatus.YES.value,
        )
        db.add(scope)
    await db.commit()
    return {
        "id": str(scope.id),
        "scope_code": scope.scope_code,
        "scope_name": scope.scope_name,
    }


async def delete_scope(db: AsyncSession, scope_code: str) -> bool:
    from app.db.models.knowledge import KnowledgeScope
    result = await db.execute(
        update(KnowledgeScope)
        .where(
            KnowledgeScope.scope_code == scope_code,
            KnowledgeScope.status == BusinessStatus.YES.value,
        )
        .values(status=BusinessStatus.NO.value)
    )
    await db.commit()
    return result.rowcount > 0


async def save_topic(
    db: AsyncSession,
    scope_code: str,
    topic_code: str,
    topic_name: str,
    description: str = "",
    aliases: str = "",
    examples: str = "",
    answer_shape: str = "",
    execution_preference: str = "",
    sort_order: int = 0,
) -> dict:
    from app.db.models.knowledge import KnowledgeScope, KnowledgeTopic
    scope = (
        await db.execute(
            select(KnowledgeScope).where(
                KnowledgeScope.scope_code == scope_code,
                KnowledgeScope.status == BusinessStatus.YES.value,
            )
        )
    ).scalar_one_or_none()
    if not scope:
        raise ValueError(f"Knowledge scope not found: {scope_code}")

    stmt = select(KnowledgeTopic).where(
        KnowledgeTopic.topic_code == topic_code,
        KnowledgeTopic.status == BusinessStatus.YES.value,
    )
    topic = (await db.execute(stmt)).scalar_one_or_none()

    if topic:
        topic.topic_name = topic_name
        topic.scope_code = scope_code
        topic.description = description
        topic.aliases = aliases
        topic.examples = examples
        topic.answer_shape = answer_shape
        topic.execution_preference = execution_preference
        topic.sort_order = sort_order
    else:
        topic = KnowledgeTopic(
            id=next_id(),
            scope_code=scope_code,
            topic_code=topic_code,
            topic_name=topic_name,
            description=description,
            aliases=aliases,
            examples=examples,
            answer_shape=answer_shape,
            execution_preference=execution_preference,
            sort_order=sort_order,
            status=BusinessStatus.YES.value,
        )
        db.add(topic)
    await db.commit()
    return {
        "id": str(topic.id),
        "topic_code": topic.topic_code,
        "topic_name": topic.topic_name,
        "scope_code": scope_code,
    }


async def delete_topic(db: AsyncSession, topic_code: str) -> bool:
    from app.db.models.knowledge import KnowledgeTopic
    result = await db.execute(
        update(KnowledgeTopic)
        .where(
            KnowledgeTopic.topic_code == topic_code,
            KnowledgeTopic.status == BusinessStatus.YES.value,
        )
        .values(status=BusinessStatus.NO.value)
    )
    await db.commit()
    return result.rowcount > 0


async def bind_topic_to_scope(db: AsyncSession, scope_code: str, topic_code: str) -> bool:
    from app.db.models.knowledge import KnowledgeScope, KnowledgeTopic
    scope = (
        await db.execute(
            select(KnowledgeScope).where(
                KnowledgeScope.scope_code == scope_code,
                KnowledgeScope.status == BusinessStatus.YES.value,
            )
        )
    ).scalar_one_or_none()
    if not scope:
        return False
    topic = (
        await db.execute(
            select(KnowledgeTopic).where(
                KnowledgeTopic.topic_code == topic_code,
                KnowledgeTopic.status == BusinessStatus.YES.value,
            )
        )
    ).scalar_one_or_none()
    if not topic:
        return False
    topic.scope_code = scope_code
    await db.commit()
    return True


async def list_topics(db: AsyncSession, scope_code: str = "") -> list[KnowledgeTopic]:
    from app.db.models.knowledge import KnowledgeTopic
    query = select(KnowledgeTopic).where(KnowledgeTopic.status == BusinessStatus.YES.value)
    if scope_code:
        query = query.where(KnowledgeTopic.scope_code == scope_code)
    query = query.order_by(KnowledgeTopic.sort_order.asc(), KnowledgeTopic.id.asc())
    items = (await db.execute(query)).scalars().all()
    return list(items)


async def list_topic_documents(db: AsyncSession, topic_code: str) -> list[dict]:
    from app.db.models.document import Document
    from app.db.models.knowledge import TopicDocumentRelation

    query = (
        select(TopicDocumentRelation, Document)
        .join(Document, Document.id == TopicDocumentRelation.document_id)
        .where(
            TopicDocumentRelation.topic_code == topic_code,
            TopicDocumentRelation.status == BusinessStatus.YES.value,
        )
    )
    result = await db.execute(query.order_by(TopicDocumentRelation.relation_score.desc()))
    data = []
    for rel, doc in result:
        data.append(
            {
                "topic_code": rel.topic_code,
                "doc_id": doc.doc_id,
                "title": doc.document_name,
                "knowledge_scope_code": getattr(doc, "knowledge_scope_code", "") or "",
                "knowledge_scope_name": getattr(doc, "knowledge_scope_name", "") or "",
                "business_category": getattr(doc, "business_category", "") or "",
                "document_tags": getattr(doc, "document_tags", "") or "",
                "relation_score": str(rel.relation_score) if rel.relation_score else "0.0000",
                "relation_source": getattr(rel, "relation_source", "manual") or "manual",
                "reason": getattr(rel, "reason", "") or "",
            }
        )
    return data


async def save_topic_document(
    db: AsyncSession,
    topic_code: str,
    doc_id: str,
    relation_score: float = 0.0,
    relation_source: str = "manual",
    reason: str = "",
) -> dict:
    from app.db.models.document import Document
    from app.db.models.knowledge import KnowledgeTopic, TopicDocumentRelation

    topic = (
        await db.execute(
            select(KnowledgeTopic).where(
                KnowledgeTopic.topic_code == topic_code,
                KnowledgeTopic.status == BusinessStatus.YES.value,
            )
        )
    ).scalar_one_or_none()
    doc = (await db.execute(select(Document).where(Document.doc_id == doc_id))).scalar_one_or_none()

    if not topic or not doc:
        raise ValueError("Topic or Document not found")

    stmt = select(TopicDocumentRelation).where(
        TopicDocumentRelation.topic_code == topic_code,
        TopicDocumentRelation.document_id == doc.id,
        TopicDocumentRelation.status == BusinessStatus.YES.value,
    )
    rel = (await db.execute(stmt)).scalar_one_or_none()
    if not rel:
        rel = TopicDocumentRelation(
            id=next_id(),
            topic_code=topic_code,
            document_id=doc.id,
            relation_score=relation_score,
            relation_source=relation_source,
            reason=reason,
            status=BusinessStatus.YES.value,
        )
        db.add(rel)
    else:
        rel.relation_score = relation_score
        rel.relation_source = relation_source
        rel.reason = reason
    await db.commit()
    return {
        "topic_code": topic_code,
        "docId": doc_id,
        "relation_score": str(relation_score),
        "relation_source": relation_source,
    }


async def remove_topic_document(db: AsyncSession, topic_code: str, doc_id: str) -> bool:
    from app.db.models.document import Document
    from app.db.models.knowledge import TopicDocumentRelation

    doc = (await db.execute(select(Document).where(Document.doc_id == doc_id))).scalar_one_or_none()
    if not doc:
        return False
    result = await db.execute(
        update(TopicDocumentRelation)
        .where(
            TopicDocumentRelation.topic_code == topic_code,
            TopicDocumentRelation.document_id == doc.id,
            TopicDocumentRelation.status == BusinessStatus.YES.value,
        )
        .values(status=BusinessStatus.NO.value)
    )
    await db.commit()
    return result.rowcount > 0

