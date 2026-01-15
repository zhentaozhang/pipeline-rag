from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import TimestampMixin
from app.db.session import Base


class ConversationSession(Base, TimestampMixin):
    """会话表（对应 conversation_session）"""

    __tablename__ = "conversation_session"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default="default", server_default="default", nullable=False, index=True
    )
    conversation_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=True)
    chat_mode: Mapped[str] = mapped_column(String(32), default="auto")
    memory_strategy: Mapped[str] = mapped_column(String(32), default="summary_compression")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)


class ChatDialogue(Base, TimestampMixin):
    """对话记录（table=pipeline_rag_chat_dialogue）"""

    __tablename__ = "pipeline_rag_chat_dialogue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        "dialogue_code", String(64), nullable=False, index=True
    )
    session_status: Mapped[int | None] = mapped_column("dialogue_stage", Integer, nullable=True)
    chat_mode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selected_document_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    selected_document_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)


class ConversationExchange(Base, TimestampMixin):
    """单轮对话记录（table=pipeline_rag_chat_exchange）"""

    __tablename__ = "pipeline_rag_chat_exchange"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        "dialogue_code", String(64), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column("user_prompt", Text, nullable=False)
    answer: Mapped[str] = mapped_column("reply_content", Text, nullable=True)
    thinking_steps: Mapped[str | None] = mapped_column("reasoning_note_list", Text, nullable=True)
    references: Mapped[str | None] = mapped_column("source_snapshot_list", Text, nullable=True)
    recommendations: Mapped[str | None] = mapped_column(
        "followup_suggestion_list", Text, nullable=True
    )
    used_tools: Mapped[str | None] = mapped_column("tool_trace_list", Text, nullable=True)
    debug_trace_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    execution_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    turn_status: Mapped[int | None] = mapped_column("exchange_state", Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column("finish_note", Text, nullable=True)
    first_response_time_ms: Mapped[int | None] = mapped_column(
        "first_token_latency_ms", BigInteger, nullable=True
    )
    total_response_time_ms: Mapped[int | None] = mapped_column(
        "total_latency_ms", BigInteger, nullable=True
    )
    status: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)


class ConversationMemory(Base, TimestampMixin):
    """会话记忆（table=pipeline_rag_chat_memory_summary）"""

    __tablename__ = "pipeline_rag_chat_memory_summary"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        "dialogue_code", String(64), nullable=False, index=True
    )
    covered_exchange_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    covered_exchange_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compression_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_source_edit_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)
