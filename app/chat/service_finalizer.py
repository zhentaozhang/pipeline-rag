from collections.abc import AsyncIterator
from datetime import UTC, datetime

import structlog

from app.chat.schema import ExecutionPlan
from app.chat.service_utils import _build_error_message, _estimate_tokens
from app.chat.state_machine import ConversationState
from app.chat.task_info import ChatRuntimeRegistry, ChatTaskInfo
from app.common.sse import SSEEventType, sse_event
from app.eventbus.bus import bus
from app.eventbus.events import (
    ConversationCancelledPayload,
    ConversationCompletedPayload,
    ConversationFailedPayload,
    Event,
    MemorySavedPayload,
)
from app.observability import SpanKind

logger = structlog.get_logger(__name__)


async def finalize_stream(
    db,
    task: ChatTaskInfo,
    plan: ExecutionPlan | None,
    question: str,
    conversation_id: str,
    temp_exchange_id: int,
    state,
    acquired: bool,
    lease_mgr,
    memory_service,
    archive_store,
    session,
) -> None:
    if task.sm.state in {ConversationState.EXECUTING}:
        task.sm.transition(ConversationState.FINALIZING)

    elapsed_total = int((datetime.now(UTC) - task.start_time).total_seconds() * 1000)
    final_tokens = task.total_tokens
    if final_tokens == 0:
        final_tokens = _estimate_tokens(question + "".join(state.full_answer))

    if state.turn_stopped:
        turn_status = 4
    elif state.turn_failed:
        turn_status = 3
    else:
        turn_status = 2

    try:
        await archive_store.complete_exchange(
            exchange_id=temp_exchange_id,
            conversation_id=conversation_id,
            answer="".join(state.full_answer),
            tokens_used=final_tokens,
            turn_status=turn_status,
            first_response_time_ms=task.first_response_time_ms or None,
            total_response_time_ms=elapsed_total or None,
            references=state.collected_references if state.collected_references else None,
            recommendations=state.collected_recommendations
            if state.collected_recommendations
            else None,
            thinking_steps=task.thinking_steps if task.thinking_steps else None,
            used_tools=task.used_tools if task.used_tools else None,
            debug_trace=task.debug_trace.model_dump() if task.debug_trace else None,
            error_message=""
            if not (state.turn_failed or state.turn_stopped)
            else state.last_error_message,
        )
        logger.info(
            "exchange finalized",
            exchange_id=temp_exchange_id,
            turn_failed=state.turn_failed,
            turn_stopped=state.turn_stopped,
        )

        if turn_status == 2:
            await memory_service.save(
                conversation_id=conversation_id,
                question=question,
                answer="".join(state.full_answer),
                exchange_id=temp_exchange_id,
            )
            await bus.emit(
                Event(
                    name="memory.saved",
                    payload=MemorySavedPayload(
                        conversation_id=conversation_id,
                        exchange_id=temp_exchange_id,
                    ),
                    conversation_id=conversation_id,
                    exchange_id=temp_exchange_id,
                )
            )
    except Exception:
        logger.exception("persist exchange failed")

    # 标题生成改为 Celery 异步执行（体检 B5）：避免流式请求收尾被 LLM 调用阻塞。
    # 任务内部会用独立 DB session，并二次校验标题未被用户重命名。
    # 用标量查询取标题，避免 finalize 阶段 ORM 属性访问触发 async IO（MissingGreenlet）
    if turn_status == 2 and state.full_answer:
        current_title = await archive_store.get_session_title(conversation_id)
        if current_title == question:
            try:
                from app.chat.tasks import task_generate_session_title

                task_generate_session_title.delay(
                    conversation_id, question, "".join(state.full_answer)[:1000]
                )
            except Exception as title_err:
                logger.warning(
                    "session title task dispatch failed",
                    error=str(title_err),
                    exc_info=True,
                )

        # P3 用户事实记忆（Mem0 式）：异步抽取（采样率控制，离线不阻塞收尾）
        try:
            from app.config import get_settings

            fm_settings = get_settings().fact_memory
            if fm_settings.enabled:
                import random as _random

                if _random.random() < fm_settings.extract_sample_rate:
                    from app.chat.tasks import task_extract_user_facts

                    task_extract_user_facts.delay(
                        conversation_id,
                        question,
                        "".join(state.full_answer)[:2000],
                        temp_exchange_id,
                    )
        except Exception as fact_err:
            logger.warning(
                "user facts dispatch failed",
                error=str(fact_err),
                exc_info=True,
            )

    if task.tracer:
        await task.tracer.flush()

    try:
        if state.turn_stopped:
            task.sm.transition(ConversationState.CANCELLED)
        elif state.turn_failed:
            task.sm.transition(ConversationState.FAILED)
        elif task.sm.state in {
            ConversationState.FINALIZING,
            ConversationState.EXECUTING,
            ConversationState.PREPARED,
        }:
            task.sm.transition(ConversationState.COMPLETED)
    except Exception:
        logger.exception("state_machine.final_transition_error")

    try:
        _event: Event[
            ConversationCompletedPayload | ConversationFailedPayload | ConversationCancelledPayload
        ]
        if turn_status == 2:
            _event = Event(
                name="conversation.completed",
                payload=ConversationCompletedPayload(
                    exchange_id=temp_exchange_id,
                    turn_status=turn_status,
                    total_tokens=final_tokens,
                    total_duration_ms=elapsed_total,
                ),
                conversation_id=conversation_id,
                exchange_id=temp_exchange_id,
            )
        elif turn_status == 3:
            _event = Event(
                name="conversation.failed",
                payload=ConversationFailedPayload(
                    exchange_id=temp_exchange_id,
                    error=state.last_error_message or "unknown",
                ),
                conversation_id=conversation_id,
                exchange_id=temp_exchange_id,
            )
        else:
            _event = Event(
                name="conversation.cancelled",
                payload=ConversationCancelledPayload(
                    exchange_id=temp_exchange_id,
                ),
                conversation_id=conversation_id,
                exchange_id=temp_exchange_id,
            )
        await bus.emit(_event)
    except Exception:
        logger.exception("eventbus.conversation_finalize_error")

    ChatRuntimeRegistry.unregister(conversation_id, task)
    if acquired:
        await lease_mgr.release()


async def handle_cancelled_stream(
    task: ChatTaskInfo,
    plan: ExecutionPlan | None,
    conversation_id: str,
    temp_exchange_id: int,
) -> AsyncIterator[str]:
    logger.info("chat stream cancelled by client or stop command", conversation_id=conversation_id)
    if task.finalize() and task.tracer:
        async with task.tracer.span("cancel", kind=SpanKind.PIPELINE):
            pass
        task.cancel()
    yield sse_event(
        SSEEventType.STATUS,
        "⏹ 已停止生成",
        conversation_id=conversation_id,
        exchange_id=temp_exchange_id,
    )
    yield sse_event(
        SSEEventType.ERROR,
        "已停止生成",
        conversation_id=conversation_id,
        exchange_id=temp_exchange_id,
    )
    yield sse_event(
        SSEEventType.DONE, conversation_id=conversation_id, exchange_id=temp_exchange_id
    )


async def handle_error_stream(
    task: ChatTaskInfo,
    plan: ExecutionPlan | None,
    exc: Exception,
    conversation_id: str,
    temp_exchange_id: int,
) -> AsyncIterator[str]:
    logger.exception("chat stream error", conversation_id=conversation_id)
    last_error_message = _build_error_message(exc)
    if task.finalize() and task.tracer:
        async with task.tracer.span("error", kind=SpanKind.PIPELINE):
            pass
    yield sse_event(
        SSEEventType.ERROR,
        last_error_message,
        conversation_id=conversation_id,
        exchange_id=temp_exchange_id,
    )
    yield sse_event(
        SSEEventType.DONE, conversation_id=conversation_id, exchange_id=temp_exchange_id
    )
