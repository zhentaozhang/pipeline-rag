import structlog

from app.celery_app import celery_app, run_async
from app.common.enums import (
    DocumentPipelineStageEnum,
    DocumentTaskStageEnum,
    DocumentTaskStatusEnum,
)
from app.document.tasks._base import (
    _get_mysql_session,
    _record_task,
    _save_log,
    _task_failed,
    _update_pipeline_stage,
    _update_task_status,
)

logger = structlog.get_logger(__name__)


@celery_app.task(
    bind=True,
    name="document.chunk",
    max_retries=3,
    default_retry_delay=10,
)
def task_chunk_document(self, parse_result: dict, doc_id: str) -> dict:
    """Step 2: 切块 → 生成 Chunk 列表"""
    from app.common.enums import (
        DocumentLogLevelEnum,
        DocumentOperatorTypeEnum,
        DocumentTaskEventTypeEnum,
    )

    logger.info("task chunk started", doc_id=doc_id, task_id=self.request.id)
    _record_task(doc_id, "chunk", self.request.id, DocumentTaskStatusEnum.RUNNING.value)
    _save_log(
        doc_id,
        self.request.id,
        DocumentTaskStageEnum.CHUNK_EXECUTE.value,
        DocumentTaskEventTypeEnum.START.value,
        DocumentLogLevelEnum.INFO.value,
        DocumentOperatorTypeEnum.SYSTEM.value,
        "system",
        "开始执行切块流水线。",
        None,
    )
    text = parse_result.get("text", "")

    async def _do_build():
        from app.manage.service.document_strategy_service import build_chunks

        async with _get_mysql_session() as db, db.begin():
            return await build_chunks(db, doc_id, text, self.request.id)

    try:
        child_chunk_dicts = run_async(_do_build())
        _save_log(
            doc_id,
            self.request.id,
            DocumentTaskStageEnum.CHUNK_EXECUTE.value,
            DocumentTaskEventTypeEnum.COMPLETE.value,
            DocumentLogLevelEnum.INFO.value,
            DocumentOperatorTypeEnum.SYSTEM.value,
            "system",
            "切块执行完成。",
            {"child_count": len(child_chunk_dicts)},
        )
        _update_task_status(self.request.id, DocumentTaskStatusEnum.SUCCESS.value)
        _update_pipeline_stage(doc_id, DocumentPipelineStageEnum.CHUNKED.value)
    except Exception as e:
        logger.error("task chunk failed", error=str(e), exc_info=True)
        _task_failed(self, doc_id, DocumentTaskStageEnum.CHUNK_EXECUTE.value, "切块执行失败。", e)

    return {"doc_id": doc_id, "chunks": child_chunk_dicts}
