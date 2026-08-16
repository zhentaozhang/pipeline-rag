"""Stub: Pydantic models placeholder until Phase 1 builds real tracer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatModelUsageTrace(BaseModel):
    stage: str = ""
    provider: str = ""
    model_name: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    estimated_cost: float = 0.0
    duration_ms: float = 0.0
    status: str = "success"
    finish_reason: str = ""
    timestamp: str = ""


class ChatLimitStats(BaseModel):
    llm_call_used: int = 0
    llm_call_run_limit: int = 0
    llm_call_thread_limit: int = 0
    tool_call_used: int = 0
    tool_call_run_limit: int = 0
    tool_call_thread_limit: int = 0
    limit_triggered: bool = False
    limit_reason: str = ""


class ChatDebugTrace(BaseModel):
    execution_mode: str = ""
    chat_mode: str = ""
    original_question: str = ""
    rewrite_question: str | None = None
    rewrite_sub_questions: list[Any] = Field(default_factory=list)
    retrieval_question: str = ""
    agent_question: str = ""
    navigation_decision: dict = Field(default_factory=dict)
    history_summary: str = ""
    long_term_summary: str = ""
    recent_history_transcript: str = ""
    answer_recent_transcript: str = ""
    answer_history_context: str = ""
    answer_history_follow_up_question: bool = False
    history_compression_applied: bool = False
    history_covered_exchange_id: int | None = None
    history_covered_exchange_count: int = 0
    history_compression_count: int = 0
    current_date_text: str = ""
    requires_fresh_search: bool = False
    requires_current_date_anchoring: bool = False
    retrieval_sub_questions: list[Any] = Field(default_factory=list)
    selected_document_id: str | None = None
    selected_task_id: str | None = None
    no_evidence_reply: str = ""
    route_decision: str = ""
    route_rename_decision: str = ""
    graph_result: str = ""
    graph_nodes: list[Any] = Field(default_factory=list)
    recommendation_questions: list[str] = Field(default_factory=list)
    retrieval_graph_contexts: list[Any] = Field(default_factory=list)
    retrieval_docs: list[Any] = Field(default_factory=list)
    memory_content: str = ""
    memory_type: str = ""
    tool_calls: list[Any] = Field(default_factory=list)
    agent_trajectory: list[Any] = Field(default_factory=list)
    model_usage: list[ChatModelUsageTrace] = Field(default_factory=list)
    limit_stats: ChatLimitStats | None = None
    prompt_content: str = ""
    rag_prompt: str = ""
    rag_system_prompt: str = ""
    rag_user_prompt: str = ""
    retrieval_notes: list[str] = Field(default_factory=list)
    used_channels: list[str] = Field(default_factory=list)
    limit_reason: str = ""
