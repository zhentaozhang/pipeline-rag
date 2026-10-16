import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import structlog

from app.chat.schema import ExecutionPlan
from app.chat.state_machine import ConversationState
from app.chat.task_info import ChatTaskInfo
from app.common.enums import ExecutionMode, chat_mode_label
from app.common.sse import SSEEventType, sse_event
from app.observability.metrics import ACTIVE_EXCHANGES, EXCHANGE_TOTAL, EXECUTION_MODE_TOTAL
from app.observability.trace_models import ChatDebugTrace

logger = structlog.get_logger(__name__)


async def execute_stream(
    db=None,
    task: ChatTaskInfo | None = None,
    conversation_id: str = "",
    temp_exchange_id: int = 0,
    question: str = "",
    request=None,
    chat_mode: str = "",
    current_date_text: str = "",
    memory_service=None,
    archive_store=None,
    session=None,
    lease_mgr=None,
    state=None,
    trace_id: str | None = None,
    get_session: Any = None,
) -> AsyncIterator[str]:
    if task is None:
        # task 承载会话运行时状态（状态机 / tracer / 计数器），缺失时后续逻辑无意义。
        # 在此显式收窄，既是运行期契约，也让类型检查在下方全程按 ChatTaskInfo 推断。
        raise ValueError("execute_stream 必须显式传入 task")
    plan: ExecutionPlan | None = None

    from app.config import get_settings as _get_settings

    _settings = _get_settings()
    _chunk_count: int = 0
    from app.config import get_settings

    settings = get_settings()
    _LEASE_CHECK_INTERVAL = max(1, settings.redis.lease_check_interval)

    from app.observability import SpanKind, Tracer
    from app.observability.models import Trace
    from app.observability.tracer import new_trace_id

    tracer = Tracer(
        db=db,
        # 优先使用 OTel server span 透传的 trace_id（基础设施 span 与业务 trace 同 ID），否则回退
        trace_id=trace_id
        or getattr(getattr(request, "state", None), "app_trace_id", None)
        or new_trace_id(),
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

    # 给当前 OTel span 打上应用层标识（未启用 OTel 时静默 no-op）
    from app.observability.otel_setup import tag_current_otel_span

    tag_current_otel_span(
        trace_id=tracer.trace_id,
        conversation_id=conversation_id,
        exchange_id=temp_exchange_id,
    )

    async with tracer.span("memory_load", kind=SpanKind.PIPELINE):
        if get_session is not None:
            from app.chat.memory_service import PersistentConversationMemoryService

            async with get_session() as prep_db:
                prep_memory_service = PersistentConversationMemoryService(prep_db)
                memory_ctx = await prep_memory_service.load(conversation_id)
        elif memory_service is not None:
            memory_ctx = await memory_service.load(conversation_id)
        else:
            from app.chat.memory import MemoryContext

            # MemoryContext 不接受 conversation_id（会话归属由 task.conversation_id 承载），
            # 早前误传该关键字会在无 get_session / memory_service 的兜底路径抛 TypeError。
            memory_ctx = MemoryContext()

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
        # P3 用户事实记忆（Mem0 式）：检索相关长期记忆注入 plan（默认关）
        # 覆盖 RETRIEVAL（RAG 问答）与 AGENT（React Agent 联网/工具）两类主执行器
        try:
            if _settings.fact_memory.enabled and plan.mode in (
                ExecutionMode.RETRIEVAL,
                ExecutionMode.AGENT,
            ):
                from app.chat.fact_memory import FactMemoryStore
                from app.infra.embedding import get_embedding_provider

                q_embedding = (
                    await get_embedding_provider().embed_batch(
                        [question or plan.original_question or ""]
                    )
                )[0]
                facts = await FactMemoryStore().retrieve(
                    conversation_id,
                    q_embedding,
                    _settings.fact_memory.retrieval_top_k,
                    user_key=getattr(task, "user_key", None),
                )
                plan.user_memory_context = facts
                logger.debug(
                    "user memory injected",
                    conversation_id=conversation_id,
                    mode=plan.mode,
                    count=len(facts),
                )
        except Exception as e:
            logger.warning("user memory retrieve failed", error=str(e), exc_info=True)

        task.plan = plan
        task.sm.transition(ConversationState.PREPARED)
        EXECUTION_MODE_TOTAL.labels(mode=plan.mode.value).inc()

        plan.agent_question = plan.original_question or ""
        task.debug_trace = ChatDebugTrace(
            execution_mode=plan.mode.value,
            chat_mode=chat_mode_label(plan.chat_mode) if plan.chat_mode else request.chat_mode,
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
    if get_session is not None:
        from app.chat.store import ConversationArchiveStore

        async with get_session() as prep_db:
            prep_archive_store = ConversationArchiveStore(prep_db)
            await prep_archive_store.start_exchange(
                exchange_id=temp_exchange_id,
                conversation_id=conversation_id,
                session_id=session.id,
                question=question,
                execution_mode=plan.mode.value if plan else "unknown",
            )
    elif archive_store is not None:
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
    # 零持有数据库连接保障：进入执行器前，若存在显式传入的 db，显式 commit 并 close 释放连接；
    # 走 get_session 模式时前置步骤已在短事务退出后自动归还连接池，流式生成周期全程零持有连接。
    if db is not None:
        try:
            if hasattr(db, "commit"):
                await db.commit()
            if hasattr(db, "close"):
                await db.close()
        except Exception:
            pass

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
        _ct = getattr(task, "_citation_task", None)
        if _ct is not None:
            _ct.cancel()
        task.finalize()
        return

    state.collected_references.clear()
    state.collected_references.extend(task.references or [])
    if state.collected_references:
        from app.chat.citation_verifier import dedupe_references

        unique_refs = dedupe_references(state.collected_references)
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
        # P0-1d: 无证据兜底回复轮跳过推荐——推荐基于回答上下文，无证据时无推荐价值
        # 019 审查：精确匹配脆弱（模型措辞微变即失效），改为去空白前缀匹配
        answer_text = "".join(state.full_answer)
        _no_evidence_reply = plan.no_evidence_reply or ""
        no_evidence = bool(_no_evidence_reply) and answer_text.replace(" ", "").startswith(
            _no_evidence_reply.replace(" ", "")
        )
        if answer_text and not no_evidence and _settings.recommendation.enabled:
            async with tracer.span("recommendation", kind=SpanKind.PIPELINE):
                from app.orchestrator.recommendation import RecommendationService

                recommendations = await RecommendationService().generate_recommendations(
                    question=question, answer=answer_text, memory_ctx=memory_ctx
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

    # 017 生成侧：引用验证器（LLM 自检引用-证据对应，追加诚实说明）
    _answer_full = "".join(state.full_answer)
    if _answer_full:
        try:
            from app.chat.citation_verifier import (
                citation_verify_enabled,
                extract_citations,
                verify_citations,
            )

            _refs = extract_citations(_answer_full)
            logger.info(
                "citation verify enter",
                conversation_id=conversation_id,
                refs=_refs,
                ref_count=len(state.collected_references or []),
                task_ref_count=len(task.references or []),
                enabled=citation_verify_enabled(),
            )
            if citation_verify_enabled() and _refs:
                from app.common.llm_client import get_chat_client
                from app.infra.model_fallback import ModelFallbackManager

                _fallback = ModelFallbackManager(client=get_chat_client())
                _ref_input = list(state.collected_references or []) or list(task.references or [])
                # P1-c：优先复用 RagChatExecutor 与质量自审并发预跑的校验结果
                _task = getattr(task, "_citation_task", None)
                _base_answer = _answer_full
                _parallel = False
                if _task is not None:
                    try:
                        _t_base, _verified, _bad_refs, _vmeta = await _task
                        if _t_base == _answer_full:
                            _base_answer, _parallel = _t_base, True
                    except Exception as _e:
                        logger.warning("citation verify task failed", error=str(_e)[:120])
                if not _parallel:
                    async with tracer.span(
                        "citation_verify",
                        kind=SpanKind.PIPELINE,
                        input={
                            "refs": _refs,
                            "ref_count": len(_ref_input),
                            "ref_preview": [
                                str(r.get("content") or r.get("title") or r)[:50]
                                for r in _ref_input[:3]
                            ],
                            "has_content": any(r.get("content") for r in _ref_input[:3]),
                        },
                    ):
                        _verified, _bad_refs, _vmeta = await verify_citations(
                            fallback=_fallback,
                            answer=_answer_full,
                            references=_ref_input,
                            question=question,
                        )
                tracer.attach_score(
                    "citation_accuracy",
                    1.0 - (len(_bad_refs) / max(1, len(_refs))),
                    reason=f"verify {_vmeta.get('status')}",
                )
                if _bad_refs and _verified != _base_answer:
                    state.full_answer.append(_verified[len(_base_answer) :])
                    # 回答正文已流式发出，追加说明对用户不可见——
                    # 通过独立 SSE 事件提示（用户可见），并落库修正
                    yield sse_event(
                        SSEEventType.STATUS,
                        "⚠️ 回答中部分引用未能从当前知识库证据中找到支持，"
                        "相关表述请以官方文件为准。",
                        conversation_id=conversation_id,
                        exchange_id=temp_exchange_id,
                    )
                    logger.info(
                        "citation verify flagged",
                        conversation_id=conversation_id,
                        bad_refs=_bad_refs,
                    )
        except Exception as _e:
            logger.warning("citation verify skipped", error=str(_e)[:120])

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
