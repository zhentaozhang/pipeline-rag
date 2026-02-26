"""
ChatCheckpointManager — 图检查点生命周期管理

职责：列举、创建、清理 LangGraph 检查点（checkpoint + checkpoint_blobs + checkpoint_writes 三表）
      以及自定义 graph_checkpoint + graph_thread 清理。
"""

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class ChatCheckpointManager:
    """图检查点管理器 — 清理与列举"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._keep_latest = settings.rag.checkpoint_keep_latest

    async def clear_thread(self, thread_id: str) -> int:
        """清理 graph_thread + graph_checkpoint"""
        try:
            from app.db.models.langgraph import GraphCheckpoint, GraphThread

            threads_result = await self.db.execute(
                select(GraphThread).where(GraphThread.thread_name == thread_id)
            )
            threads = threads_result.scalars().all()
            if not threads:
                return 0

            graph_thread_ids = [t.thread_id for t in threads]

            # 统计将要删除的检查点数
            count_result = await self.db.execute(
                select(func.count())
                .select_from(GraphCheckpoint)
                .where(GraphCheckpoint.thread_id.in_(graph_thread_ids))
            )
            checkpoint_count = count_result.scalar() or 0

            if checkpoint_count > 0:
                await self.db.execute(
                    delete(GraphCheckpoint).where(GraphCheckpoint.thread_id.in_(graph_thread_ids))
                )

            await self.db.execute(delete(GraphThread).where(GraphThread.thread_name == thread_id))
            await self.db.commit()
            logger.info(
                "clear_thread completed", thread_id=thread_id, removed_checkpoints=checkpoint_count
            )
            return checkpoint_count
        except Exception:
            await self.db.rollback()
            logger.warning("clear_thread failed", thread_id=thread_id, exc_info=True)
            return 0
