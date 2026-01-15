from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class GraphCheckpoint(Base):
    __tablename__ = "graph_checkpoint"

    checkpoint_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(128), nullable=True)
    next_node_id: Mapped[str] = mapped_column(String(128), nullable=True)
    state_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)


class Checkpoint(Base):
    """LangGraph 原生 checkpoint 表（由 AIOMySQLSaver 管理）"""

    __tablename__ = "checkpoint"

    thread_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checkpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkpoint_metadata: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)


class CheckpointBlob(Base):
    """LangGraph checkpoint_blobs 表"""

    __tablename__ = "checkpoint_blobs"

    thread_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    channel: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[str] = mapped_column(String(128), primary_key=True)
    type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    blob: Mapped[str | None] = mapped_column(Text, nullable=True)


class CheckpointWrite(Base):
    """LangGraph checkpoint_writes 表"""

    __tablename__ = "checkpoint_writes"

    thread_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    task_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str | None] = mapped_column(String(128), nullable=True)
    type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    blob: Mapped[str | None] = mapped_column(Text, nullable=True)


class GraphThread(Base):
    __tablename__ = "graph_thread"

    thread_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    thread_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_released: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
