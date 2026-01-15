from __future__ import annotations

from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import TimestampMixin
from app.db.session import Base


class ShadowRouterRecord(Base, TimestampMixin):
    """影子路由观测记录（用户手动选文档时，系统静默跑路由并记录对比结果）"""

    __tablename__ = "shadow_router_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    user_selected_doc_ids: Mapped[str] = mapped_column(Text, nullable=True)  # JSON
    system_routed_doc_ids: Mapped[str] = mapped_column(Text, nullable=True)  # JSON
    hit: Mapped[bool] = mapped_column(Boolean, nullable=True)  # 系统路由是否命中用户选择
    confidence: Mapped[float] = mapped_column(nullable=True)
    candidate_rank: Mapped[int] = mapped_column(Integer, nullable=True)


class KnowledgeRouteTrace(Base, TimestampMixin):
    """完整记录路由决策的轨迹"""

    __tablename__ = "pipeline_rag_knowledge_route_trace"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    exchange_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=True)
    rewrite_question: Mapped[str] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=True)  # shadow or auto
    top_scopes_json: Mapped[str] = mapped_column(Text, nullable=True)
    top_topics_json: Mapped[str] = mapped_column(Text, nullable=True)
    top_documents_json: Mapped[str] = mapped_column(Text, nullable=True)
    selected_document_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    hit_selected_document: Mapped[int] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=True)
    route_status: Mapped[int] = mapped_column(
        Integer, nullable=True
    )  # 1: success, 2: low confidence, 3: failed
    error_msg: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1)
