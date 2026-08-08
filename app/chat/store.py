"""
ConversationArchiveStore — 对话归档存储抽象层

职责：封装 Exchange/Session 的所有 DB 操作，服务层不再直接操作 DB。
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import asc, delete, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.task_info import ChatRuntimeRegistry
from app.db.models.conversation import ConversationExchange, ConversationMemory, ConversationSession
from app.infra.id_generator import next_id_int


class ConversationArchiveStore:
    """对话归档存储：CRUD session、exchange 及关联清理"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Session ──────────────────────────────────────────────────────────

    async def find_or_create_session(
        self, conversation_id: str, title: str
    ) -> tuple[ConversationSession, bool]:
        stmt = select(ConversationSession).where(
            ConversationSession.conversation_id == conversation_id
        )
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()
        created = False
        if not session:
            session = ConversationSession(
                id=next_id_int(),
                conversation_id=conversation_id,
                title=title[:50],
                created_at=datetime.now(),
            )
            self.db.add(session)
            await self.db.flush()
            created = True
        return session, created

    async def get_session(self, conversation_id: str) -> ConversationSession | None:
        stmt = select(ConversationSession).where(
            ConversationSession.conversation_id == conversation_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_session_title(self, conversation_id: str, title: str) -> None:
        await self.db.execute(
            update(ConversationSession)
            .where(ConversationSession.conversation_id == conversation_id)
            .values(title=title[:256], updated_at=func.now())
        )
        await self.db.commit()

    async def list_sessions(
        self,
        page: int = 1,
        size: int = 20,
        keyword: str | None = None,
        chat_mode: str | None = None,
        turn_status: int | None = None,
    ) -> tuple[list[ConversationSession], int]:
        from sqlalchemy import and_, exists, or_

        from app.db.models.conversation import ConversationExchange as CE

        base = select(ConversationSession)
        count_base = select(func.count(func.distinct(ConversationSession.id))).select_from(
            ConversationSession
        )

        # 软删除过滤：只返回未删除的会话
        base = base.where(~ConversationSession.is_deleted)
        count_base = count_base.where(~ConversationSession.is_deleted)

        # apply session page filters:
        # keyword → conversationId OR selectedDocumentName OR EXISTS exchange content
        if keyword:
            pattern = f"%{keyword}%"
            exchange_content_exists = exists(
                select(CE.id).where(
                    CE.conversation_id == ConversationSession.conversation_id,
                    or_(
                        CE.question.ilike(pattern),
                        CE.answer.ilike(pattern),
                    ),
                )
            )
            base = base.where(
                or_(
                    ConversationSession.conversation_id.ilike(f"%{keyword}%"),
                    ConversationSession.title.ilike(pattern),
                    exchange_content_exists,
                )
            )
            count_base = count_base.where(
                or_(
                    ConversationSession.conversation_id.ilike(f"%{keyword}%"),
                    ConversationSession.title.ilike(pattern),
                    exchange_content_exists,
                )
            )

        # chatMode filter uses session.chat_mode, turnStatus uses exchange.turn_status
        if chat_mode and chat_mode.upper() != "ALL":
            base = base.where(ConversationSession.chat_mode == chat_mode)
            count_base = count_base.where(ConversationSession.chat_mode == chat_mode)
        if turn_status is not None:
            exchange_filter = and_(
                CE.conversation_id == ConversationSession.conversation_id,
                CE.turn_status == turn_status,
            )
            exchange_exists = exists(select(CE.id).where(exchange_filter))
            base = base.where(exchange_exists)
            count_base = count_base.where(exchange_exists)

        total = await self.db.scalar(count_base)

        # 排序：置顶优先 → pinned_at → updated_at → id
        stmt = (
            base.order_by(
                desc(ConversationSession.is_pinned),
                desc(ConversationSession.pinned_at),
                desc(ConversationSession.updated_at),
                desc(ConversationSession.id),
            )
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        return list(rows), total or 0

    async def delete_session_cascade(self, conversation_id: str) -> None:
        await self.db.execute(
            delete(ConversationExchange).where(
                ConversationExchange.conversation_id == conversation_id
            )
        )
        await self.db.execute(
            delete(ConversationMemory).where(ConversationMemory.conversation_id == conversation_id)
        )
        await self.db.execute(
            delete(ConversationSession).where(
                ConversationSession.conversation_id == conversation_id
            )
        )
        await self.db.commit()

    # ── Exchange ─────────────────────────────────────────────────────────

    async def start_exchange(
        self,
        exchange_id: int,
        conversation_id: str,
        session_id: int,
        question: str,
        execution_mode: str = "unknown",
    ) -> None:
        exchange = ConversationExchange(
            id=exchange_id,
            conversation_id=conversation_id,
            question=question,
            answer="",
            execution_mode=execution_mode or None,
        )
        self.db.add(exchange)
        await self.db.commit()

    async def complete_exchange(
        self,
        exchange_id: int,
        conversation_id: str,
        answer: str,
        tokens_used: int | None = None,
        turn_status: int = 2,
        first_response_time_ms: int | None = None,
        total_response_time_ms: int | None = None,
        references: list[dict] | None = None,
        recommendations: list[str] | None = None,
        thinking_steps: list[str] | None = None,
        used_tools: list[str] | None = None,
        debug_trace: dict | None = None,
        error_message: str = "",
    ) -> None:
        import json

        # verify exchange exists for this conversation_id
        from sqlalchemy import select as _select

        existing = await self.db.scalar(
            _select(ConversationExchange)
            .where(
                ConversationExchange.id == exchange_id,
                ConversationExchange.conversation_id == conversation_id,
            )
            .limit(1)
        )
        if not existing:
            return

        values: dict[str, Any] = {
            ConversationExchange.answer: answer,
            ConversationExchange.turn_status: turn_status,
            ConversationExchange.updated_at: func.now(),
        }
        if first_response_time_ms is not None:
            values[ConversationExchange.first_response_time_ms] = first_response_time_ms
        if total_response_time_ms is not None:
            values[ConversationExchange.total_response_time_ms] = total_response_time_ms
        if tokens_used is not None:
            values[ConversationExchange.tokens_used] = tokens_used
        if references is not None:
            values[ConversationExchange.references] = json.dumps(references, ensure_ascii=False)
        if recommendations is not None:
            values[ConversationExchange.recommendations] = json.dumps(
                recommendations, ensure_ascii=False
            )
        if thinking_steps:
            values[ConversationExchange.thinking_steps] = json.dumps(
                thinking_steps, ensure_ascii=False
            )
        if used_tools is not None:
            values[ConversationExchange.used_tools] = json.dumps(used_tools, ensure_ascii=False)
        if debug_trace is not None:
            values[ConversationExchange.debug_trace_json] = json.dumps(
                debug_trace, ensure_ascii=False, default=str
            )
            exec_mode = debug_trace.get("execution_mode") or debug_trace.get("executionMode")
            if exec_mode:
                values[ConversationExchange.execution_mode] = exec_mode
        if error_message:
            values[ConversationExchange.error_message] = error_message
        stmt = (
            update(ConversationExchange)
            .where(ConversationExchange.id == exchange_id)
            .values(values)
        )
        await self.db.execute(stmt)

        # update session after completing exchange
        await self.db.execute(
            update(ConversationSession)
            .where(ConversationSession.conversation_id == conversation_id)
            .values(updated_at=func.now())
        )
        await self.db.commit()

    async def get_exchange(self, exchange_id: int) -> ConversationExchange | None:
        from sqlalchemy import select

        stmt = select(ConversationExchange).where(ConversationExchange.id == exchange_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_exchanges(
        self,
        conversation_id: str,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[ConversationExchange], int]:
        count_stmt = (
            select(func.count())
            .select_from(ConversationExchange)
            .where(ConversationExchange.conversation_id == conversation_id)
        )
        total = (await self.db.execute(count_stmt)).scalar() or 0
        # ORDER BY created_at ASC, id ASC
        stmt = (
            select(ConversationExchange)
            .where(ConversationExchange.conversation_id == conversation_id)
            .order_by(asc(ConversationExchange.created_at), asc(ConversationExchange.id))
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    # ── 运行时合并 ────────────────────────────────────────────────────

    async def merge_runtime_exchange(self, conversation_id: str) -> dict | None:
        """
        如果当前 conversation 有正在运行的 task，构建一条"运行时 exchange" VO 合并到会话列表。
        返回 None 表示无运行中任务。
        """
        task = ChatRuntimeRegistry.get(conversation_id)
        if not task:
            return None
        elapsed = int((datetime.now(UTC) - task.start_time).total_seconds() * 1000)
        return {
            "id": task.exchange_id or 0,
            "conversation_id": conversation_id,
            "question": task.question,
            "answer": "".join(task.answer_buffer),
            "tokens_used": task.total_tokens,
            "created_at": task.start_time.isoformat() if task.start_time else None,
            "status": "running",
            "elapsed_ms": elapsed,
        }
