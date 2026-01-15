from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import TimestampMixin
from app.db.session import Base


class Document(Base, TimestampMixin):
    """文档主表"""

    __tablename__ = "pipeline_rag_document"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default="default", server_default="default", nullable=False, index=True
    )
    doc_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    document_name: Mapped[str] = mapped_column(String(256), nullable=False)
    original_file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    file_type: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=True)
    storage_type: Mapped[int] = mapped_column(Integer, nullable=True)
    bucket_name: Mapped[str] = mapped_column(String(128), nullable=True)
    object_name: Mapped[str] = mapped_column(String(256), nullable=True)
    object_url: Mapped[str] = mapped_column(String(512), nullable=True)
    parse_status: Mapped[int] = mapped_column(Integer, default=0)
    strategy_status: Mapped[int] = mapped_column(Integer, nullable=True)
    index_status: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=True)
    structure_level: Mapped[int] = mapped_column(Integer, nullable=True)
    content_quality_level: Mapped[int] = mapped_column(Integer, nullable=True)
    parse_text_path: Mapped[str] = mapped_column(String(512), nullable=True)
    parse_error_msg: Mapped[str] = mapped_column(Text, nullable=True)
    knowledge_scope_code: Mapped[str] = mapped_column(String(64), nullable=True)
    knowledge_scope_name: Mapped[str] = mapped_column(String(128), nullable=True)
    business_category: Mapped[str] = mapped_column(String(128), nullable=True)
    document_tags: Mapped[str] = mapped_column(String(512), nullable=True)
    current_plan_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    last_parse_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_index_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    structure_node_count: Mapped[int] = mapped_column(Integer, nullable=True)
    pipeline_stage: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=True)

    chunks: Mapped[list[DocumentChunk]] = relationship(back_populates="document")
    tasks: Mapped[list[DocumentTask]] = relationship(back_populates="document")


class DocumentProfile(Base, TimestampMixin):
    """文档画像信息"""

    __tablename__ = "pipeline_rag_document_profile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pipeline_rag_document.id"), unique=True, nullable=False
    )
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    profile_status: Mapped[int] = mapped_column(Integer, default=1)  # 1: pending, 2: completed
    document_summary: Mapped[str] = mapped_column(Text, nullable=True)
    document_type: Mapped[str] = mapped_column(String(64), nullable=True)
    core_topics: Mapped[str] = mapped_column(Text, nullable=True)  # JSON array
    example_questions: Mapped[str] = mapped_column(Text, nullable=True)  # JSON array
    graph_friendly: Mapped[int | None] = mapped_column(Integer, default=0)
    supports_graph_outline: Mapped[int | None] = mapped_column(Integer, default=0)
    supports_item_lookup: Mapped[int | None] = mapped_column(Integer, default=0)
    supports_graph_assist: Mapped[int | None] = mapped_column(Integer, default=1)
    knowledge_domain: Mapped[str] = mapped_column(String(128), nullable=True)
    knowledge_scope_code: Mapped[str] = mapped_column(String(64), nullable=True)
    knowledge_scope_name: Mapped[str] = mapped_column(String(128), nullable=True)
    business_category: Mapped[str] = mapped_column(String(128), nullable=True)
    document_tags: Mapped[str] = mapped_column(String(256), nullable=True)
    profile_source: Mapped[str] = mapped_column(String(64), default="auto", nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1)  # 1: active, 0: inactive

    document: Mapped[Document] = relationship()


class DocumentChunk(Base, TimestampMixin):
    """文档分块表（存储元信息，向量存 PGVector，关键词存 ES）"""

    __tablename__ = "pipeline_rag_document_chunk"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default="default", server_default="default", nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pipeline_rag_document.id"), nullable=False
    )
    chunk_no: Mapped[int] = mapped_column(Integer, nullable=True)
    source_type: Mapped[int] = mapped_column(Integer, nullable=True)
    section_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    structure_node_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    structure_node_type: Mapped[int] = mapped_column(Integer, nullable=True)
    canonical_path: Mapped[str] = mapped_column(Text, nullable=True)
    item_index: Mapped[int] = mapped_column(Integer, nullable=True)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=True)
    vector_status: Mapped[int] = mapped_column(Integer, nullable=True)
    vector_store_type: Mapped[int] = mapped_column(Integer, nullable=True)
    vector_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    parent_block_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=True)

    document: Mapped[Document] = relationship(back_populates="chunks")


class DocumentTask(Base, TimestampMixin):
    """文档异步处理任务记录"""

    __tablename__ = "document_task"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    doc_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("pipeline_rag_document.doc_id"), nullable=False
    )
    task_type: Mapped[str] = mapped_column(String(32), nullable=True)  # parse/chunk/vectorize
    stage: Mapped[str] = mapped_column(String(32), nullable=True)
    status: Mapped[int] = mapped_column(
        Integer, default=0
    )  # 0: pending, 1: running, 2: success, 3: failed
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str] = mapped_column(String(128), nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    document: Mapped[Document] = relationship(back_populates="tasks")


class PipelineRAGDocumentTask(Base, TimestampMixin):
    """文档异步处理任务（table=pipeline_rag_document_task）"""

    __tablename__ = "pipeline_rag_document_task"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    plan_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    task_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_stage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trigger_source: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strategy_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cost_millis: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    ext_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)


class DocumentStrategyPlan(Base, TimestampMixin):
    """文档切块策略计划（两阶段推荐核心表）"""

    __tablename__ = "pipeline_rag_document_strategy_plan"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=True)
    plan_source: Mapped[int] = mapped_column(Integer, nullable=True)  # 1: System, 2: User
    plan_status: Mapped[int] = mapped_column(
        Integer, nullable=True
    )  # 1: Pending Confirm, 2: Confirmed
    strategy_count: Mapped[int] = mapped_column(Integer, nullable=True)
    strategy_snapshot: Mapped[str] = mapped_column(Text, nullable=True)
    recommend_reason: Mapped[str] = mapped_column(Text, nullable=True)
    adjust_note: Mapped[str] = mapped_column(Text, nullable=True)
    confirm_user_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    confirm_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)


class DocumentStrategyStep(Base, TimestampMixin):
    """文档策略执行步骤"""

    __tablename__ = "pipeline_rag_document_strategy_step"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    step_no: Mapped[int] = mapped_column(Integer, nullable=True)
    pipeline_type: Mapped[str] = mapped_column(String(64), nullable=True)
    strategy_type: Mapped[int] = mapped_column(
        Integer, nullable=True
    )  # 1: Structure, 2: Recursive, 3: Semantic, 4: LLM
    strategy_role: Mapped[int] = mapped_column(
        Integer, nullable=True
    )  # 1: Main, 2: Fallback, 3: Optimize, 4: Enhance
    source_type: Mapped[int] = mapped_column(Integer, nullable=True)
    execute_status: Mapped[int] = mapped_column(Integer, nullable=True)
    recommend_reason: Mapped[str] = mapped_column(Text, nullable=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)


class DocumentParentBlock(Base, TimestampMixin):
    """文档父块（大块实体，用于RAG精准提取结构上下文）"""

    __tablename__ = "pipeline_rag_document_parent_block"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    parent_no: Mapped[int] = mapped_column(Integer, nullable=True)
    source_type: Mapped[int] = mapped_column(Integer, nullable=True)
    section_path: Mapped[str] = mapped_column(Text, nullable=True)
    structure_node_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    structure_node_type: Mapped[int] = mapped_column(Integer, nullable=True)
    canonical_path: Mapped[str] = mapped_column(Text, nullable=True)
    item_index: Mapped[int] = mapped_column(Integer, nullable=True)
    parent_text: Mapped[str] = mapped_column(Text, nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=True)
    child_count: Mapped[int] = mapped_column(Integer, nullable=True)
    start_chunk_no: Mapped[int] = mapped_column(Integer, nullable=True)
    end_chunk_no: Mapped[int] = mapped_column(Integer, nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)


class DocumentStructureNode(Base, TimestampMixin):
    """文档结构树节点（持久化图谱数据）"""

    __tablename__ = "pipeline_rag_document_structure_node"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    parse_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    node_no: Mapped[int] = mapped_column(Integer, nullable=True)
    node_type: Mapped[int] = mapped_column(Integer, nullable=True)
    parent_node_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    prev_sibling_node_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    next_sibling_node_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=True)
    node_code: Mapped[str] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=True)
    anchor_text: Mapped[str] = mapped_column(Text, nullable=True)
    canonical_path: Mapped[str] = mapped_column(Text, nullable=True)
    section_path: Mapped[str] = mapped_column(Text, nullable=True)
    content_text: Mapped[str] = mapped_column(Text, nullable=True)
    item_index: Mapped[int] = mapped_column(Integer, nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1)
