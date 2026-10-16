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
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def get_retrieval_results(
        db: AsyncSession, conversation_id: str, exchange_id: int
    ) -> list:
        # 注意：该表没有名为 rank 的列，展示用排名由 final_rank → rrf_rank → channel_rank
        # 逐级回退得出（与 app/api/manage_observability.py 的 VO 组装逻辑保持一致）。
        # 早前直接 order_by(ConversationRetrievalResult.rank) 会抛 AttributeError。
        display_rank = func.coalesce(
            ConversationRetrievalResult.final_rank,
            ConversationRetrievalResult.rrf_rank,
            ConversationRetrievalResult.channel_rank,
            999,
        )
        stmt = (
            select(ConversationRetrievalResult)
            .where(
                ConversationRetrievalResult.conversation_id == conversation_id,
                ConversationRetrievalResult.exchange_id == exchange_id,
            )
            .order_by(display_rank)
        )
        return list((await db.execute(stmt)).scalars().all())

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
        return list((await db.execute(stmt)).scalars().all()), total or 0

    @staticmethod
    async def run_evaluation(db: AsyncSession, dataset_ids: list[int] | None = None) -> list:
        stmt = select(RagEvaluationDataset)
        if dataset_ids:
            stmt = stmt.where(RagEvaluationDataset.id.in_(dataset_ids))
        else:
            stmt = stmt.where(RagEvaluationDataset.status == 1)

        records = list((await db.execute(stmt)).scalars().all())
        for r in records:
            r.status = 3
        await db.commit()
        return records

    @staticmethod
    async def delete_evaluation(db: AsyncSession, dataset_id: int) -> None:
        stmt = sql_delete(RagEvaluationDataset).where(RagEvaluationDataset.id == dataset_id)
        await db.execute(stmt)
        await db.commit()
