"""
BusinessChatService — 对话主服务
串联：记忆加载 → Orchestrator → ExecutorRegistry → 持久化

所有对话流式请求的唯一入口。
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date as date_type
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.schema import StreamLaunchPlan
from app.chat.service_executor import execute_stream
from app.chat.service_finalizer import finalize_stream, handle_cancelled_stream, handle_error_stream
from app.chat.service_utils import (
    StreamChunkTimeoutError,
    _async_generator_with_timeout,
    _format_current_date,
    _normalize_conversation_id,
    _normalize_question,
    _parse_required_chat_mode,
)
from app.chat.state_machine import ConversationState
from app.chat.task_info import ChatRuntimeRegistry, ChatTaskInfo
from app.common.sse import SSEEventType, sse_event
from app.config import get_settings
from app.eventbus.bus import bus
from app.eventbus.events import (
    ConversationStartedPayload,
    Event,
)
from app.infra.id_generator import next_id_int

if TYPE_CHECKING:
    from app.api.chat_stream import ChatRequest

logger = structlog.get_logger(__name__)
settings = get_settings()


@dataclass
class _StreamState:
    """流式执行的临时可变状态，封装 out-params 避免函数签名膨胀"""

    full_answer: list[str] = field(default_factory=list)
    collected_references: list[dict] = field(default_factory=list)
    collected_recommendations: list[str] = field(default_factory=list)
    turn_failed: bool = False
    turn_stopped: bool = False
    last_error_message: str = ""


class BusinessChatService:
    """
    对话主流程协调器。
    仅负责流程串联，具体业务下沉至各子服务。
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def stream(self, request: "ChatRequest") -> AsyncIterator[str]:
        """
        完整对话流程，生成 SSE 事件字符串序列。

        完整对话流程：
        buildLaunchPlan → claimLease → bootstrapConversation → createTaskInfo
        → bindClientChannel → activateGeneration → buildConversationExecution
        → executor.execute
        """
        from app.chat.memory_service import PersistentConversationMemoryService
        from app.chat.store import ConversationArchiveStore
        from app.infra.redis_lease import RedisLeaseManager

        # ── 初始化存储层 ──────────────────────────────────────────────────
        archive_store = ConversationArchiveStore(self.db)
        memory_service = PersistentConversationMemoryService(self.db)

        # ── 0. 参数规范化 ─────────────────────────────────────────────────
        question = _normalize_question(request.question)
        conversation_id = _normalize_conversation_id(request.conversation_id)

        # ── 1. 构建启动计划 StreamLaunchPlan ─────────────────────────────
        today = date_type.today()
        current_date_text = _format_current_date(today)

        chat_mode = _parse_required_chat_mode(request.chat_mode)
        launch_plan = StreamLaunchPlan(
            conversation_id=conversation_id,
            question=question,
            chat_mode=chat_mode,
            doc_ids=request.doc_ids,
            current_date=today.isoformat(),
            current_date_text=current_date_text,
        )

        # 2. 查找或创建 Session (为了获取 session_id)
        session, _ = await archive_store.find_or_create_session(conversation_id, question)

        # ── 3. 集群级 Redis 锁（先获取锁再注册任务）───────────────────────
        lease_mgr = RedisLeaseManager(conversation_id)
        acquired = await lease_mgr.acquire()
        if not acquired:
            yield sse_event(
                SSEEventType.ERROR,
                "该会话当前正在执行中，请稍后再试",
                conversation_id=conversation_id,
            )
            yield sse_event(SSEEventType.DONE, conversation_id=conversation_id)
            return

        # ── 4. 构建任务上下文 TaskInfo ─────────────────────────────────
        temp_exchange_id = next_id_int()
        task = ChatTaskInfo(
            conversation_id=conversation_id,
            question=question,
            chat_mode=request.chat_mode,
            current_date=today.isoformat(),
            current_date_text=current_date_text,
            plan=None,
        )
        if hasattr(request, "model_name"):
            task.model_name = request.model_name

        task.sm.transition(ConversationState.LOCK_ACQUIRED)

        # 填充租赁信息到启动计划 / 任务
        launch_plan.lease_key = lease_mgr.lock_name
        launch_plan.lease_owner_token = lease_mgr.lock_token
        task.lease_key = lease_mgr.lock_name
        task.lease_token = lease_mgr.lock_token

        # 初始化事件元数据
        from app.chat.support import StreamEventMetadata

        task.event_metadata = StreamEventMetadata(
            conversation_id=conversation_id,
            exchange_id=temp_exchange_id,
        )

        if not ChatRuntimeRegistry.register(task):
            ChatRuntimeRegistry.replace(task)
        task.sm.transition(ConversationState.REGISTERED)

        await bus.emit(
            Event(
                name="conversation.started",
                payload=ConversationStartedPayload(question=question, chat_mode=chat_mode),
                conversation_id=conversation_id,
                exchange_id=temp_exchange_id,
            )
        )

        state = _StreamState()

        try:
            timeout = settings.rag.stream_timeout_seconds
            async for event in _async_generator_with_timeout(
                execute_stream(
                    db=self.db,
                    task=task,
                    conversation_id=conversation_id,
                    temp_exchange_id=temp_exchange_id,
                    question=question,
                    request=request,
                    chat_mode=chat_mode,
                    current_date_text=current_date_text,
                    memory_service=memory_service,
                    archive_store=archive_store,
                    session=session,
                    lease_mgr=lease_mgr,
                    state=state,
                ),
                timeout=timeout,
            ):
                yield event

        except asyncio.CancelledError:
            state.turn_stopped = True
            state.last_error_message = "已停止生成"
            async for event in handle_cancelled_stream(
                task, task.plan, conversation_id, temp_exchange_id
            ):
                yield event

        except StreamChunkTimeoutError as exc:
            state.turn_failed = True
            state.last_error_message = str(exc) or "生成超时"
            async for event in handle_error_stream(
                task, task.plan, exc, conversation_id, temp_exchange_id
            ):
                yield event

        except GeneratorExit:
            state.turn_stopped = True
            logger.debug(
                "client disconnected, stream generator closed", exchange_id=temp_exchange_id
            )
            raise

        except Exception as exc:
            state.turn_failed = True
            from app.chat.service_utils import _build_error_message

            state.last_error_message = _build_error_message(exc)
            async for event in handle_error_stream(
                task, task.plan, exc, conversation_id, temp_exchange_id
            ):
                yield event

        finally:
            await finalize_stream(
                db=self.db,
                task=task,
                plan=task.plan,
                question=question,
                conversation_id=conversation_id,
                temp_exchange_id=temp_exchange_id,
                state=state,
                acquired=acquired,
                lease_mgr=lease_mgr,
                memory_service=memory_service,
                archive_store=archive_store,
                session=session,
            )
