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
    name="document.parse",
    max_retries=3,
    default_retry_delay=10,
)
def task_parse_document(self, doc_id: str, file_path: str) -> dict:
    """Step 1: 解析文档 → 提取纯文本 + 元信息 + 策略推荐"""
    from app.common.enums import (
        DocumentLogLevelEnum,
        DocumentOperatorTypeEnum,
        DocumentParseStatusEnum,
        DocumentStrategyStatusEnum,
        DocumentTaskEventTypeEnum,
    )
    from app.document.parser import DocumentParser

    logger.info("task parse started", doc_id=doc_id, task_id=self.request.id)
    _record_task(doc_id, "parse", self.request.id, DocumentTaskStatusEnum.RUNNING.value)
    _save_log(
        doc_id,
        self.request.id,
        DocumentTaskStageEnum.CONTENT_PARSE.value,
        DocumentTaskEventTypeEnum.START.value,
        DocumentLogLevelEnum.INFO.value,
        DocumentOperatorTypeEnum.SYSTEM.value,
        "system",
        "开始解析文档内容。",
        {"doc_id": doc_id, "file_path": file_path},
    )

    try:
        # 从 MinIO 下载文件到临时目录，因为 DocumentParser 需要本地路径
        async def _download_and_parse():
            import os
            import tempfile

            from app.infra.minio import download_bytes

            file_bytes = await download_bytes(file_path)
            suffix = os.path.splitext(file_path)[1] or ".tmp"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            try:
                parser = DocumentParser()
                return await parser.parse(tmp_path)
            finally:
                os.unlink(tmp_path)

        result = run_async(_download_and_parse())

        # 持久化解析文本到存储
        async def _save_parsed_text():
            try:
                from app.infra.minio import upload_file

                text_path = f"{doc_id}/parsed.txt"
                import os
                import tempfile

                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False, encoding="utf-8"
                ) as tmp:
                    tmp.write(result.text)
                    tmp_path = tmp.name
                await upload_file(text_path, tmp_path, "text/plain")
                os.unlink(tmp_path)
                logger.info("parsed text saved to storage", doc_id=doc_id, path=text_path)
            except Exception as e:
                logger.error(
                    "failed to save parsed text to storage",
                    doc_id=doc_id,
                    error=str(e),
                    exc_info=True,
                )

        run_async(_save_parsed_text())

        # 持久化结构节点
        structure_node_count = 0
        if result.nodes:
            from app.manage.service.document_structure_node_service import save_nodes

            async def _save_nodes():
                nonlocal structure_node_count
                try:
                    async with _get_mysql_session() as session, session.begin():
                        await save_nodes(session, doc_id, self.request.id, result.nodes)
                        structure_node_count = len(result.nodes)
                except Exception as e:
                    logger.error(
                        "failed to save document structure nodes in parser",
                        error=str(e),
                        exc_info=True,
                    )

            run_async(_save_nodes())

        # Update document with parse results (parseStatus, strategyStatus, charCount, tokenCount, etc.)
        async def _update_doc_after_parse():
            from sqlalchemy import update

            from app.db.models.document import Document as DocModel

            async with _get_mysql_session() as session, session.begin():
                stmt = (
                    update(DocModel)
                    .where(DocModel.doc_id == doc_id)
                    .values(
                        parse_status=DocumentParseStatusEnum.PARSE_SUCCESS.value,
                        strategy_status=DocumentStrategyStatusEnum.RECOMMENDED.value,
                        char_count=result.char_count,
                        token_count=result.token_count,
                        structure_level=result.structure_level,
                        content_quality_level=result.content_quality_level,
                        parse_text_path=f"{doc_id}/parsed.txt",
                        parse_error_msg=None,
                        last_parse_task_id=self.request.id,
                        structure_node_count=structure_node_count,
                    )
                )
                await session.execute(stmt)

        run_async(_update_doc_after_parse())

        _save_log(
            doc_id,
            self.request.id,
            DocumentTaskStageEnum.CONTENT_PARSE.value,
            DocumentTaskEventTypeEnum.COMPLETE.value,
            DocumentLogLevelEnum.INFO.value,
            DocumentOperatorTypeEnum.SYSTEM.value,
            "system",
            "文档解析完成。",
            {"char_count": len(result.text), "structure_node_count": structure_node_count},
        )

        _update_task_status(self.request.id, DocumentTaskStatusEnum.SUCCESS.value)
        _update_pipeline_stage(doc_id, DocumentPipelineStageEnum.PARSED.value)
    except Exception as e:
        _task_failed(self, doc_id, DocumentTaskStageEnum.CONTENT_PARSE.value, "文档解析失败。", e)
        return {"doc_id": doc_id}

    # 策略推荐 + 自动确认（可选后处理，失败不影响主流程）
    from app.manage.service.document_async_service import save_log as _save_log_fn

    async def _recommend_and_confirm_strategy():
        doc_internal_id: int | None = None
        try:
            from sqlalchemy import select as sa_select

            from app.db.models.document import DocumentStrategyPlan
            from app.manage.service.document_strategy_service import (
                confirm_strategy,
                recommend_strategy,
            )

            async with _get_mysql_session() as session, session.begin():
                await recommend_strategy(session, doc_id)
            async with _get_mysql_session() as session, session.begin():
                from app.db.models.document import Document as DocModel

                doc_row = await session.execute(
                    sa_select(DocModel.id).where(DocModel.doc_id == doc_id)
                )
                doc_internal_id = doc_row.scalar_one_or_none()
                if doc_internal_id:
                    plan_row = await session.execute(
                        sa_select(DocumentStrategyPlan.id)
                        .where(DocumentStrategyPlan.document_id == doc_internal_id)
                        .order_by(DocumentStrategyPlan.id.desc())
                        .limit(1)
                    )
                    plan_id = plan_row.scalar_one_or_none()
                    if plan_id:
                        await confirm_strategy(session, doc_id, plan_id, 0)
            async with _get_mysql_session() as db:
                await _save_log_fn(
                    db,
                    self.request.id,
                    doc_internal_id or 0,
                    DocumentTaskStageEnum.STRATEGY_ROUTE.value,
                    DocumentTaskEventTypeEnum.RECOMMEND_STRATEGY.value,
                    DocumentLogLevelEnum.INFO.value,
                    DocumentOperatorTypeEnum.SYSTEM.value,
                    "system",
                    "系统已生成并自动确认推荐策略。",
                    {"doc_id": doc_id},
                )
                await db.commit()
        except Exception as e:
            logger.error("strategy recommendation failed", error=str(e), exc_info=True)

    run_async(_recommend_and_confirm_strategy())

    return {
        "doc_id": doc_id,
        "text": result.text,
        "metadata": result.metadata,
        "file_type": result.file_type,
    }
