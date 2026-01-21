from __future__ import annotations

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.rag_observability import (
    ConversationChannelExecution,
    ConversationRetrievalResult,
    RagEvaluationDataset,
)


class ObservabilityRepository:
    @staticmethod
    async def get_channel_executions(
        db: AsyncSession, conversation_id: str, exchange_id: int
    ) -> list:
        stmt = select(ConversationChannelExecution).where(
            ConversationChannelExecution.conversation_id == conversation_id,
            ConversationChannelExecution.exchange_id == exchange_id,
        )
        return (await db.execute(stmt)).scalars().all()

    @staticmethod
    async def get_retrieval_results(
        db: AsyncSession, conversation_id: str, exchange_id: int
    ) -> list:
        stmt = (
            select(ConversationRetrievalResult)
            .where(
                ConversationRetrievalResult.conversation_id == conversation_id,
                ConversationRetrievalResult.exchange_id == exchange_id,
            )
            .order_by(ConversationRetrievalResult.rank)
        )
        return (await db.execute(stmt)).scalars().all()

    @staticmethod
    async def get_evaluation_page(
        db: AsyncSession, page_no: int, page_size: int
    ) -> tuple[list, int]:
        total = await db.scalar(select(func.count()).select_from(RagEvaluationDataset))
        stmt = (
            select(RagEvaluationDataset)
            .order_by(RagEvaluationDataset.id.desc())
            .offset((page_no - 1) * page_size)
            .limit(page_size)
        )
        return (await db.execute(stmt)).scalars().all(), total or 0

    @staticmethod
    async def run_evaluation(
        db: AsyncSession, dataset_ids: list[int] | None = None
    ) -> list:
        stmt = select(RagEvaluationDataset)
        if dataset_ids:
            stmt = stmt.where(RagEvaluationDataset.id.in_(dataset_ids))
        else:
            stmt = stmt.where(RagEvaluationDataset.status == 1)

        records = (await db.execute(stmt)).scalars().all()
        for r in records:
            r.status = 3
        await db.commit()
        return records

    @staticmethod
    async def delete_evaluation(db: AsyncSession, dataset_id: int) -> None:
        stmt = sql_delete(RagEvaluationDataset).where(RagEvaluationDataset.id == dataset_id)
        await db.execute(stmt)
        await db.commit()
