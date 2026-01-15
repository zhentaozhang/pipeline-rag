from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Float, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import TimestampMixin
from app.db.session import Base

__all__ = [
    "ChatExchangeFeedback",
    "ChatModelUsageTrace",
    "ConversationChannelExecution",
    "ConversationRAGEvaluation",
    "ConversationRetrievalResult",
    "ConversationTraceStage",
    "RagEvaluationDataset",
]


class ConversationChannelExecution(Base, TimestampMixin):
    """RAG 通道执行记录"""

    __tablename__ = "pipeline_rag_chat_channel_execution"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        "dialogue_code", String(64), nullable=False, index=True
    )
    exchange_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sub_question_index: Mapped[int] = mapped_column(Integer, default=0)
    sub_question: Mapped[str] = mapped_column(Text, nullable=False)
    channel_type: Mapped[str] = mapped_column(String(32), nullable=False)

    execution_state: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    recalled_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    final_selected_count: Mapped[int] = mapped_column(Integer, default=0)

    avg_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    max_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    min_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    config_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)


class ConversationRetrievalResult(Base, TimestampMixin):
    """RAG 检索证据记录"""

    __tablename__ = "pipeline_rag_chat_retrieval_result"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        "dialogue_code", String(64), nullable=False, index=True
    )
    exchange_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sub_question_index: Mapped[int] = mapped_column(Integer, nullable=True)
    sub_question: Mapped[str] = mapped_column(Text, nullable=False)
    channel_type: Mapped[str] = mapped_column(String(32), nullable=True)
    channel_rank: Mapped[int] = mapped_column(Integer, nullable=True)
    rrf_rank: Mapped[int] = mapped_column(Integer, nullable=True)
    final_rank: Mapped[int] = mapped_column(Integer, nullable=True)
    original_score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=True)
    rrf_score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=True)
    rerank_score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=True)
    gate_passed: Mapped[int] = mapped_column(Integer, nullable=True)
    is_elevated: Mapped[int] = mapped_column(Integer, nullable=True)
    is_selected: Mapped[int] = mapped_column(Integer, nullable=True)
    selection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    document_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    chunk_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    chunk_no: Mapped[int] = mapped_column(Integer, nullable=True)
    parent_block_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    parent_block_no: Mapped[int] = mapped_column(Integer, nullable=True)
    section_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_text_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_char_count: Mapped[int] = mapped_column(Integer, nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)


class ConversationTraceStage(Base, TimestampMixin):
    """对话引擎生命周期阶段记录"""

    __tablename__ = "pipeline_rag_chat_exchange_trace_stage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        "dialogue_code", String(64), nullable=False, index=True
    )
    exchange_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage_code: Mapped[str] = mapped_column(String(64), nullable=False)
    stage_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    stage_order: Mapped[int] = mapped_column(Integer, nullable=True)
    stage_level: Mapped[int] = mapped_column(Integer, nullable=True)
    parent_stage_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    execution_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stage_state: Mapped[int] = mapped_column(Integer, nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)


class ChatModelUsageTrace(Base):
    """单次模型调用追踪记录"""

    __tablename__ = "chat_model_usage_trace"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    exchange_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stage_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    usage_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConversationRAGEvaluation(Base, TimestampMixin):
    """RAGAS 评估结果表 — 每条记录对应一次 RAG 对话的评估"""

    __tablename__ = "conversation_rag_evaluation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    exchange_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    faithfulness_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    answer_relevancy_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    context_precision_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)

    eval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    eval_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChatExchangeFeedback(Base, TimestampMixin):
    """用户点赞/踩反馈"""

    __tablename__ = "chat_exchange_feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    exchange_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default="default", server_default="default", nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False, comment="1=thumbs_up, -1=thumbs_down")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="可选评论文本")

    status: Mapped[int] = mapped_column(Integer, default=1)


class RagEvaluationDataset(Base, TimestampMixin):
    """人工标注与 Golden Dataset (供 Ragas 自动化测试使用的基准数据)"""

    __tablename__ = "rag_evaluation_dataset"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default="default", server_default="default", nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    ground_truth: Mapped[str] = mapped_column(Text, nullable=False)
    contexts: Mapped[str | None] = mapped_column(Text, nullable=True)  # 参考上下文 JSON
    exchange_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 来源对话
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="manual")  # user_feedback, manual
    status: Mapped[int] = mapped_column(Integer, default=1)

    # 评估结果
    generated_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    faithfulness_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    answer_relevancy_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    context_precision_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    context_recall_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    answer_correctness_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    eval_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
