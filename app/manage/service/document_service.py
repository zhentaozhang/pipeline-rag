from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

import structlog
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import (
    BusinessStatus,
    DocumentFileTypeEnum,
    DocumentIndexStatusEnum,
    DocumentLogLevelEnum,
    DocumentOperatorTypeEnum,
    DocumentParseStatusEnum,
    DocumentStorageTypeEnum,
    DocumentStrategyStatusEnum,
    DocumentTaskEventTypeEnum,
    DocumentTaskStageEnum,
    DocumentTaskStatusEnum,
    DocumentTaskTypeEnum,
)
from app.common.exceptions import ArgumentException
from app.common.utils import safe_int
from app.db.repositories.document_repository import DocumentRepository
from app.db.repositories.knowledge_repository import KnowledgeRepository
from app.db.repositories.observability_repository import ObservabilityRepository
from app.db.repositories.routing_repository import RoutingRepository
from app.document.tasks import trigger_document_pipeline
from app.infra.id_generator import next_id, next_id_int, next_id_str
from app.manage.service.storage_service import delete_objects, upload_original_file

if TYPE_CHECKING:
    from app.db.models.document import (
        Document,
        DocumentChunk,
        DocumentParentBlock,
        PipelineRAGDocumentTask,
    )

logger = structlog.get_logger(__name__)


async def upload_document(
    db: AsyncSession,
    file: UploadFile,
    scope_code: str,
    title: str | None,
    tags: str | None,
    operator_id: str | None = None,
) -> dict:
    if not file or not file.filename:
        raise ValueError("Empty file content")

    original_file_name = re.sub(r"[^\w\-.]", "_", file.filename)

    file_ext = original_file_name.split(".")[-1].lower() if "." in original_file_name else ""
    supported_extensions = {"pdf", "doc", "docx", "txt", "md", "html"}
    if file_ext not in supported_extensions:
        raise ValueError(f"Unsupported file type: .{file_ext}")

    file_type = DocumentFileTypeEnum.__members__.get(file_ext.upper())
    file_type_code = file_type.value if file_type else 0

    file_bytes = await file.read()
    if not file_bytes:
        raise ValueError("Empty file content")

    doc_id = next_id_str()
    doc_internal_id = next_id_int()

    stored_info = await upload_original_file(
        doc_id, original_file_name, file_bytes, file.content_type or "application/octet-stream"
    )

    scope = await KnowledgeRepository.get_scope_by_code(db, scope_code)

    from app.db.models.document import Document as DocModel
    from app.db.models.document import DocumentTask

    task_id_val = next_id_str()
    doc = DocModel(
        id=doc_internal_id,
        doc_id=doc_id,
        document_name=title or original_file_name,
        original_file_name=original_file_name,
        file_type=file_type_code,
        mime_type=file.content_type or "application/octet-stream",
        file_size=len(file_bytes),
        storage_type=DocumentStorageTypeEnum.MINIO.value,
        bucket_name=stored_info.bucket_name,
        object_name=stored_info.object_name,
        object_url=stored_info.object_url,
        parse_status=DocumentParseStatusEnum.PARSING.value,
        strategy_status=DocumentStrategyStatusEnum.WAIT_RECOMMEND.value,
        index_status=DocumentIndexStatusEnum.WAIT_BUILD.value,
        char_count=0,
        token_count=0,
        knowledge_scope_code=scope_code,
        knowledge_scope_name=scope.scope_name if scope else "",
        business_category=None,
        document_tags=tags,
        status=BusinessStatus.YES.value,
    )
    op_id = safe_int(operator_id, default=None)
    task = DocumentTask(
        id=next_id(),
        task_id=task_id_val,
        doc_id=doc_id,
        task_type=str(DocumentTaskTypeEnum.PARSE_ROUTE.value),
        stage=str(DocumentTaskStageEnum.FILE_UPLOAD.value),
        status=DocumentTaskStatusEnum.NEW.value,
    )
    db.add(doc)
    db.add(task)
    await db.flush()

    from app.manage.service.document_async_service import save_log

    await save_log(
        db,
        task.id,
        doc_internal_id,
        stage_type=DocumentTaskStageEnum.FILE_UPLOAD.value,
        event_type=DocumentTaskEventTypeEnum.COMPLETE.value,
        log_level=DocumentLogLevelEnum.INFO.value,
        operator_type=DocumentOperatorTypeEnum.USER.value
        if op_id
        else DocumentOperatorTypeEnum.SYSTEM.value,
        operator_id=operator_id or "system",
        content="文件上传完成，已进入解析与策略推荐队列。",
        detail={"originalFileName": original_file_name, "fileSize": len(file_bytes)},
    )
    task.status = DocumentTaskStatusEnum.SUCCESS.value
    await db.commit()

    trigger_document_pipeline(doc_id, stored_info.object_name)

    return {
        "docId": doc_id,
        "taskId": task_id_val,
        "status": "pending",
        "parseStatus": doc.parse_status,
        "strategyStatus": doc.strategy_status,
        "indexStatus": doc.index_status,
    }


async def list_documents(
    db: AsyncSession,
    page: int,
    size: int,
    scope_code: str | None = None,
    keyword: str | None = None,
) -> tuple[list, int]:
    return await DocumentRepository.list_documents(db, page, size, scope_code, keyword)


async def get_document(db: AsyncSession, doc_id: str) -> Document | None:
    return await DocumentRepository.get_by_doc_id(db, doc_id)


async def delete_document(db: AsyncSession, doc_id: str) -> None:
    doc_row = await DocumentRepository.get_by_doc_id(db, doc_id)
    if not doc_row:
        raise ArgumentException("文档不存在")
    doc_internal_id = doc_row.id

    active_count = await DocumentRepository.get_active_task_count(db, doc_id)
    if active_count > 0:
        raise ArgumentException("当前文档存在进行中的任务，请等待任务结束后再删除。")

    # 2. Delete MinIO objects by specific names (objectName + parseTextPath)
    obj_names_to_delete = []
    if doc_row.object_name:
        obj_names_to_delete.append(doc_row.object_name)
    if doc_row.parse_text_path:
        obj_names_to_delete.append(doc_row.parse_text_path)
    if obj_names_to_delete:
        try:
            await delete_objects(obj_names_to_delete)
        except Exception as e:
            logger.warning("failed to delete minio objects", doc_id=doc_id, error=str(e))

    # 3. Delete PGVector
    from app.document.vectorizer import VectorizerService

    try:
        await VectorizerService().delete_doc(db, doc_id)
    except Exception as e:
        logger.warning("failed to delete pgvector", doc_id=doc_id, error=str(e))

    # 4. Delete ES keyword index + Neo4j
    from app.document.indexer import DocumentIndexer

    try:
        await DocumentIndexer().delete_doc(doc_id)
    except Exception as e:
        logger.warning("failed to delete es/neo4j", doc_id=doc_id, error=str(e))

    # 5. Delete ES navigation index
    from app.document.navigation_indexer import NavigationIndexer

    try:
        await NavigationIndexer().delete_doc(doc_id)
    except Exception as e:
        logger.warning("failed to delete navigation index", doc_id=doc_id, error=str(e))

    # 6. Delete ES knowledge route index
    from app.infra.es_services import ElasticsearchKnowledgeRouteIndexService

    try:
        await ElasticsearchKnowledgeRouteIndexService().delete_document_route(doc_id)
    except Exception as e:
        logger.warning("failed to delete route index", doc_id=doc_id, error=str(e))

    # 7. Delete DB records in cascade order
    await DocumentRepository.delete_profile_by_doc_id(db, doc_internal_id)
    await KnowledgeRepository.delete_topic_relations_by_doc_id(db, doc_internal_id)
    await DocumentRepository.delete_parent_blocks_by_doc_id(db, doc_internal_id)
    await DocumentRepository.delete_chunks_by_doc_id(db, doc_internal_id)
    await DocumentRepository.delete_structure_nodes_by_doc_id(db, doc_internal_id)
    await DocumentRepository.delete_task_logs_by_doc_id(db, doc_internal_id)
    await DocumentRepository.delete_strategy_steps_by_doc_id(db, doc_internal_id)
    await DocumentRepository.delete_tasks_by_doc_id(db, doc_id)
    await DocumentRepository.delete_super_tasks_by_doc_id(db, doc_internal_id)
    await DocumentRepository.delete_strategy_plans_by_doc_id(db, doc_internal_id)
    await DocumentRepository.delete_by_doc_id(db, doc_id)
    await db.commit()


async def get_chunks_page(
    db: AsyncSession, doc_internal_id: int, page: int, size: int
) -> tuple[list, int]:
    return await DocumentRepository.get_chunks_page(db, doc_internal_id, page, size)


async def get_parent_blocks_by_ids(
    db: AsyncSession, ids: list[int]
) -> dict[int, DocumentParentBlock]:
    if not ids:
        return {}
    return await DocumentRepository.get_parent_blocks_by_ids(db, ids)


async def get_chunk_by_id(
    db: AsyncSession, chunk_id: int, doc_internal_id: int
) -> DocumentChunk | None:
    return await DocumentRepository.get_chunk_by_id(db, chunk_id, doc_internal_id)


async def get_parent_block_by_id(
    db: AsyncSession, parent_block_id: int
) -> DocumentParentBlock | None:
    return await DocumentRepository.get_parent_block_by_id(db, parent_block_id)


async def get_exchange_channel_executions(
    db: AsyncSession, conversation_id: str, exchange_id: int
) -> list:
    return await ObservabilityRepository.get_channel_executions(db, conversation_id, exchange_id)


async def get_exchange_retrieval_results(
    db: AsyncSession, conversation_id: str, exchange_id: int
) -> list:
    return await ObservabilityRepository.get_retrieval_results(db, conversation_id, exchange_id)


async def query_evaluation_dataset_page(
    db: AsyncSession, page_no: int, page_size: int
) -> tuple[list, int]:
    return await ObservabilityRepository.get_evaluation_page(db, page_no, page_size)


async def run_evaluation_dataset(db: AsyncSession, dataset_ids: list[int] | None = None) -> list:
    return await ObservabilityRepository.run_evaluation(db, dataset_ids)


async def delete_evaluation_record(db: AsyncSession, dataset_id: int) -> None:
    return await ObservabilityRepository.delete_evaluation(db, dataset_id)


async def query_route_traces(
    db: AsyncSession,
    page: int,
    size: int,
    conversation_id: str | None = None,
    mode: str | None = None,
    route_status: str | None = None,
) -> tuple[list, int]:
    return await RoutingRepository.query_traces(db, page, size, conversation_id, mode, route_status)


async def create_index_task(
    db: AsyncSession, doc: Document, task_type: int | None = None, trigger_source: int = 2
) -> int:
    """创建索引构建任务记录，返回 task_id"""
    from app.common.enums import DocumentTaskStatusEnum, DocumentTaskTypeEnum
    from app.db.models.document import PipelineRAGDocumentTask as SuperTask
    from app.manage.service.document_async_service import submit_pipeline

    task_id_val = next_id()
    task_record = SuperTask(
        id=next_id(),
        document_id=doc.id,
        plan_id=doc.current_plan_id,
        task_type=task_type or DocumentTaskTypeEnum.BUILD_INDEX.value,
        task_status=DocumentTaskStatusEnum.NEW.value,
        trigger_source=trigger_source,
        retry_count=0,
        start_time=datetime.now(),
        status=1,
    )
    db.add(task_record)
    await db.flush()
    await db.commit()

    if doc.object_name:
        await submit_pipeline(doc.doc_id, doc.object_name)

    return task_id_val


async def get_strategy_plan_by_doc_id(db: AsyncSession, doc_id: str) -> dict | None:
    plan = await DocumentRepository.get_strategy_plan_by_doc_id(db, doc_id)
    if not plan:
        return None
    pipeline_stages = []
    if plan.strategy_snapshot:
        import json

        try:
            snapshot = json.loads(plan.strategy_snapshot)
            pipeline_stages = snapshot if isinstance(snapshot, list) else []
        except json.JSONDecodeError:
            pipeline_stages = []
    return {
        "pipeline_stages": pipeline_stages,
        "plan_status": plan.plan_status,
        "recommend_reason": plan.recommend_reason,
    }


async def get_sibling_chunks(db: AsyncSession, parent_block_id: int, exclude_chunk_id: str) -> list:
    return await DocumentRepository.get_sibling_chunks(db, parent_block_id, exclude_chunk_id)


async def get_latest_task_by_doc_ids(
    db: AsyncSession, doc_ids: list[int]
) -> dict[int, PipelineRAGDocumentTask]:
    return await DocumentRepository.get_latest_task_by_doc_ids(db, doc_ids)


async def get_latest_task_by_doc_id(
    db: AsyncSession, doc_id: int
) -> PipelineRAGDocumentTask | None:
    return await DocumentRepository.get_latest_task_by_doc_id(db, doc_id)


async def get_documents_by_doc_ids(db: AsyncSession, doc_ids: list[str]) -> dict[str, Document]:
    return await DocumentRepository.get_by_doc_ids(db, doc_ids)


async def get_document_by_doc_id(db: AsyncSession, doc_id: str) -> Document | None:
    return await DocumentRepository.get_by_doc_id(db, doc_id)


async def retry_document(db: AsyncSession, doc_id: str) -> dict:
    doc = await DocumentRepository.get_by_doc_id(db, doc_id)
    if not doc:
        raise ValueError("Document not found")
    if not (
        doc.parse_status == DocumentParseStatusEnum.PARSE_FAILED.value
        or doc.index_status == DocumentIndexStatusEnum.BUILD_FAILED.value
    ):
        raise ValueError("Document is not in a failed state")
    if not doc.object_name:
        raise ValueError("Document source file not found, please re-upload")

    doc.parse_status = DocumentParseStatusEnum.PARSING.value
    doc.index_status = DocumentIndexStatusEnum.WAIT_BUILD.value
    await db.commit()

    trigger_document_pipeline(doc_id, doc.object_name)
    logger.info("document retry triggered", doc_id=doc_id)
    return {"docId": doc_id, "status": "retry_triggered"}
