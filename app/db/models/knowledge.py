from __future__ import annotations

from decimal import Decimal

from sqlalchemy import BigInteger, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import TimestampMixin
from app.db.session import Base


class KnowledgeScope(Base, TimestampMixin):
    """知识域（Scope）"""

    __tablename__ = "pipeline_rag_knowledge_scope_node"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default="default", server_default="default", nullable=False, index=True
    )
    scope_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_scope_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[str | None] = mapped_column(Text, nullable=True)
    examples: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=True)


class KnowledgeTopic(Base, TimestampMixin):
    """知识主题（Topic）"""

    __tablename__ = "pipeline_rag_knowledge_topic_node"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default="default", server_default="default", nullable=False, index=True
    )
    topic_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    topic_name: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[str | None] = mapped_column(Text, nullable=True)
    examples: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_shape: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_preference: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=True)


class TopicDocumentRelation(Base, TimestampMixin):
    """知识主题与文档的多对多关联及打分"""

    __tablename__ = "pipeline_rag_topic_document_relation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    topic_code: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    relation_score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=True)
    relation_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1)  # 1: active, 0: inactive
