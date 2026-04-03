"""管理 API — /manage/knowledge/document/profile/* + /manage/knowledge/route/trace/*"""

import structlog
from fastapi import APIRouter, BackgroundTasks, Body, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import get_current_user
from app.api.schemas.manage_schema import (
    DocumentProfileVO,
    ProfileBatchRegenerateRequest,
    RouteTraceItemVO,
    RouteTracePageResponse,
)
from app.api.schemas.response import ApiResponse
from app.db.session import get_db

logger = structlog.get_logger(__name__)

router: APIRouter = APIRouter()


class RouteTracePageRequest(BaseModel):
    page_no: str | None = Field(default=None, alias="pageNo")
    page_size: str | None = Field(default=None, alias="pageSize")
    conversation_id: str | None = Field(default=None, alias="conversationId")
    mode: str | None = None
    route_status: str | None = Field(default=None, alias="routeStatus")
    model_config = {"populate_by_name": True}


@router.post(
    "/knowledge/document/profile/detail",
    summary="文档画像详情",
    description="查询文档的 AI 画像详情，包括文档摘要、核心主题、示例问题、文档类型、图图谱支持标记等。",
)
async def query_profile_detail(
    doc_id: str = Body(..., alias="documentId", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """POST /manage/knowledge/document/profile/detail — 查询文档画像详情"""
    from app.manage.service.document_profile_service import get_document_profile

    profile = await get_document_profile(db, doc_id)

    if not profile:
        return ApiResponse.ok(data=None)

    vo = DocumentProfileVO(
        document_summary=profile.document_summary,
        core_topics=profile.core_topics,
        example_questions=profile.example_questions,
        profile_status=profile.profile_status,
        document_type=profile.document_type,
        profile_source=profile.profile_source,
        supports_graph_outline=str(profile.supports_graph_outline or 0),
        supports_item_lookup=str(profile.supports_item_lookup or 0),
        supports_graph_assist=str(profile.supports_graph_assist or 0),
    )
    return ApiResponse.ok(data=vo.model_dump(by_alias=True))


@router.post(
    "/knowledge/document/profile/regenerate",
    summary="重新生成文档画像",
    description="根据已解析的文档文本，重新调用 LLM 生成文档摘要、核心主题和示例问题。",
)
async def regenerate_profile(
    doc_id: str = Body(..., alias="documentId", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """POST /manage/knowledge/document/profile/regenerate — 重新生成文档画像"""
    from app.manage.service.document_profile_service import generate_profile
    from app.manage.service.storage_service import download_object

    try:
        text = await download_object(f"{doc_id}/parsed.txt")
    except Exception as e:
        logger.error("failed to download parsed text from minio", doc_id=doc_id, error=str(e))
        return ApiResponse.fail(f"Failed to fetch parsed document text: {e}")

    if not text:
        return ApiResponse.fail("Document text is empty")

    text_str = text.decode("utf-8") if isinstance(text, bytes) else text
    await generate_profile(db, doc_id, text_str)
    return ApiResponse.ok(message="profile regeneration started")


@router.post(
    "/knowledge/document/profile/batch/regenerate",
    summary="批量重新生成文档画像",
    description="后台批量重新生成文档的 AI 画像（摘要、核心主题、示例问题等），通过 BackgroundTasks 异步执行。",
)
async def batch_regenerate_profile(
    req: "ProfileBatchRegenerateRequest",
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """POST /manage/knowledge/document/profile/batch/regenerate"""
    from app.db.session import _session_factory as async_session_maker
    from app.manage.service.document_profile_service import generate_profile
    from app.manage.service.document_service import get_document_by_doc_id
    from app.manage.service.storage_service import download_object

    async def _regenerate_task(doc_ids: list[str]):
        assert async_session_maker is not None
        async with async_session_maker() as session:
            for doc_id in doc_ids:
                doc = await get_document_by_doc_id(session, doc_id)
                if doc:
                    try:
                        text = await download_object(f"{doc_id}/parsed.txt")
                        if text:
                            text_str = text.decode("utf-8") if isinstance(text, bytes) else text
                            await generate_profile(session, doc_id, text_str)
                    except Exception as e:
                        logger.error("batch profile error", doc_id=doc_id, error=str(e))

    background_tasks.add_task(_regenerate_task, req.document_ids)
    return ApiResponse.ok(message="batch regeneration started in background")


@router.post(
    "/knowledge/route/trace/page/query",
    summary="路由溯源分页查询",
    description="分页查询知识路由溯源记录，可按 conversationId、mode、routeStatus 筛选。用于调试对话的编排决策过程。",
)
async def get_route_trace_page_post(
    req: "RouteTracePageRequest",
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """POST /manage/knowledge/route/trace/page/query"""
    from app.manage.service.document_service import query_route_traces

    page = int(req.page_no) if req.page_no else 1
    size = int(req.page_size) if req.page_size else 20

    traces, total = await query_route_traces(
        db, page, size, req.conversation_id, req.mode, req.route_status
    )

    items = [
        RouteTraceItemVO(
            conversation_id=t.conversation_id,
            exchange_id=t.exchange_id,
            question=t.question,
            rewrite_question=t.rewrite_question,
            mode=t.mode,
            confidence=float(t.confidence) if t.confidence is not None else None,
            route_status=str(t.route_status),
            created_at=t.created_at.isoformat() if t.created_at else None,
        )
        for t in traces
    ]
    total_pages = 0 if not total else (total + size - 1) // size
    resp = RouteTracePageResponse(
        records=items, total=total or 0, page_no=page, page_size=size, total_pages=total_pages
    )
    return ApiResponse.ok(data=resp.model_dump(by_alias=True))
