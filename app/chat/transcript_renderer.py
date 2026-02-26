"""
TranscriptRenderer — 对话历史文本格式化工具
"""

import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# ── Local constants (mirrored from memory.py to avoid circular import) ──
_MAX_QUESTION_LENGTH = 160
_MAX_ANSWER_LENGTH = 320
MAX_QUESTION_LENGTH = _MAX_QUESTION_LENGTH
MAX_ANSWER_LENGTH = _MAX_ANSWER_LENGTH


def clip_text(text: str, max_chars: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(0, max_chars - 1)] + "…"


def clip_recent_transcript(text: str, max_chars: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    start_index = max(0, len(normalized) - max(0, max_chars - 1))
    return "…" + normalized[start_index:]


class HistoryTurn:
    __slots__ = ("question", "answer")

    def __init__(self, question: str, answer: str) -> None:
        self.question = question
        self.answer = answer


class TranscriptRenderer:
    """对话历史渲染器，负责将结构化对话数据格式化为 Prompt 文本。"""

    @staticmethod
    def render_recent_transcript(turns: list[HistoryTurn]) -> str:
        if not turns:
            return ""
        builder = ["【最近对话原文】"]
        for t in turns:
            if t.question:
                builder.append("用户：" + clip_text(t.question, _MAX_QUESTION_LENGTH))
            if t.answer:
                builder.append("助手：" + clip_text(t.answer, _MAX_ANSWER_LENGTH))
        max_chars = settings.memory.max_window_chars or 2200
        return clip_recent_transcript("\n".join(builder), max_chars)

    @staticmethod
    def render_answer_recent_transcript(turns: list[HistoryTurn]) -> str:
        if not turns:
            return ""
        builder = ["【最近相关对话】"]
        for t in turns:
            if t.question:
                builder.append("用户：" + clip_text(t.question, _MAX_QUESTION_LENGTH))
        max_chars = settings.rag.answer_history_max_chars or 1000
        return clip_recent_transcript("\n".join(builder), max_chars)

    @staticmethod
    def render_compression_transcript(batch: list) -> str:
        builder = []
        for exchange in batch:
            if exchange.question:
                builder.append("用户：" + clip_text(exchange.question, _MAX_QUESTION_LENGTH))
            if exchange.answer:
                builder.append("助手：" + clip_text(exchange.answer, _MAX_ANSWER_LENGTH))
        return "\n".join(builder)

    @staticmethod
    def assemble_history(long_term_summary: str, recent_transcript: str) -> str:
        parts = [p for p in (long_term_summary, recent_transcript) if p and p.strip()]
        return "\n\n".join(parts)
