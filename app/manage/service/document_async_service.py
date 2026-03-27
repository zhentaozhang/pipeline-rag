"""
文档异步处理流水线服务
文档异步处理服务

职责:
- 提交文档处理流水线（parse→chunk→vectorize→index）
- 查询任务状态与进度
- 任务重试与错误处理
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import (
    DocumentLogLevelEnum,
    DocumentOperatorTypeEnum,
    DocumentTaskEventTypeEnum,
    DocumentTaskStageEnum,
)
from app.infra.id_generator import next_id

if TYPE_CHECKING:
    from app.db.models.document import DocumentTask
    from app.db.models.task_log import DocumentTaskLog

logger = structlog.get_logger(__name__)


async def submit_pipeline(doc_id: str, file_path: str) -> str:
    """提交完整文档处理流水线。返回流水线首个任务 ID。"""
    from app.document.tasks import trigger_document_pipeline

    task_id = trigger_document_pipeline(doc_id, file_path)
    logger.info("pipeline submitted", doc_id=doc_id, task_id=task_id)
    return task_id


async def save_log(
    db: AsyncSession,
    task_id: str,
    document_id: int,
    stage_type: int = DocumentTaskStageEnum.FILE_UPLOAD.value,
    event_type: int = DocumentTaskEventTypeEnum.START.value,
    log_level: int = DocumentLogLevelEnum.INFO.value,
    operator_type: int = DocumentOperatorTypeEnum.SYSTEM.value,
    operator_id: str = "system",
    content: str = "",
    detail: dict | None = None,
) -> DocumentTaskLog:
    from app.db.models.task_log import DocumentTaskLog as TaskLog

    record = TaskLog(
        id=next_id(),
        task_id=task_id,
        document_id=document_id,
        stage_type=stage_type,
        event_type=event_type,
        log_level=log_level,
        operator_type=operator_type,
        operator_id=operator_id or "system",
        content=content,
        detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
    )
    db.add(record)
    await db.flush()
    return record


async def record_task(
    db: AsyncSession,
    doc_id: str,
    stage: str,
    task_id: str,
    status: int = 0,
) -> DocumentTask:
    from app.db.models.document import DocumentTask as DocTask

    stmt = select(DocTask).where(DocTask.task_id == task_id)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        existing.status = status
        existing.stage = stage
        existing.error_msg = None
        await db.flush()
        return existing

    record = DocTask(
        id=next_id(),
        task_id=task_id,
        doc_id=doc_id,
        stage=stage,
        status=status,
    )
    db.add(record)
    await db.flush()
    return record


async def update_status(
    db: AsyncSession,
    task_id: str,
    status: int,
    error_msg: str | None = None,
) -> None:
    from app.db.models.document import DocumentTask as DocTask

    stmt = select(DocTask).where(DocTask.task_id == task_id)
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task:
        task.status = status
        if error_msg:
            task.error_msg = error_msg


async def list_by_doc(db: AsyncSession, doc_id: str) -> list:
    from app.db.models.document import DocumentTask as DocTask

    stmt = select(DocTask).where(DocTask.doc_id == doc_id).order_by(DocTask.id.desc())
    return (await db.execute(stmt)).scalars().all()
