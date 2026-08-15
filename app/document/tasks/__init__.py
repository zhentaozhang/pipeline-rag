"""
Celery 异步任务定义 — 文档处理流水线

任务链：parse → chunk → vectorize → index → profile（每步独立日志+状态追踪）
"""

import structlog

from app.celery_app import celery_app, run_async
from app.common.enums import DocumentPipelineStageEnum, DocumentTaskStageEnum
from app.document.tasks._base import (
    _compensate,
    _get_mysql_session,
    _infer_stage,
    _update_document_failed,
)
from app.document.tasks._chunk import task_chunk_document
from app.document.tasks._index import task_index_document
from app.document.tasks._parse import task_parse_document
from app.document.tasks._profile import task_generate_profile
from app.document.tasks._vectorize import task_vectorize_document
from app.document.tasks.reconcile import (
    import_s3_documents,
    import_web_documents,
    reconcile_indexes,
)

logger = structlog.get_logger(__name__)


# ── 孤儿文档清理 ──────────────────────────────────────────────────────────


@celery_app.task(name="document.cleanup_orphans")
def cleanup_orphan_documents():
    """定时扫描异常状态的文档，执行补偿 + 重试"""

    async def _do():
        from sqlalchemy import select

        from app.db.models.document import Document as DocModel

        async with _get_mysql_session() as db:
            stmt = (
                select(DocModel)
                .where(
                    DocModel.pipeline_stage.between(
                        DocumentPipelineStageEnum.PARSED.value,
                        DocumentPipelineStageEnum.INDEXED.value,
                    ),
                    DocModel.status == 1,
                )
                .order_by(DocModel.id.desc())
            )
            rows = (await db.execute(stmt)).scalars().all()

        for doc in rows:
            logger.warning("orphaned document found", doc_id=doc.doc_id, stage=doc.pipeline_stage)
            stage_map = {
                1: DocumentTaskStageEnum.CHUNK_EXECUTE.value,
                2: DocumentTaskStageEnum.VECTORIZE.value,
                3: DocumentTaskStageEnum.STORE_COMPLETE.value,
                4: DocumentTaskStageEnum.STORE_COMPLETE.value,
            }
            _compensate(doc.doc_id, stage_map.get(doc.pipeline_stage))

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
    "import_web_documents",
    "_compensate",
    "_infer_stage",
    "_update_document_failed",
    "celery_app",
]
