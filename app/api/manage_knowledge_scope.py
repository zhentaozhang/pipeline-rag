"""管理 API — /manage/knowledge/scope/* + /manage/knowledge/topic/*"""

import structlog
from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import get_current_user
from app.api.schemas.manage_schema import (
    KnowledgeScopeSaveRequest,
    KnowledgeScopeVO,
    KnowledgeTopicSaveRequest,
    KnowledgeTopicVO,
    TopicDocumentSaveRequest,
    TopicDocumentVO,
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
    "/knowledge/scope/list",
    summary="知识域列表",
    description="获取所有知识域（Knowledge Scope）列表，包含编码、名称、描述、别名、示例等。",
)
async def list_scopes_post(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """POST /manage/knowledge/scope/list — 知识域列表"""
    from app.manage.service.scope_service import list_scopes

    scopes = await list_scopes(db)

    data_list = [
        KnowledgeScopeVO(
            scope_code=s.scope_code,
            scope_name=s.scope_name,
            description=s.description,
            parent_scope_code=s.parent_scope_code,
            sort_order=s.sort_order,
            aliases=s.aliases,
            examples=s.examples,
        ).model_dump(by_alias=True)
        for s in scopes
    ]
    return ApiResponse.ok(data=data_list)


@router.post(
    "/knowledge/scope/save",
    summary="保存知识域",
    description="创建或更新知识域（Knowledge Scope），包含编码、名称、描述、父域、别名、示例等。",
)
async def save_knowledge_scope(
    req: "KnowledgeScopeSaveRequest",
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """POST /manage/knowledge/scope/save"""
    from app.manage.service.scope_service import save_scope

    await save_scope(
        db,
        req.scope_code,
        req.scope_name,
        description=req.description,
        parent_scope_code=req.parent_scope_code or "",
        aliases=req.aliases or "",
        examples=req.examples or "",
        sort_order=int(req.sort_order) if req.sort_order else 0,
    )
    return ApiResponse.ok(data={"scopeCode": req.scope_code})


@router.post(
    "/knowledge/scope/delete",
    summary="删除知识域",
    description="删除指定的知识域。如果知识域不存在则返回错误。",
)
async def delete_knowledge_scope(
    scope_code: str = Body(..., alias="scopeCode", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """POST /manage/knowledge/scope/delete"""
    from app.manage.service.scope_service import delete_scope

    success = await delete_scope(db, scope_code)
    if not success:
        return ApiResponse.fail("Scope not found")

    return ApiResponse.ok()


@router.post(
    "/knowledge/topic/save",
    summary="保存知识主题",
    description="在指定知识域下创建或更新知识主题（Topic），包含编码、名称、描述、别名、回答形态、执行偏好等。",
)
async def save_knowledge_topic(
    req: "KnowledgeTopicSaveRequest",
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    from app.manage.service.scope_service import save_topic

    success = await save_topic(
        db,
        req.scope_code,
        req.topic_code,
        req.topic_name,
        description=req.description or "",
        aliases=req.aliases or "",
        examples=req.examples or "",
        answer_shape=req.answer_shape or "",
        execution_preference=req.execution_preference or "",
        sort_order=int(req.sort_order) if req.sort_order else 0,
    )
    if not success:
        return ApiResponse.fail("Scope not found")

    return ApiResponse.ok(data={"topicCode": req.topic_code})


@router.post(
    "/knowledge/topic/delete",
    summary="删除知识主题",
    description="删除指定的知识主题。如果主题不存在则返回错误。",
)
async def delete_knowledge_topic(
    topic_code: str = Body(..., alias="topicCode", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    from app.manage.service.scope_service import delete_topic

    success = await delete_topic(db, topic_code)
    if not success:
        return ApiResponse.fail("Topic not found")
    return ApiResponse.ok()


@router.post(
    "/knowledge/scope/topic/bind",
    summary="主题绑定到知识域",
    description="将已有知识主题绑定到指定知识域下。",
)
async def bind_topic_to_scope(
    scope_code: str = Body(...),
    topic_code: str = Body(...),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """POST /manage/knowledge/scope/topic/bind — 将已有主题绑定到知识域"""
    from app.manage.service.scope_service import bind_topic_to_scope

    success = await bind_topic_to_scope(db, scope_code, topic_code)
    if not success:
        return ApiResponse.fail("Scope or Topic not found")
    return ApiResponse.ok()


@router.post(
    "/knowledge/topic/list",
    summary="知识主题列表",
    description="获取指定知识域下的所有知识主题列表，包含编码、名称、描述、别名、回答形态、执行偏好等。",
)
async def list_knowledge_topics(
    scope_code: str = Body(None, alias="scopeCode", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    from app.manage.service.scope_service import list_topics

    topics = await list_topics(db, scope_code or "")
    if topics is None:
        return ApiResponse.fail("Scope not found")

    return ApiResponse.ok(
        data=[
            KnowledgeTopicVO(
                topic_code=t.topic_code,
                topic_name=t.topic_name,
                scope_code=t.scope_code,
                description=t.description,
                aliases=t.aliases,
                examples=t.examples,
                answer_shape=t.answer_shape,
                execution_preference=t.execution_preference,
                sort_order=t.sort_order,
            ).model_dump(by_alias=True)
            for t in topics
        ]
    )


@router.post(
    "/knowledge/topic/document/list",
    summary="主题关联文档列表",
    description="获取指定知识主题下关联的文档列表，包含关联分数、来源、理由及各文档的元数据。",
)
async def list_topic_documents(
    topic_code: str = Body(None, alias="topicCode", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    from app.manage.service.document_service import get_documents_by_doc_ids
    from app.manage.service.scope_service import list_topic_documents

    if not topic_code:
        return ApiResponse.ok(data=[])
    data = await list_topic_documents(db, topic_code)

    doc_ids = [d.get("doc_id", "") for d in data if d.get("doc_id")]
    doc_map = await get_documents_by_doc_ids(db, doc_ids)

    vo_list = [
        TopicDocumentVO(
            topic_code=topic_code,
            document_id=d["doc_id"],
            doc_id=d["doc_id"],
            title=d.get("title", ""),
            document_name=doc_map[d["doc_id"]].document_name if d["doc_id"] in doc_map else None,
            relation_score=d.get("relation_score"),
            relation_source=d.get("relation_source"),
            reason=d.get("reason"),
            knowledge_scope_code=doc_map[d["doc_id"]].knowledge_scope_code
            if d["doc_id"] in doc_map
            else None,
            knowledge_scope_name=doc_map[d["doc_id"]].knowledge_scope_name
            if d["doc_id"] in doc_map
            else None,
            business_category=doc_map[d["doc_id"]].business_category
            if d["doc_id"] in doc_map
            else None,
            document_tags=doc_map[d["doc_id"]].document_tags if d["doc_id"] in doc_map else None,
        ).model_dump(by_alias=True)
        for d in data
    ]
    return ApiResponse.ok(data=vo_list)


@router.post(
    "/knowledge/topic/document/save",
    summary="关联文档到主题",
    description="将指定文档关联到知识主题，可设置关联分数。",
)
async def save_topic_document(
    req: "TopicDocumentSaveRequest",
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    from app.manage.service.scope_service import save_topic_document

    await save_topic_document(db, req.topic_code, req.document_id, req.relation_score)
    return ApiResponse.ok()


@router.post(
    "/knowledge/topic/document/remove",
    summary="移除主题关联文档",
    description="移除指定文档与知识主题的关联关系。",
)
async def remove_topic_document(
    topic_code: str = Body(..., alias="topicCode", embed=True),
    document_id: str = Body(..., alias="documentId", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """主题-文档关系移除"""
    from app.manage.service.scope_service import remove_topic_document

    await remove_topic_document(db, topic_code, document_id)
    return ApiResponse.ok()
