"""
PersistentConversationMemoryService — 统一记忆持久化服务

封装：记忆加载、异步摘要刷新、重建、查询、删除。
"""

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.memory import MemoryContext, create_memory_strategy
from app.db.models.conversation import ConversationMemory

logger = structlog.get_logger(__name__)


class PersistentConversationMemoryService:
    """统一记忆服务 — 封装策略模式提供的各操作"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._strategy = create_memory_strategy()

    async def load(self, conversation_id: str) -> MemoryContext:
        return await self._strategy.load(conversation_id, self.db)

    async def save(
        self, conversation_id: str, question: str, answer: str, exchange_id: int
    ) -> None:
        try:
            await self._strategy.save(
                conversation_id=conversation_id,
                question=question,
                answer=answer,
                db=self.db,
                exchange_id=exchange_id,
            )
        except Exception as e:
            logger.exception(
                "memory strategy save failed", conversation_id=conversation_id, error=str(e)
            )
            raise

    async def rebuild_summary(self, conversation_id: str) -> None:
        """触发全量摘要重建。
        delete existing summary, then refreshSummaryIfNecessary with null currentState"""
        await self.delete_memory(conversation_id)
        from app.chat.memory import SummaryCompressionStrategy

        strategy = create_memory_strategy("summary_compression")
        if isinstance(strategy, SummaryCompressionStrategy):
            await strategy.compress_history(conversation_id, self.db)

    async def get_summary(self, conversation_id: str) -> str:
        stmt = select(ConversationMemory).where(
            ConversationMemory.conversation_id == conversation_id
        )
        result = await self.db.execute(stmt)
        memory = result.scalar_one_or_none()
        return (memory.summary_text or "") if memory else ""

    async def delete_memory(self, conversation_id: str) -> None:
        await self.db.execute(
            delete(ConversationMemory).where(ConversationMemory.conversation_id == conversation_id)
        )
        await self.db.commit()
