"""管理 API — /manage/document/* (文档 CRUD)"""

import contextlib
import json
from typing import Any

import structlog
from fastapi import APIRouter, Body, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import get_current_user
from app.api.schemas.manage_schema import (
    DocumentPageRequest,
    DocumentPageResponse,
    DocumentVO,
    TaskLogVO,
)
from app.api.schemas.response import ApiResponse
from app.common.enums import (
    DocumentFileTypeEnum,
    DocumentIndexStatusEnum,
    DocumentParseStatusEnum,
    DocumentStrategyStatusEnum,
    DocumentTaskStatusEnum,
    DocumentTaskTypeEnum,
)
from app.db.session import get_db

logger = structlog.get_logger(__name__)

router: APIRouter = APIRouter()

_FILE_TYPE_NAMES = {
    DocumentFileTypeEnum.PDF: "PDF",
    DocumentFileTypeEnum.DOC: "DOC",
    DocumentFileTypeEnum.DOCX: "DOCX",
    DocumentFileTypeEnum.TXT: "TXT",
    DocumentFileTypeEnum.MD: "MD",
    DocumentFileTypeEnum.HTML: "HTML",
}
_PARSE_STATUS_NAMES = {
    DocumentParseStatusEnum.WAIT_PARSE: "等待解析",
    DocumentParseStatusEnum.PARSING: "解析中",
    DocumentParseStatusEnum.PARSE_SUCCESS: "解析成功",
    DocumentParseStatusEnum.PARSE_FAILED: "解析失败",
}
_STRATEGY_STATUS_NAMES = {
    DocumentStrategyStatusEnum.WAIT_RECOMMEND: "等待推荐",
    DocumentStrategyStatusEnum.RECOMMENDED: "已推荐",
    DocumentStrategyStatusEnum.CONFIRMED: "已确认",
    DocumentStrategyStatusEnum.EXPIRED: "已过期",
}
_INDEX_STATUS_NAMES = {
    DocumentIndexStatusEnum.WAIT_BUILD: "等待构建",
    DocumentIndexStatusEnum.BUILDING: "构建中",
    DocumentIndexStatusEnum.BUILD_SUCCESS: "构建成功",
    DocumentIndexStatusEnum.BUILD_FAILED: "构建失败",
}
_TASK_TYPE_NAMES = {
    DocumentTaskTypeEnum.PARSE_ROUTE: "文档解析",
    DocumentTaskTypeEnum.BUILD_INDEX: "索引构建",
    3: "画像生成",
}
_TASK_STATUS_NAMES = {
    DocumentTaskStatusEnum.NEW: "等待中",
    DocumentTaskStatusEnum.RUNNING: "执行中",
    DocumentTaskStatusEnum.SUCCESS: "执行成功",
    DocumentTaskStatusEnum.FAILED: "执行失败",
}
_TASK_STAGE_NAMES = {
    "parse": "文档解析",
    "chunk": "文档切块",
    "vectorize": "向量化",
    "index": "索引构建",
}
_TASK_STAGE_CODE_NAMES = {1: "文档解析", 2: "文档切块", 3: "向量化", 4: "索引构建"}
_TASK_EVENT_NAMES = {
    "pending": "等待执行",
    "running": "执行中",
    "success": "执行成功",
    "failed": "执行失败",
}


@router.post(
    "/document/upload",
    summary="上传文档",
    description="上传文档文件到 MinIO 存储，并创建文档记录。支持传递 JSON meta 信息（知识域编码、文档名、标签）。触发异步文档处理流水线。",
)
async def upload_document(
    file: UploadFile = File(...),
    meta: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    """POST /manage/document/upload — 上传文档"""
    from app.manage.service.document_service import upload_document

    meta_dict = {}
    if meta:
        meta_bytes = await meta.read()
        with contextlib.suppress(json.JSONDecodeError, UnicodeDecodeError):
            meta_dict = json.loads(meta_bytes.decode("utf-8"))
    scope_code = meta_dict.get("knowledgeScopeCode", "")
    title = meta_dict.get("documentName", "")
    tags = meta_dict.get("documentTags", "")
    try:
        data = await upload_document(db, file, scope_code, title, tags)
        return ApiResponse.ok(data=data)
    except ValueError as e:
        return ApiResponse.fail(str(e))


@router.post(
    "/document/page/query",
    summary="文档列表",
    description="分页查询文档列表，支持 keyword 关键词过滤、知识域 scope_code 筛选。返回文档状态、最近任务信息等。",
)
async def list_documents(
    req: "DocumentPageRequest",
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    """POST /manage/document/page/query — 文档列表（分页 + keyword 过滤）"""
    from app.manage.service.document_service import (
        get_latest_task_by_doc_ids,
        list_documents,
    )

    docs, total = await list_documents(
        db, req.page_no, req.page_size, req.scope_code, keyword=req.keyword
    )

    doc_ids = [d.id for d in docs if d.id]
    latest_tasks = await get_latest_task_by_doc_ids(db, doc_ids)

    data_list = []
    for d in docs:
        t = latest_tasks.get(d.id) if d.id else None
        data_list.append(
            DocumentVO(
                documentId=str(d.doc_id),
                document_name=d.document_name,
                original_file_name=d.original_file_name,
                file_type=d.file_type,
                file_type_name=_FILE_TYPE_NAMES.get(DocumentFileTypeEnum(d.file_type), "")
                if d.file_type
                else "",
                file_size=d.file_size,
                char_count=d.char_count,
                token_count=d.token_count,
                parse_status=d.parse_status,
                parse_status_name=_PARSE_STATUS_NAMES.get(
                    DocumentParseStatusEnum(d.parse_status), ""
                )
                if d.parse_status
                else "",
                strategy_status=d.strategy_status,
                strategy_status_name=_STRATEGY_STATUS_NAMES.get(
                    DocumentStrategyStatusEnum(d.strategy_status), ""
                )
                if d.strategy_status
                else "",
                index_status=d.index_status,
                index_status_name=_INDEX_STATUS_NAMES.get(
                    DocumentIndexStatusEnum(d.index_status), ""
                )
                if d.index_status
                else "",
                parse_error_msg=d.parse_error_msg,
                knowledge_scope_code=d.knowledge_scope_code,
                knowledge_scope_name=d.knowledge_scope_name,
                business_category=d.business_category,
                document_tags=d.document_tags,
                current_plan_id=d.current_plan_id,
                last_index_task_id=d.last_index_task_id,
                edit_time=d.updated_at.isoformat() if d.updated_at else None,
                status=d.status,
                latest_task_id=str(t.id) if t else None,
                latest_task_type=t.task_type if t else None,
                latest_task_type_name=_TASK_TYPE_NAMES.get(DocumentTaskTypeEnum(t.task_type))
                if t and t.task_type
                else None,
                latest_task_status=t.task_status if t else None,
                latest_task_status_name=_TASK_STATUS_NAMES.get(
                    DocumentTaskStatusEnum(t.task_status)
                )
                if t and t.task_status
                else None,
            )
        )
    resp = DocumentPageResponse(
        records=data_list, total=total, page_no=req.page_no, page_size=req.page_size
    )
    return ApiResponse.ok(data=resp.model_dump(by_alias=True))


@router.post(
    "/document/detail/query",
    summary="文档详情",
    description="获取单篇文档的详细信息，包括基本信息、解析/策略/索引状态、及最新的处理任务状态。",
)
async def get_document(
    document_id: str = Body(..., alias="documentId", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    """POST /manage/document/detail/query — 文档详情"""
    from app.manage.service.document_service import get_document, get_latest_task_by_doc_id

    doc = await get_document(db, document_id)
    if not doc:
        return ApiResponse.fail("文档不存在")

    latest_task = await get_latest_task_by_doc_id(db, doc.id) if doc.id else None

    vo = DocumentVO(
        documentId=str(doc.doc_id),
        document_name=doc.document_name,
        original_file_name=doc.original_file_name,
        file_type=doc.file_type,
        file_type_name=_FILE_TYPE_NAMES.get(DocumentFileTypeEnum(doc.file_type), "")
        if doc.file_type
        else "",
        file_size=doc.file_size,
        char_count=doc.char_count,
        token_count=doc.token_count,
        parse_status=doc.parse_status,
        parse_status_name=_PARSE_STATUS_NAMES.get(DocumentParseStatusEnum(doc.parse_status), "")
        if doc.parse_status
        else "",
        strategy_status=doc.strategy_status,
        strategy_status_name=_STRATEGY_STATUS_NAMES.get(
            DocumentStrategyStatusEnum(doc.strategy_status), ""
        )
        if doc.strategy_status
        else "",
        index_status=doc.index_status,
        index_status_name=_INDEX_STATUS_NAMES.get(DocumentIndexStatusEnum(doc.index_status), "")
        if doc.index_status
        else "",
        parse_error_msg=doc.parse_error_msg,
        knowledge_scope_code=doc.knowledge_scope_code,
        knowledge_scope_name=doc.knowledge_scope_name,
        business_category=doc.business_category,
        document_tags=doc.document_tags,
        current_plan_id=doc.current_plan_id,
        last_index_task_id=doc.last_index_task_id,
        edit_time=doc.updated_at.isoformat() if doc.updated_at else None,
        status=doc.status,
        latest_task_id=str(latest_task.id) if latest_task else None,
        latest_task_type=latest_task.task_type if latest_task else None,
        latest_task_type_name=_TASK_TYPE_NAMES.get(DocumentTaskTypeEnum(latest_task.task_type))
        if latest_task and latest_task.task_type
        else None,
        latest_task_status=latest_task.task_status if latest_task else None,
        latest_task_status_name=_TASK_STATUS_NAMES.get(
            DocumentTaskStatusEnum(latest_task.task_status)
        )
        if latest_task and latest_task.task_status
        else None,
    )
    return ApiResponse.ok(data=vo.model_dump(by_alias=True))


@router.post(
    "/document/delete",
    summary="删除文档",
    description="删除文档及所有关联数据（Chunk、向量、索引、任务记录等）。不可恢复。",
)
async def delete_document(
    document_id: str = Body(..., alias="documentId", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    """POST /manage/document/delete"""
    from app.manage.service.document_service import delete_document

    await delete_document(db, document_id)
    return ApiResponse.ok(message="文档及所有关联数据已完全删除")


@router.post(
    "/document/retry",
    summary="重试文档处理",
    description="重试失败的文档，重新从失败阶段开始处理流水线。",
)
async def retry_document(
    doc_id: str = Body(..., alias="docId", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    """POST /manage/document/retry — 重试失败文档的处理流水线"""
    from app.manage.service.document_service import retry_document

    try:
        data = await retry_document(db, doc_id)
        return ApiResponse.ok(data=data)
    except ValueError as e:
        return ApiResponse.fail(str(e))


@router.post(
    "/document/task/log/query",
    summary="文档任务日志",
    description="获取文档处理流水线的任务日志列表，包含每个阶段的执行状态、错误信息、时间戳。",
)
async def get_document_tasks(
    doc_id: str = Body(..., alias="documentId", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    """POST /manage/document/task/log/query — 文档处理任务日志"""
    from app.manage.service.document_async_service import list_by_doc
    from app.manage.service.document_service import (
        get_document_by_doc_id,
        get_latest_task_by_doc_id,
    )

    tasks = await list_by_doc(db, doc_id)

    _STAGE_CODES = {"parse": 1, "chunk": 2, "vectorize": 3, "index": 4}
    _STATUS_TO_EVENT = {1: 1, 2: 2, 3: 3, 4: 4}

    logs = [
        TaskLogVO(
            id=str(t.id),
            task_id=t.task_id,
            stage_type=_STAGE_CODES.get(t.stage or ""),
            stage_type_name=_TASK_STAGE_NAMES.get(t.stage or "", t.stage or ""),
            event_type=_STATUS_TO_EVENT.get(t.status, 1),
            event_type_name=_TASK_EVENT_NAMES.get(
                {1: "pending", 2: "running", 3: "success", 4: "failed"}.get(t.status, "pending"), ""
            ),
            content=t.error_msg or f"任务 {t.stage or ''} 阶段完成",
            detail_json=t.error_msg if t.error_msg else None,
            create_time=t.start_time.isoformat() if t.start_time else None,
        ).model_dump(by_alias=True)
        for t in tasks
    ]

    doc = await get_document_by_doc_id(db, doc_id)
    task_meta = await get_latest_task_by_doc_id(db, doc.id) if doc and doc.id else None

    result: dict[str, Any] = {"logs": logs}
    if task_meta:
        result["taskId"] = str(task_meta.id)
        result["taskStatus"] = str(task_meta.task_status) if task_meta.task_status else None
        result["taskType"] = task_meta.task_type
        result["currentStage"] = str(task_meta.current_stage) if task_meta.current_stage else None
        result["currentStageName"] = _TASK_STAGE_CODE_NAMES.get(task_meta.current_stage or 0, "")
        result["errorMsg"] = task_meta.error_msg
        result["costMillis"] = task_meta.cost_millis
    return ApiResponse.ok(data=result)
