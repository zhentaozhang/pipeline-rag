from __future__ import annotations

import structlog

from app.chat.memory import MemoryContext
from app.chat.schema import AnswerHistoryContext, HistoryPlanningContext
from app.common.text_utils import clip_head, clip_tail, join_non_blank, safe_text
from app.config import get_settings
from app.orchestrator.query_rewriter import ChatQueryRewriteService

logger = structlog.get_logger(__name__)


class HistoryBuilder:
    @staticmethod
    def build_planning_context(memory_ctx: MemoryContext) -> HistoryPlanningContext:
        payload = getattr(memory_ctx, "summary_payload", None)
        if not payload:
            return HistoryPlanningContext()
        return HistoryPlanningContext(
            goals=[payload.conversation_goal] if payload.conversation_goal else [],
            facts=list(payload.stable_facts or []),
            pending_questions=list(payload.pending_questions or []),
            retrieval_hints=list(payload.retrieval_hints or []),
        )

    @staticmethod
    def build_planning_history(memory_ctx, planning_ctx) -> str:
        settings = get_settings()
        structured = HistoryBuilder._build_structured_planning_history(planning_ctx)
        recent = safe_text(getattr(memory_ctx, "recent_transcript", ""))
        max_chars = max(1, settings.rag.planning_history_max_chars)
        if not recent.strip():
            return clip_head(structured, max_chars)
        recent_budget = min(max(max_chars // 2, int(max_chars * 0.65)), max_chars)
        recent_part = clip_tail(recent, recent_budget)
        structured_budget = max(0, max_chars - len(recent_part) - (2 if recent_part else 0))
        structured_part = clip_head(structured, structured_budget)
        return join_non_blank(structured_part, recent_part)

    @staticmethod
    def build_answer_context(question: str, answer_recent_transcript: str) -> AnswerHistoryContext:
        assembler = ChatQueryRewriteService()
        result = assembler._assemble_answer_history(question, answer_recent_transcript)
        return AnswerHistoryContext(**result.__dict__)

    @staticmethod
    def _build_structured_planning_history(ctx: HistoryPlanningContext) -> str:
        if not ctx:
            return ""
        builder: list[str] = []
        HistoryBuilder._append_section(builder, "会话目标", ctx.goals[0] if ctx.goals else "")
        HistoryBuilder._append_bullet_section(builder, "已确认事实", ctx.facts)
        HistoryBuilder._append_bullet_section(builder, "待跟进问题", ctx.pending_questions)
        HistoryBuilder._append_bullet_section(builder, "检索提示", ctx.retrieval_hints)
        return "\n".join(builder).strip()

    @staticmethod
    def _append_section(builder: list[str], title: str, content: str) -> None:
        if not content or not content.strip():
            return
        if builder:
            builder.append("")
        builder.append(f"【{title}】\n{content.strip()}")

    @staticmethod
    def _append_bullet_section(builder: list[str], title: str, values: list[str]) -> None:
        if not values:
            return
        filtered = [v for v in values if v and v.strip()]
        if not filtered:
            return
        if builder:
            builder.append("")
        builder.append(f"【{title}】")
        for item in filtered[:5]:
            builder.append(f"- {item.strip()}")
