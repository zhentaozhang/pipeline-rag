"""
BusinessChatService — 对话主服务
串联：记忆加载 → Orchestrator → ExecutorRegistry → 持久化

所有对话流式请求的唯一入口。
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date as date_type
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from app.common.enums import chat_mode_label
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
    支持短事务连接模式，长生成周期零持有数据库连接。
    """

    def __init__(
        self,
        db: AsyncSession | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.db = db
        self._session_factory = session_factory

    @contextlib.asynccontextmanager
    async def _get_session(self) -> AsyncIterator[AsyncSession]:
        """短事务模式获取 DB Session，执行完自动提交/关闭"""
        if self.db is not None:
            try:
                yield self.db
                if self.db.is_active:
                    await self.db.commit()
            except Exception:
                if self.db.is_active:
                    await self.db.rollback()
                raise
        else:
            from app.db.session import get_session_factory

            sf = self._session_factory or get_session_factory()
            if sf is None:
                raise RuntimeError("Session factory not initialized.")
            async with sf() as session:
                try:
                    yield session
                    if session.is_active:
                        await session.commit()
                except Exception:
                    if session.is_active:
                        await session.rollback()
                    raise

    async def stream(
        self, request: "ChatRequest", trace_id: str | None = None
    ) -> AsyncIterator[str]:
        """
        完整对话流程，生成 SSE 事件字符串序列。

        完整对话流程：
        buildLaunchPlan → claimLease → bootstrapConversation → createTaskInfo
        → bindClientChannel → activateGeneration → buildConversationExecution
        → executor.execute
        """
        from app.chat.store import ConversationArchiveStore
        from app.infra.redis_lease import RedisLeaseManager

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

        # 2. 查找或创建 Session (短事务获取并释放)
        async with self._get_session() as bootstrap_db:
            bootstrap_archive_store = ConversationArchiveStore(bootstrap_db)
            session, _ = await bootstrap_archive_store.find_or_create_session(
                conversation_id,
                question,
                user_id=getattr(request, "user_key", None),
                tenant_id=getattr(request, "tenant_id", "default"),
            )

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
            user_key=getattr(request, "user_key", None),
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
                # chat_mode 为 IntEnum，进入 SSE 载荷前必须归一为字符串标签
                payload=ConversationStartedPayload(
                    question=question, chat_mode=chat_mode_label(chat_mode)
                ),
                conversation_id=conversation_id,
                exchange_id=temp_exchange_id,
            )
        )

        state = _StreamState()

        # ── 响应缓存：短事务查询（命中跳过执行，未命中收集回写）────────────
        cached_hit = None
        collected_events: list[str] = []
        if settings.chat_cache.enabled:
            from app.chat.response_cache import lookup as cache_lookup

            async with self._get_session() as cache_lookup_db:
                cached_hit = await cache_lookup(
                    cache_lookup_db,
                    conversation_id,
                    question,
                    chat_mode_label(chat_mode),
                    request.doc_ids,
                )

        try:
            if cached_hit is not None:
                # 缓存命中：前置持久化 exchange，确保后续 finalize 能够 complete_exchange 成功落库
                from app.chat.store import ConversationArchiveStore

                task.exchange_id = temp_exchange_id
                async with self._get_session() as cache_exchange_db:
                    cache_archive_store = ConversationArchiveStore(cache_exchange_db)
                    await cache_archive_store.start_exchange(
                        exchange_id=temp_exchange_id,
                        conversation_id=conversation_id,
                        session_id=session.id,
                        question=question,
                        execution_mode="cache_hit",
                    )

                # 命中：回放缓存事件（替换 exchange_id 为本次真实值）
                import json as _json

                for raw in cached_hit.events:
                    line = raw.strip()
                    if line.startswith("data:"):
                        payload_str = line[len("data:") :].strip()
                        try:
                            payload = _json.loads(payload_str)
                            if payload.get("exchangeId") is not None:
                                payload["exchangeId"] = temp_exchange_id
                                raw = "data: " + _json.dumps(payload, ensure_ascii=False)
                        except ValueError:
                            pass
                    yield raw
                state.full_answer = [cached_hit.answer]
            else:
                timeout = settings.rag.stream_timeout_seconds
                # 零持有数据库连接保障：execute_stream 不再由长 session 上下文包裹。
                # 记忆加载与 exchange 预持久化在 execute_stream 内部短事务内按需完成并立即归还连接池，
                # SSE 跨越数十秒的大模型流式生成周期全程零持有数据库连接，避免在高并发下占满连接池。
                async for event in _async_generator_with_timeout(
                    execute_stream(
                        db=None,
                        task=task,
                        conversation_id=conversation_id,
                        temp_exchange_id=temp_exchange_id,
                        question=question,
                        request=request,
                        chat_mode=chat_mode_label(chat_mode),
                        current_date_text=current_date_text,
                        memory_service=None,
                        archive_store=None,
                        session=session,
                        lease_mgr=lease_mgr,
                        state=state,
                        trace_id=trace_id,
                        get_session=self._get_session,
                    ),
                    timeout=timeout,
                ):
                    if '"type": "clear_answer"' in event or '"type": "review"' in event:
                        collected_events = [
                            e for e in collected_events if '"type": "text"' not in e
                        ]
                    collected_events.append(event)
                    yield event

            # 正常结束（非失败/停止且非命中缓存回放）→ 写缓存（短事务独立写入）
            if (
                cached_hit is None
                and settings.chat_cache.enabled
                and not state.turn_failed
                and not state.turn_stopped
            ):
                from app.chat.response_cache import (
                    store as cache_store,
                )

                cacheable_events = [
                    e
                    for e in collected_events
                    if '"type": "text"' in e
                    or '"type": "reference"' in e
                    or '"type": "recommend"' in e
                    or '"type": "done"' in e
                ]
                async with self._get_session() as cache_store_db:
                    await cache_store(
                        cache_store_db,
                        conversation_id,
                        question,
                        chat_mode_label(chat_mode),
                        request.doc_ids,
                        cacheable_events,
                        "".join(state.full_answer),
                    )

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
            from app.chat.memory_service import PersistentConversationMemoryService
            from app.chat.store import ConversationArchiveStore

            async with self._get_session() as finalize_db:
                final_archive_store = ConversationArchiveStore(finalize_db)
                final_memory_service = PersistentConversationMemoryService(finalize_db)
                await finalize_stream(
                    db=finalize_db,
                    task=task,
                    plan=task.plan,
                    question=question,
                    conversation_id=conversation_id,
                    temp_exchange_id=temp_exchange_id,
                    state=state,
                    acquired=acquired,
                    lease_mgr=lease_mgr,
                    memory_service=final_memory_service,
                    archive_store=final_archive_store,
                    session=session,
                )
