"""
Celery 异步任务定义 — 文档处理流水线

任务链：parse → chunk → vectorize → index → profile（每步独立日志+状态追踪）
"""

import structlog

from app.celery_app import celery_app, run_async
from app.common.enums import DocumentPipelineStageEnum, DocumentTaskStageEnum
from app.document.tasks._base import (
    _compensate,
    _compensate_async,
    _get_mysql_session,
    _infer_stage,
    _update_document_failed,
    _update_document_failed_async,
)
from app.document.tasks._chunk import task_chunk_document
from app.document.tasks._index import task_index_document
from app.document.tasks._parse import task_parse_document
from app.document.tasks._profile import task_generate_profile
from app.document.tasks._vectorize import task_vectorize_document
from app.document.tasks.reconcile import (
    cleanup_traces,
    import_s3_documents,
    import_web_documents,
    reconcile_indexes,
)

logger = structlog.get_logger(__name__)


# ── 孤儿文档清理 ──────────────────────────────────────────────────────────


@celery_app.task(name="document.cleanup_orphans")
def cleanup_orphan_documents():
    """定时扫描停滞超时的文档，执行补偿 + 失败标记（避免误杀正常处理中的文档）"""

    async def _do():
        from datetime import datetime, timedelta

        from sqlalchemy import select

        from app.db.models.document import Document as DocModel

        # 仅针对超过 2 小时未更新且停留在中间处理状态（PARSED=1 到 VECTORIZED=3）的停滞文档
        # INDEXED=4 说明主要索引已完成，严禁清理
        stale_threshold = datetime.now() - timedelta(hours=2)
        async with _get_mysql_session() as db:
            stmt = (
                select(DocModel)
                .where(
                    DocModel.pipeline_stage.between(
                        DocumentPipelineStageEnum.PARSED.value,
                        DocumentPipelineStageEnum.VECTORIZED.value,
                    ),
                    DocModel.status == 1,
                    DocModel.updated_at < stale_threshold,
                )
                .order_by(DocModel.id.desc())
                .limit(100)
            )
            rows = (await db.execute(stmt)).scalars().all()

        for doc in rows:
            logger.warning(
                "stale orphaned document found, compensating",
                doc_id=doc.doc_id,
                stage=doc.pipeline_stage,
            )
            stage_map = {
                DocumentPipelineStageEnum.PARSED.value: DocumentTaskStageEnum.CHUNK_EXECUTE.value,
                DocumentPipelineStageEnum.CHUNKED.value: DocumentTaskStageEnum.VECTORIZE.value,
                DocumentPipelineStageEnum.VECTORIZED.value: DocumentTaskStageEnum.STORE_COMPLETE.value,
            }
            target_stage = stage_map.get(doc.pipeline_stage)
            if target_stage:
                await _compensate_async(doc.doc_id, target_stage)
                await _update_document_failed_async(
                    doc.doc_id, "文档处理停滞超时(>2h)，系统已执行补偿清理。"
                )

    run_async(_do())


def trigger_document_pipeline(doc_id: str, file_path: str) -> str:
    """
    触发完整文档处理流水线（任务链）。
    返回流水线的首个任务 ID。
    """
    from celery import chain

    pipeline = chain(
        task_parse_document.s(doc_id, file_path),
        task_chunk_document.s(doc_id),
        task_vectorize_document.s(doc_id),
        task_index_document.s(doc_id),
        task_generate_profile.s(doc_id),
    )
    result = pipeline.apply_async()
    logger.info("document pipeline triggered", doc_id=doc_id, task_id=result.id)
    return result.id  # type: ignore[no-any-return]


__all__ = [
    "task_parse_document",
    "task_chunk_document",
    "task_vectorize_document",
    "task_index_document",
    "task_generate_profile",
    "trigger_document_pipeline",
    "cleanup_orphan_documents",
    "reconcile_indexes",
    "import_s3_documents",
    "cleanup_traces",
    "import_web_documents",
    "_compensate",
    "_compensate_async",
    "_infer_stage",
    "_update_document_failed",
    "_update_document_failed_async",
    "celery_app",
]
