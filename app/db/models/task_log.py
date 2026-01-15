from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class DocumentTaskLog(Base):
    __tablename__ = "pipeline_rag_document_task_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    stage_type: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[int] = mapped_column(Integer, nullable=False)
    log_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    operator_type: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    operator_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=True)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
