"""
增量记忆压缩器

SummaryCompressionStrategy 的后台压缩逻辑：
- 批次加载增量 exchange
- LLM 摘要合并（降级到规则拼接）
- SAVEPOINT 检查避免并发覆盖
"""

import copy

import structlog
from sqlalchemy import select

from app.chat.memory import (
    MAX_GOAL_LENGTH,
    MAX_ITEM_LENGTH,
    TURN_COMPLETED,
    ConversationSummaryPayload,
    clip_text,
    deduplicate_and_limit,
    extract_retrieval_hints,
)
from app.chat.transcript_renderer import TranscriptRenderer
from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class ConversationMemoryCompressor:
    """后台记忆压缩器，被 Celery 任务调用"""

    async def compress_history(
        self, conversation_id: str, db, known_exchange_id: int | None = None
    ) -> None:
        from app.db.models.conversation import ConversationExchange, ConversationMemory

        mem_result = await db.execute(
            select(ConversationMemory).where(ConversationMemory.conversation_id == conversation_id)
        )
        mem = mem_result.scalar_one_or_none()
        covered_exchange_id = mem.covered_exchange_id if mem and mem.covered_exchange_id else 0

        base_query = select(ConversationExchange).where(
            ConversationExchange.conversation_id == conversation_id
        )
        if covered_exchange_id > 0:
            base_query = base_query.where(ConversationExchange.id > covered_exchange_id)
        result = await db.execute(base_query.order_by(ConversationExchange.id.asc()))
        incremental_exchanges = result.scalars().all()

        stable_exchanges = [
            e
            for e in incremental_exchanges
            if e.turn_status == TURN_COMPLETED and e.question and e.question.strip()
        ]

        overflow_count = max(0, len(stable_exchanges) - settings.memory.window_size)
        if overflow_count <= 0:
            return

        overflow_exchanges = stable_exchanges[:overflow_count]
        if not overflow_exchanges:
            return

        existing_payload = ConversationSummaryPayload()
        if mem and mem.summary_json:
            try:
                existing_payload = ConversationSummaryPayload.model_validate_json(mem.summary_json)
            except Exception:
                logger.warning(
                    "failed to parse structured summary, falling back to raw text", exc_info=True
                )
                existing_payload.summary = mem.summary_json or ""

        merged_payload = existing_payload
        batch_size = settings.memory.summary_batch_size or 4
        last_covered_id = covered_exchange_id
        covered_count = 0

        for start in range(0, len(overflow_exchanges), batch_size):
            end = min(start + batch_size, len(overflow_exchanges))
            batch = overflow_exchanges[start:end]
            merged_payload = await self._merge_summary_payload(merged_payload, batch)
            last_exchange = batch[-1]
            last_covered_id = last_exchange.id
            covered_count += len(batch)

        latest_mem_result = await db.execute(
            select(ConversationMemory).where(ConversationMemory.conversation_id == conversation_id)
        )
        latest_mem = latest_mem_result.scalar_one_or_none()
        latest_covered_id = (
            latest_mem.covered_exchange_id if latest_mem and latest_mem.covered_exchange_id else 0
        )

        if latest_covered_id > last_covered_id:
            logger.info(
                "memory compression skipped — another process wrote ahead",
                conversation_id=conversation_id,
                latest_covered=latest_covered_id,
                our_covered=last_covered_id,
            )
            return

        if (
            latest_mem
            and latest_covered_id == last_covered_id
            and latest_mem.summary_text
            and latest_mem.summary_text.strip()
        ):
            logger.info(
                "memory compression skipped — already saved",
                conversation_id=conversation_id,
                covered_id=last_covered_id,
            )
            return

        summary_json = merged_payload.model_dump_json(by_alias=True, exclude_none=True)
        long_term_summary_text = self._build_long_term_summary_text(merged_payload)

        if not latest_mem:
            latest_mem = ConversationMemory(
                conversation_id=conversation_id,
                summary_json="",
                covered_exchange_id=0,
            )
            db.add(latest_mem)

        async with db.begin_nested():
            latest_mem.summary_json = summary_json
            latest_mem.summary_text = long_term_summary_text
            latest_mem.covered_exchange_id = last_covered_id
        await db.commit()
        logger.info(
            "memory compressed",
            conversation_id=conversation_id,
            pointer=last_covered_id,
            covered_count=covered_count,
        )

    async def _merge_summary_payload(
        self,
        existing_payload: ConversationSummaryPayload,
        batch: list,
    ) -> ConversationSummaryPayload:
        from app.common.jinja import jinja_env
        from app.common.llm_client import get_chat_client, llm_breaker

        try:
            client = get_chat_client()
            existing_json = existing_payload.model_dump_json(by_alias=True, exclude_none=True)
            new_conversation_batch = TranscriptRenderer.render_compression_transcript(batch)

            template = jinja_env.get_template("memory_summary.j2")
            prompt = template.render(
                current_summary=existing_json,
                new_dialogue=new_conversation_batch,
            )

            try:
                async with llm_breaker():
                    response = await client.chat.completions.create(
                        model=settings.llm.model,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a helpful assistant that summarizes conversation histories. Output valid JSON matching the provided structure.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.3,
                        max_tokens=settings.llm.max_tokens,
                        response_format={"type": "json_object"},
                    )
            except Exception:
                logger.warning(
                    "LLM summary with response_format failed, retrying without it", exc_info=True
                )
                async with llm_breaker():
                    response = await client.chat.completions.create(
                        model=settings.llm.model,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a helpful assistant that summarizes conversation histories. Output valid JSON matching the provided structure.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.3,
                        max_tokens=settings.llm.max_tokens,
                    )
            content = response.choices[0].message.content
            parsed = ConversationSummaryPayload.model_validate_json(content or "{}")
            return self._normalize_payload(parsed)
        except Exception as e:
            logger.warning(
                "LLM summary merge failed, fallback to rule-based", error=str(e), exc_info=True
            )
            return self._fallback_merge(existing_payload, batch)

    def _fallback_merge(
        self,
        existing_payload: ConversationSummaryPayload,
        batch: list,
    ) -> ConversationSummaryPayload:
        merged = copy.deepcopy(existing_payload)

        highlights = []
        for exchange in batch:
            if exchange.question:
                highlights.append("用户关注：" + clip_text(exchange.question, MAX_ITEM_LENGTH))
            if exchange.answer:
                highlights.append("已有结论：" + clip_text(exchange.answer, MAX_ITEM_LENGTH))
            if len(highlights) >= 4:
                break
        batch_highlight = "；".join(highlights)

        merged_summary = merged.summary or ""
        if merged_summary and batch_highlight:
            merged_summary = merged_summary + "；" + batch_highlight
        elif batch_highlight:
            merged_summary = batch_highlight
        merged.summary = clip_text(
            merged_summary, getattr(settings.memory, "max_summary_chars", 1400) or 1400
        )

        last_exchange = batch[-1] if batch else None
        if not merged.conversation_goal and last_exchange and last_exchange.question:
            merged.conversation_goal = clip_text(last_exchange.question, MAX_GOAL_LENGTH)

        pending = list(merged.pending_questions) if merged.pending_questions else []
        for exchange in batch:
            if exchange.question:
                pending.append(clip_text(exchange.question, MAX_ITEM_LENGTH))
        merged.pending_questions = deduplicate_and_limit(pending)

        retrieval_hints = list(merged.retrieval_hints) if merged.retrieval_hints else []
        if last_exchange and last_exchange.question:
            retrieval_hints.extend(extract_retrieval_hints(last_exchange.question))
        merged.retrieval_hints = deduplicate_and_limit(retrieval_hints)

        return self._normalize_payload(merged)

    def _normalize_payload(self, payload: ConversationSummaryPayload) -> ConversationSummaryPayload:
        max_summary_chars = settings.memory.max_summary_chars or 1400
        normalized_summary = clip_text(payload.summary or "", max_summary_chars)
        if not normalized_summary:
            normalized_summary = self._synthesize_summary_from_sections(payload)

        return ConversationSummaryPayload.model_construct(
            summary=normalized_summary,
            conversation_goal=clip_text(payload.conversation_goal or "", MAX_GOAL_LENGTH),
            stable_facts=deduplicate_and_limit(payload.stable_facts or []),
            user_preferences=deduplicate_and_limit(payload.user_preferences or []),
            resolved_points=deduplicate_and_limit(payload.resolved_points or []),
            pending_questions=deduplicate_and_limit(payload.pending_questions or []),
            retrieval_hints=deduplicate_and_limit(payload.retrieval_hints or []),
        )

    def _synthesize_summary_from_sections(self, payload: ConversationSummaryPayload) -> str:
        max_summary_chars = settings.memory.max_summary_chars or 1400
        parts = []
        if payload.conversation_goal:
            parts.append("目标：" + clip_text(payload.conversation_goal, MAX_ITEM_LENGTH))
        if payload.stable_facts:
            parts.append("事实：" + "；".join(payload.stable_facts))
        if payload.pending_questions:
            parts.append("待跟进：" + "；".join(payload.pending_questions))
        return clip_text("；".join(parts), max_summary_chars)

    def _build_long_term_summary_text(self, payload: ConversationSummaryPayload) -> str:
        max_summary_chars = settings.memory.max_summary_chars or 1400
        normalized = self._normalize_payload(payload)
        builder = []

        def _append_section(title: str, content: str):
            if not content:
                return
            builder.append(f"【{title}】\n{content.strip()}")

        def _append_bullet_section(title: str, values: list[str]):
            if not values:
                return
            builder.append(f"【{title}】")
            for v in values:
                builder.append(f"- {v}")

        _append_section("长期会话摘要", normalized.summary)
        _append_section("会话目标", normalized.conversation_goal)
        _append_bullet_section("已确认事实", normalized.stable_facts)
        _append_bullet_section("用户偏好与约束", normalized.user_preferences)
        _append_bullet_section("已解决问题", normalized.resolved_points)
        _append_bullet_section("待跟进问题", normalized.pending_questions)
        _append_bullet_section("检索提示", normalized.retrieval_hints)
        return clip_text("\n".join(builder), max_summary_chars)
