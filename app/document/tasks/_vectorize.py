import structlog

from app.celery_app import celery_app, run_async
from app.common.enums import (
    DocumentLogLevelEnum,
    DocumentOperatorTypeEnum,
    DocumentPipelineStageEnum,
    DocumentTaskEventTypeEnum,
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


async def _save_mysql_document_chunks_async(doc_id: str, chunks: list, task_id: str) -> None:
    """向量化完成后将 Chunk 元信息写入 MySQL pipeline_rag_document_chunk (异步版本)"""
    from sqlalchemy import delete as sa_delete
    from sqlalchemy import select

    from app.db.models.document import Document, DocumentChunk

    async with _get_mysql_session() as db, db.begin():
        doc = (
            await db.execute(select(Document).where(Document.doc_id == doc_id))
        ).scalar_one_or_none()
        if not doc:
            return

        # 幂等：先删旧 chunk 元数据，避免 pipeline 重跑后累积重复
        await db.execute(sa_delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))

        from app.common.utils import stable_id_to_int

        target_chunks = [
            c for c in chunks if getattr(c, "chunk_type", "child") != "parent"
        ] or chunks
        chunk_models = []
        for c in target_chunks:
            chunk_id_int = stable_id_to_int(c.chunk_id)
            parent_block_id = stable_id_to_int(c.parent_chunk_id) if c.parent_chunk_id else None
            chunk_models.append(
                DocumentChunk(
                    id=chunk_id_int,
                    document_id=doc.id,
                    chunk_no=c.chunk_index,
                    source_type=0,
                    section_path=c.section_path,
                    structure_node_id=c.structure_node_id,
                    structure_node_type=c.structure_node_type,
                    canonical_path=c.canonical_path or "",
                    item_index=c.item_index,
                    chunk_text=c.content,
                    char_count=len(c.content),
                    token_count=c.token_count,
                    vector_status=3,
                    vector_store_type=1,
                    task_id=task_id,
                    plan_id=doc.current_plan_id,
                    parent_block_id=parent_block_id,
                    status=1,
                )
            )
            db.add_all(chunk_models)


def _save_mysql_document_chunks(doc_id: str, chunks: list, task_id: str) -> None:
    """向量化完成后将 Chunk 元信息写入 MySQL pipeline_rag_document_chunk (兼容独立调用)"""
    from app.document.tasks._base import _safe_dispatch

    _safe_dispatch(_save_mysql_document_chunks_async(doc_id, chunks, task_id))


@celery_app.task(
    bind=True,
    name="document.vectorize",
    max_retries=3,
    default_retry_delay=30,
)
def task_vectorize_document(self, chunk_result: dict, doc_id: str) -> dict:
    """Step 3: 向量化 → 写入 PGVector"""
    from app.document.chunker import Chunk
    from app.document.vectorizer import VectorizerService

    logger.info("task vectorize started", doc_id=doc_id, task_id=self.request.id)
    _record_task(doc_id, "vectorize", self.request.id, DocumentTaskStatusEnum.RUNNING.value)
    _save_log(
        doc_id,
        self.request.id,
        DocumentTaskStageEnum.VECTORIZE.value,
        DocumentTaskEventTypeEnum.START.value,
        DocumentLogLevelEnum.INFO.value,
        DocumentOperatorTypeEnum.SYSTEM.value,
        "system",
        "开始执行向量化。",
        None,
    )

    chunk_dicts = chunk_result.get("chunks", [])

    try:
        chunks = [Chunk(**c) for c in chunk_dicts]

        if not chunks:
            raise ValueError(f"文档切块列表为空，无法执行向量化: doc_id={doc_id}")

        # 获取 tenant_id 和 document_name
        tenant_id = "default"
        document_name = ""

        async def _get_doc_meta():
            from sqlalchemy import select

            from app.db.models.document import Document

            async with _get_mysql_session() as db:
                doc = (
                    await db.execute(select(Document).where(Document.doc_id == doc_id))
                ).scalar_one_or_none()
                if doc:
                    return (
                        getattr(doc, "tenant_id", "default") or "default",
                        getattr(doc, "document_name", "") or "",
                        getattr(doc, "knowledge_scope_code", "") or "",
                        getattr(doc, "business_category", "") or "",
                        getattr(doc, "document_tags", "") or "",
                        doc.id,
                    )
            return "default", "", "", "", "", None

        tenant_id, document_name, scope_code, business_category, document_tags, doc_internal_id = (
            run_async(_get_doc_meta())
        )
        for chunk in chunks:
            chunk.tenant_id = tenant_id  # type: ignore[attr-defined]
            chunk.scope_code = scope_code  # type: ignore[attr-defined]
            chunk.business_category = business_category  # type: ignore[attr-defined]
            chunk.document_tags = document_tags  # type: ignore[attr-defined]
            if not getattr(chunk, "document_id", None) and doc_internal_id:
                chunk.document_id = doc_internal_id

        async def _do_vectorize():
            vectorizer = VectorizerService()
            vec_count = await vectorizer.vectorize(
                chunks,
                task_id=self.request.id,
                document_name=document_name,
                scope_code=scope_code,
                business_category=business_category,
                document_tags=document_tags,
            )
            await _save_mysql_document_chunks_async(doc_id, chunks, self.request.id)
            return vec_count

        count = run_async(_do_vectorize())
        _save_log(
            doc_id,
            self.request.id,
            DocumentTaskStageEnum.VECTORIZE.value,
            DocumentTaskEventTypeEnum.COMPLETE.value,
            DocumentLogLevelEnum.INFO.value,
            DocumentOperatorTypeEnum.SYSTEM.value,
            "system",
            "向量化完成。",
            {"chunk_count": count},
        )
        _update_task_status(self.request.id, DocumentTaskStatusEnum.SUCCESS.value)
        _update_pipeline_stage(doc_id, DocumentPipelineStageEnum.VECTORIZED.value)
        return {"doc_id": doc_id, "chunks": chunk_dicts, "vectorized_count": count}
    except Exception as e:
        _task_failed(self, doc_id, DocumentTaskStageEnum.VECTORIZE.value, "向量化失败。", e)
        return {"doc_id": doc_id, "chunks": chunk_dicts, "vectorized_count": 0}
