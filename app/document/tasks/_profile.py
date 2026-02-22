import structlog

from app.celery_app import celery_app, run_async
from app.common.enums import DocumentPipelineStageEnum, DocumentTaskStatusEnum
from app.document.tasks._base import (
    _get_mysql_session,
    _record_task,
    _update_pipeline_stage,
    _update_task_status,
)

logger = structlog.get_logger(__name__)


@celery_app.task(
    bind=True,
    name="document.profile",
    max_retries=2,
    default_retry_delay=10,
)
def task_generate_profile(self, index_result: dict, doc_id: str) -> dict:
    """Step 5: 流水线结束自动生成文档画像"""
    logger.info("task profile started", doc_id=doc_id, task_id=self.request.id)
    _record_task(doc_id, "profile", self.request.id, DocumentTaskStatusEnum.RUNNING.value)

    async def _do_generate():
        from app.infra.pg import close_pg, init_pg
        from app.manage.service.document_profile_service import generate_profile
        from app.manage.service.storage_service import download_object

        await init_pg()
        try:
            text_bytes = await download_object(f"{doc_id}/parsed.txt")
            if not text_bytes:
                logger.warning("no parsed text available for profile", doc_id=doc_id)
                return {"doc_id": doc_id, "profile_status": "skipped"}

            async with _get_mysql_session() as db:
                await generate_profile(db, doc_id, text_bytes.decode("utf-8"))

            logger.info("profile generation completed", doc_id=doc_id)
            return {"doc_id": doc_id, "profile_status": "completed"}
        except Exception as e:
            logger.error("profile generation failed", doc_id=doc_id, error=str(e), exc_info=True)
            return {"doc_id": doc_id, "profile_status": "failed", "error": str(e)}
        finally:
            await close_pg()

    try:
        result = run_async(_do_generate())
        if result.get("profile_status") == "failed":
            _update_task_status(
                self.request.id, DocumentTaskStatusEnum.FAILED.value, result.get("error")
            )
        else:
            _update_task_status(self.request.id, DocumentTaskStatusEnum.SUCCESS.value)
            _update_pipeline_stage(doc_id, DocumentPipelineStageEnum.PROFILED.value)
        return result  # type: ignore[no-any-return]
    except Exception as e:
        _update_task_status(self.request.id, DocumentTaskStatusEnum.FAILED.value, str(e))
        self.retry(exc=e)
        return {}
