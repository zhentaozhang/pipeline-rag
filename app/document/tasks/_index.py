import structlog

from app.celery_app import celery_app, run_async
from app.common.enums import DocumentPipelineStageEnum, DocumentTaskStageEnum
from app.document.tasks._base import (
    _get_mysql_session,
    _record_task,
    _save_log,
    _task_failed,
    _update_pipeline_stage,
    _update_task_status,
)

logger = structlog.get_logger(__name__)


async def _update_index_build_result_async(
    doc_id: str,
    index_status: int,
    task_status: int,
    error_msg: str | None = None,
    task_id: str | None = None,
) -> None:
    """索引构建完成后更新 Document.index_status 和 PipelineRAGDocumentTask.task_status (异步版本)"""
    from datetime import datetime

    from sqlalchemy import select

    from app.db.models.document import Document, PipelineRAGDocumentTask

    async with _get_mysql_session() as db, db.begin():
        stmt = select(Document).where(Document.doc_id == doc_id)
        doc = (await db.execute(stmt)).scalar_one_or_none()
        if doc:
            doc.index_status = index_status
            doc.last_index_task_id = task_id
            # 更新最近一条 BUILD_INDEX 类型的 PipelineRAGDocumentTask
            task_stmt = (
                select(PipelineRAGDocumentTask)
                .where(
                    PipelineRAGDocumentTask.document_id == doc.id,
                    PipelineRAGDocumentTask.task_type == 2,
                )
                .order_by(PipelineRAGDocumentTask.id.desc())
                .limit(1)
            )
            task = (await db.execute(task_stmt)).scalar_one_or_none()
            if task:
                task.task_status = task_status
                if error_msg:
                    task.error_msg = error_msg
                task.finish_time = datetime.now()


def _update_index_build_result(
    doc_id: str,
    index_status: int,
    task_status: int,
    error_msg: str | None = None,
    task_id: str | None = None,
) -> None:
    """索引构建完成后更新 Document.index_status 和 PipelineRAGDocumentTask.task_status (兼容同步与异步)"""
    from app.document.tasks._base import _safe_dispatch

    _safe_dispatch(
        _update_index_build_result_async(doc_id, index_status, task_status, error_msg, task_id)
    )


@celery_app.task(
    bind=True,
    name="document.index",
    max_retries=3,
    default_retry_delay=10,
)
def task_index_document(self, vectorize_result: dict, doc_id: str) -> dict:
    """Step 4: 关键词索引 → 写入 Elasticsearch"""
    from app.common.enums import (
        DocumentIndexStatusEnum,
        DocumentLogLevelEnum,
        DocumentOperatorTypeEnum,
        DocumentTaskEventTypeEnum,
        DocumentTaskStatusEnum,
    )
    from app.infra.es import init_es

    logger.info("task index started", doc_id=doc_id, task_id=self.request.id)
    _record_task(doc_id, "index", self.request.id, DocumentTaskStatusEnum.RUNNING.value)
    _save_log(
        doc_id,
        self.request.id,
        DocumentTaskStageEnum.STORE_COMPLETE.value,
        DocumentTaskEventTypeEnum.START.value,
        DocumentLogLevelEnum.INFO.value,
        DocumentOperatorTypeEnum.SYSTEM.value,
        "system",
        "开始写入 ES 关键词索引。",
        None,
    )

    chunk_dicts = vectorize_result.get("chunks", [])

    async def _do_index():
        await init_es()
        from app.config import get_settings as _gs
        from app.infra.neo4j import init_neo4j

        if _gs().neo4j.enabled:
            await init_neo4j()

        try:
            from sqlalchemy import select

            from app.db.models.document import Document, DocumentProfile
            from app.db.models.knowledge import KnowledgeScope
            from app.document.chunker import Chunk
            from app.document.indexer import DocumentIndexer

            doc_info = {}
            doc_internal_id = None
            async with _get_mysql_session() as db:
                stmt = (
                    select(
                        Document.id,
                        Document.document_name,
                        Document.document_tags,
                        Document.tenant_id,
                        KnowledgeScope.scope_code,
                        KnowledgeScope.scope_name,
                        DocumentProfile.business_category,
                    )
                    .outerjoin(
                        KnowledgeScope, Document.knowledge_scope_code == KnowledgeScope.scope_code
                    )
                    .outerjoin(DocumentProfile, Document.id == DocumentProfile.document_id)
                    .where(Document.doc_id == doc_id)
                )
                res = await db.execute(stmt)
                row = res.first()
                if row:
                    doc_internal_id = row.id
                    doc_info = {
                        "id": row.id,
                        "title": row.document_name or "",
                        "tags": row.document_tags or "",
                        "scope_code": row.scope_code or "",
                        "scope_name": row.scope_name or "",
                        "business_category": row.business_category or "",
                        "tenant_id": getattr(row, "tenant_id", "default"),
                    }

            chunks = [Chunk(**c) for c in chunk_dicts]
            if doc_internal_id:
                for c in chunks:
                    if not getattr(c, "document_id", None):
                        c.document_id = doc_internal_id

            indexer = DocumentIndexer()

            await indexer.index_to_es(
                chunks,
                doc_title=doc_info.get("title", ""),
                scope_code=doc_info.get("scope_code", ""),
                scope_name=doc_info.get("scope_name", ""),
                business_category=doc_info.get("business_category", ""),
                document_tags=doc_info.get("tags", ""),
                tenant_id=doc_info.get("tenant_id", "default"),
                task_id=self.request.id,
                document_id=doc_internal_id,
            )

            # 这里新加入了 Neo4j 图谱节点注入
            await indexer.index_nodes_to_neo4j(doc_id)

            return len(chunks)
        except Exception as e:
            logger.error("index pipeline failed", error=str(e), exc_info=True)
            raise

    try:
        if not chunk_dicts:
            raise ValueError(f"文档切块列表为空，无法构建关键词与图谱索引: doc_id={doc_id}")
        count = run_async(_do_index())
        if count > 0:
            _save_log(
                doc_id,
                self.request.id,
                DocumentTaskStageEnum.STORE_COMPLETE.value,
                DocumentTaskEventTypeEnum.COMPLETE.value,
                DocumentLogLevelEnum.INFO.value,
                DocumentOperatorTypeEnum.SYSTEM.value,
                "system",
                "索引构建完成。",
                {"chunk_count": count},
            )
            _update_task_status(self.request.id, DocumentTaskStatusEnum.SUCCESS.value)
            _update_pipeline_stage(doc_id, DocumentPipelineStageEnum.INDEXED.value)
            _update_index_build_result(
                doc_id,
                DocumentIndexStatusEnum.BUILD_SUCCESS.value,
                DocumentTaskStatusEnum.SUCCESS.value,
                task_id=self.request.id,
            )
        else:
            _save_log(
                doc_id,
                self.request.id,
                DocumentTaskStageEnum.STORE_COMPLETE.value,
                DocumentTaskEventTypeEnum.FAILED.value,
                DocumentLogLevelEnum.ERROR.value,
                DocumentOperatorTypeEnum.SYSTEM.value,
                "system",
                "索引构建返回 0 chunks。",
                None,
            )
            _update_task_status(
                self.request.id, DocumentTaskStatusEnum.FAILED.value, "index returned 0 chunks"
            )
            _update_index_build_result(
                doc_id,
                DocumentIndexStatusEnum.BUILD_FAILED.value,
                DocumentTaskStatusEnum.FAILED.value,
            )
        return {"doc_id": doc_id, "indexed_count": count}
    except Exception as e:
        _update_index_build_result(
            doc_id,
            DocumentIndexStatusEnum.BUILD_FAILED.value,
            DocumentTaskStatusEnum.FAILED.value,
            str(e),
        )
        _task_failed(self, doc_id, DocumentTaskStageEnum.STORE_COMPLETE.value, "索引构建失败。", e)
        return {"doc_id": doc_id, "indexed_count": 0}
