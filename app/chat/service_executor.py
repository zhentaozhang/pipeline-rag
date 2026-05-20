import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import structlog

from app.chat.schema import ExecutionPlan
from app.chat.state_machine import ConversationState
from app.chat.task_info import ChatTaskInfo
from app.common.enums import ExecutionMode
from app.common.sse import SSEEventType, sse_event
from app.observability.metrics import ACTIVE_EXCHANGES, EXCHANGE_TOTAL, EXECUTION_MODE_TOTAL
from app.observability.trace_models import ChatDebugTrace

logger = structlog.get_logger(__name__)


async def execute_stream(
    db,
    task: ChatTaskInfo,
    conversation_id: str,
    temp_exchange_id: int,
    question: str,
    request,
    chat_mode: str,
    current_date_text: str,
    memory_service,
    archive_store,
    session,
    lease_mgr,
    state,
) -> AsyncIterator[str]:
    plan: ExecutionPlan | None = None
    _chunk_count: int = 0
    from app.config import get_settings

    settings = get_settings()
    _LEASE_CHECK_INTERVAL = max(1, settings.redis.lease_check_interval)

    from app.observability import SpanKind, Tracer
    from app.observability.models import Trace
    from app.observability.tracer import next_id_str

    tracer = Tracer(
        db=db,
        trace_id=next_id_str(),
        conversation_id=conversation_id,
        exchange_id=temp_exchange_id,
        sample_rate=settings.observability.sample_rate,
    )
    tracer._trace = Trace(
        trace_id=tracer._trace_id,
        conversation_id=tracer._conversation_id,
        exchange_id=tracer._exchange_id,
        session_id=str(session.id) if hasattr(session, "id") and session.id else None,
    )
    task.tracer = tracer
    ACTIVE_EXCHANGES.inc()
    tracer.root("exchange", kind=SpanKind.PIPELINE)

    async with tracer.span("memory_load", kind=SpanKind.PIPELINE):
        memory_ctx = await memory_service.load(conversation_id)

    logger.info(
        "memory loaded",
        conversation_id=conversation_id,
        has_summary=bool(memory_ctx.summary_payload.summary),
        recent_turns=len(memory_ctx.recent_turns),
    )
    task.sm.transition(ConversationState.MEMORY_LOADED)

    task.sm.transition(ConversationState.ORCHESTRATING)
    async with tracer.span("orchestrator", kind=SpanKind.PIPELINE):
        from app.orchestrator.orchestrator import prepare as orchestrator_prepare

        plan = await orchestrator_prepare(
            question=question,
            conversation_id=conversation_id,
            memory_ctx=memory_ctx,
            doc_ids=request.doc_ids,
            chat_mode=request.chat_mode,
            selected_document_id=request.selected_document_id,
            exchange_id=temp_exchange_id,
            tenant_id=getattr(session, "tenant_id", "default"),
        )
        task.plan = plan
        task.sm.transition(ConversationState.PREPARED)
        EXECUTION_MODE_TOTAL.labels(mode=plan.mode.value).inc()

        plan.agent_question = plan.original_question or ""
        task.debug_trace = ChatDebugTrace(
            execution_mode=plan.mode.value,
            chat_mode=plan.chat_mode.name if plan.chat_mode else request.chat_mode,
            original_question=request.question,
            rewrite_question=plan.rewritten_question,
            rewrite_sub_questions=plan.rewrite_sub_questions,
            retrieval_question=plan.retrieval_question or "",
            agent_question=plan.agent_question,
            navigation_decision=plan.navigation_decision.model_dump()
            if plan.navigation_decision
            else {},
            history_summary=plan.history_summary,
            long_term_summary=plan.long_term_summary,
            recent_history_transcript=plan.recent_history_transcript,
            answer_recent_transcript=plan.answer_recent_transcript,
            answer_history_context=plan.answer_history_context.rendered_text
            if plan.answer_history_context
            else "",
            answer_history_follow_up_question=plan.answer_history_context.follow_up_question
            if plan.answer_history_context
            else False,
            history_compression_applied=False,
            history_covered_exchange_id=None,
            history_covered_exchange_count=0,
            history_compression_count=0,
            current_date_text=plan.current_date_text,
            requires_fresh_search=plan.requires_fresh_search,
            requires_current_date_anchoring=plan.requires_current_date_anchoring,
            retrieval_sub_questions=plan.retrieval_sub_questions,
            selected_document_id=plan.selected_document_id,
            selected_task_id=plan.selected_task_id,
            retrieval_notes=[],
            used_channels=[],
            no_evidence_reply=plan.no_evidence_reply or "",
        )

    logger.info(
        "execution plan ready",
        mode=plan.mode,
        sub_questions=len(plan.sub_questions),
    )

    task.exchange_id = temp_exchange_id
    await archive_store.start_exchange(
        exchange_id=temp_exchange_id,
        conversation_id=conversation_id,
        session_id=session.id,
        question=question,
        execution_mode=plan.mode.value if plan else "unknown",
    )
    logger.info(
        "exchange pre-persisted",
        conversation_id=conversation_id,
        exchange_id=temp_exchange_id,
    )

    yield sse_event(
        SSEEventType.THINKING,
        "正在分析问题上下文。",
        conversation_id=conversation_id,
        exchange_id=temp_exchange_id,
    )
    from app.executors.registry import ExecutorRegistry

    registry = ExecutorRegistry(db=db, task=task)
    task.sm.transition(ConversationState.EXECUTING)
    async for chunk in registry.dispatch(plan):
        if task.cancelled:
            state.turn_stopped = True
            state.last_error_message = "已停止生成"
            yield sse_event(
                SSEEventType.STATUS,
                "⏹ 已停止生成",
                conversation_id=conversation_id,
                exchange_id=temp_exchange_id,
            )
            yield sse_event(
                SSEEventType.ERROR,
                state.last_error_message,
                conversation_id=conversation_id,
                exchange_id=temp_exchange_id,
            )
            yield sse_event(
                SSEEventType.DONE,
                conversation_id=conversation_id,
                exchange_id=temp_exchange_id,
            )
            break
        yield chunk

        _chunk_count += 1
        if _chunk_count % _LEASE_CHECK_INTERVAL == 0:
            still_owned = await lease_mgr.is_owned()
            if not still_owned:
                logger.warning(
                    "redis lease lost mid-execution, forcing stop",
                    conversation_id=conversation_id,
                )
                state.turn_stopped = True
                state.last_error_message = "会话锁已丢失，系统将停止当前执行"
                yield sse_event(
                    SSEEventType.STATUS,
                    "⏹ 会话租约已失效，已停止生成",
                    conversation_id=conversation_id,
                    exchange_id=temp_exchange_id,
                )
                yield sse_event(
                    SSEEventType.ERROR,
                    state.last_error_message,
                    conversation_id=conversation_id,
                    exchange_id=temp_exchange_id,
                )
                yield sse_event(
                    SSEEventType.DONE,
                    conversation_id=conversation_id,
                    exchange_id=temp_exchange_id,
                )
                break

        try:
            data = json.loads(chunk.removeprefix("data: ").strip())
            if data.get("type") == "text":
                elapsed = int((datetime.now(UTC) - task.start_time).total_seconds() * 1000)
                task.try_set_first_response_time(elapsed)
                content = data.get("content", "")
                if isinstance(content, dict):
                    content = content.get("content", "")
                state.full_answer.append(str(content))
        except Exception as e:
            logger.warning(
                "failed to parse text chunk", chunk=chunk[:80], error=str(e), exc_info=True
            )

        if '"usage_metadata"' in chunk:
            try:
                data = json.loads(chunk.removeprefix("data: ").strip())
                if "usage_metadata" in data:
                    usage = data["usage_metadata"]
                    task.add_token_usage(
                        usage.get("input_tokens", 0), usage.get("output_tokens", 0)
                    )
            except Exception as e:
                logger.warning(
                    "failed to parse usage chunk", chunk=chunk[:80], error=str(e), exc_info=True
                )

    if state.turn_stopped:
        task.finalize()
        return

    state.collected_references.clear()
    state.collected_references.extend(task.references or [])
    if state.collected_references:
        seen_keys: set[str] = set()
        unique_refs: list[dict] = []
        for ref in state.collected_references:
            key = str(ref.get("id", "")) or str(ref.get("title", "")) or str(ref.get("url", ""))
            if key and key not in seen_keys:
                seen_keys.add(key)
                unique_refs.append(ref)
        if unique_refs:
            yield sse_event(
                SSEEventType.REFERENCE,
                unique_refs,
                conversation_id=conversation_id,
                exchange_id=temp_exchange_id,
            )
            state.collected_references.clear()
            state.collected_references.extend(unique_refs)

    if plan and plan.mode == ExecutionMode.CLARIFICATION:
        state.collected_recommendations.clear()
        state.collected_recommendations.extend(plan.clarification_options or [])
        if state.collected_recommendations:
            yield sse_event(
                SSEEventType.RECOMMENDATION,
                state.collected_recommendations,
                conversation_id=conversation_id,
                exchange_id=temp_exchange_id,
            )
    elif plan:
        async with tracer.span("recommendation", kind=SpanKind.PIPELINE):
            from app.orchestrator.recommendation import RecommendationService

            recommendations = await RecommendationService().generate_recommendations(
                question=question, answer="".join(state.full_answer), memory_ctx=memory_ctx
            )
            if recommendations:
                state.collected_recommendations.clear()
                state.collected_recommendations.extend(recommendations)
                yield sse_event(
                    SSEEventType.RECOMMENDATION,
                    recommendations,
                    conversation_id=conversation_id,
                    exchange_id=temp_exchange_id,
                )

    if task.debug_trace and task.debug_trace.limit_stats and task.used_tools:
        task.debug_trace.limit_stats.tool_call_used = len(task.used_tools)
    task.finalize()
    yield sse_event(
        SSEEventType.DONE, conversation_id=conversation_id, exchange_id=temp_exchange_id
    )

    # ── 延迟评估：DONE 发出后执行，再 flush（确保 eval scores 落盘）─
    pending = getattr(task, "_pending_eval", None)
    if pending:
        from app.observability.metrics.pipeline import EvaluationPipeline

        try:
            _pipeline = EvaluationPipeline.standard()
            _results = await _pipeline.run(
                question=pending["question"],
                answer=pending["answer"],
                contexts=pending["contexts"],
                tracer=task.tracer,
                timeout=settings.rag.evaluation_timeout_seconds,
            )
            for _r in _results:
                logger.info("rag_eval_result", metric=_r.metric_name, value=_r.value)
        except Exception:
            logger.exception("rag_evaluation_failed")

    await tracer.flush()
    EXCHANGE_TOTAL.inc()
    ACTIVE_EXCHANGES.dec()
