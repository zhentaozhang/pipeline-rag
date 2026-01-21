from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge import KnowledgeScope, TopicDocumentRelation


class KnowledgeRepository:
    @staticmethod
    async def get_scope_by_code(db: AsyncSession, scope_code: str) -> KnowledgeScope | None:
        return await db.scalar(select(KnowledgeScope).where(KnowledgeScope.scope_code == scope_code))

    @staticmethod
    async def delete_topic_relations_by_doc_id(db: AsyncSession, doc_internal_id: int) -> None:
        await db.execute(
            delete(TopicDocumentRelation).where(
                TopicDocumentRelation.document_id == doc_internal_id
            )
        )
