"""管理 API — /manage/document/chunk/* (文档切片管理)"""

from typing import Any

import structlog
from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import get_current_user
from app.api.schemas.manage_schema import (
    DocumentChunkDetailVO,
    DocumentChunkPageResponse,
    DocumentChunkVO,
    ParentBlockVO,
)
from app.api.schemas.response import ApiResponse
from app.common.enums import (
    DocumentChunkSourceTypeEnum,
    DocumentVectorStatusEnum,
)
from app.db.session import get_db

logger = structlog.get_logger(__name__)

router: APIRouter = APIRouter()

_SOURCE_TYPE_NAMES = {
    DocumentChunkSourceTypeEnum.ORIGINAL: "结构切分",
    DocumentChunkSourceTypeEnum.ENRICHED: "语义切分",
    3: "递归切分",
    4: "LLM 切分",
}
_VECTOR_STATUS_NAMES = {
    DocumentVectorStatusEnum.WAIT_VECTOR: "待处理",
    DocumentVectorStatusEnum.VECTORIZING: "处理中",
    DocumentVectorStatusEnum.VECTOR_SUCCESS: "已向量化",
    DocumentVectorStatusEnum.VECTOR_FAILED: "构建失败",
}


@router.post(
    "/document/chunk/query",
    summary="文档切片列表",
    description="分页查询文档的切块列表，包含每个 Chunk 的编号、来源策略、路径、字符数、向量化状态及所属 Parent Block 信息。",
)
async def list_document_chunks(
    doc_id: str = Body(..., alias="documentId", embed=True),
    page: int = Body(1, alias="pageNo"),
    size: int = Body(20, alias="pageSize"),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    """POST /manage/document/chunk/query — 文档切片列表"""
    from app.manage.service.document_service import (
        get_chunks_page,
        get_document_by_doc_id,
        get_parent_blocks_by_ids,
    )

    doc = await get_document_by_doc_id(db, doc_id)
    if not doc:
        return ApiResponse.fail("文档不存在")

    chunks, total = await get_chunks_page(db, doc.id, page, size)

    parent_block_ids = [c.parent_block_id for c in chunks if c.parent_block_id]
    parent_blocks = await get_parent_blocks_by_ids(db, parent_block_ids)

    vo_list = []
    for c in chunks:
        pb_ref = parent_blocks.get(c.parent_block_id) if c.parent_block_id else None
        vo_list.append(
            DocumentChunkVO(
                chunk_id=str(c.id),
                doc_id=str(c.document_id),
                chunk_no=c.chunk_no,
                source_type=c.source_type,
                source_type_name=_SOURCE_TYPE_NAMES.get(c.source_type or 0, ""),
                section_path=c.section_path,
                chunk_text=c.chunk_text[:200] if c.chunk_text else None,
                char_count=c.char_count,
                token_count=c.token_count,
                vector_status=c.vector_status,
                vector_status_name=_VECTOR_STATUS_NAMES.get(
                    DocumentVectorStatusEnum(c.vector_status), ""
                )
                if c.vector_status
                else "",
                parent_block_id=c.parent_block_id,
                parent_block_no=pb_ref.parent_no if pb_ref else None,
                parent_child_count=pb_ref.child_count if pb_ref else None,
                parent_start_chunk_no=pb_ref.start_chunk_no if pb_ref else None,
                parent_end_chunk_no=pb_ref.end_chunk_no if pb_ref else None,
            )
        )
    task_id = next((c.task_id for c in chunks if c.task_id), None)
    resp = DocumentChunkPageResponse(
        records=vo_list, total=total or 0, page_no=page, page_size=size, task_id=task_id
    )
    return ApiResponse.ok(data=resp.model_dump(by_alias=True))


@router.post(
    "/document/chunk/detail/query",
    summary="切片详情与上下文",
    description="获取单个切片的完整文本内容、所属 Parent Block（父级块）的上下文，以及同属一个 Parent Block 的兄弟切片列表。",
)
async def get_document_chunk_detail(
    doc_id: str = Body(..., alias="documentId", embed=True),
    chunk_id: str = Body(..., alias="chunkId", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    """POST /manage/document/chunk/detail/query — 切片详情与上下文"""
    from app.manage.service.document_service import (
        get_chunk_by_id,
        get_document_by_doc_id,
        get_parent_block_by_id,
        get_sibling_chunks,
    )

    doc = await get_document_by_doc_id(db, doc_id)
    if not doc:
        return ApiResponse.fail("文档不存在")

    chunk_id_int = int(chunk_id)
    chunk = await get_chunk_by_id(db, chunk_id_int, doc.id)
    if not chunk:
        return ApiResponse.fail("切片不存在")

    chunk_vo = DocumentChunkVO(
        chunk_id=str(chunk.id),
        doc_id=str(chunk.document_id),
        chunk_no=chunk.chunk_no,
        source_type=chunk.source_type,
        source_type_name=_SOURCE_TYPE_NAMES.get(chunk.source_type or 0, ""),
        section_path=chunk.section_path,
        chunk_text=chunk.chunk_text,
        char_count=chunk.char_count,
        token_count=chunk.token_count,
        vector_status=chunk.vector_status,
        vector_status_name=_VECTOR_STATUS_NAMES.get(
            DocumentVectorStatusEnum(chunk.vector_status), ""
        )
        if chunk.vector_status
        else "",
        parent_block_id=chunk.parent_block_id,
    )

    parent_block = None
    sibling_chunks = []
    if chunk.parent_block_id:
        pb = await get_parent_block_by_id(db, chunk.parent_block_id)
        if pb:
            parent_block = ParentBlockVO(
                parent_block_id=pb.id,
                parent_block_no=pb.parent_no,
                start_chunk_no=pb.start_chunk_no,
                end_chunk_no=pb.end_chunk_no,
                section_path=pb.section_path,
                char_count=pb.char_count,
                token_count=pb.token_count,
                parent_text=pb.parent_text,
                child_count=pb.child_count,
            )
        siblings = await get_sibling_chunks(db, chunk.parent_block_id, chunk_id)
        for sc in siblings:
            sibling_chunks.append(
                DocumentChunkVO(
                    chunk_id=str(sc.id),
                    doc_id=str(sc.document_id),
                    chunk_no=sc.chunk_no,
                    source_type=sc.source_type,
                    source_type_name=_SOURCE_TYPE_NAMES.get(sc.source_type or 0, ""),
                    section_path=sc.section_path,
                    chunk_text=sc.chunk_text[:200] if sc.chunk_text else None,
                    char_count=sc.char_count,
                    token_count=sc.token_count,
                    vector_status=sc.vector_status,
                    vector_status_name=_VECTOR_STATUS_NAMES.get(
                        DocumentVectorStatusEnum(sc.vector_status), ""
                    )
                    if sc.vector_status
                    else "",
                    parent_block_id=sc.parent_block_id,
                )
            )

    vo = DocumentChunkDetailVO(
        chunk=chunk_vo,
        parent_block=parent_block,
        sibling_chunks=sibling_chunks,
    )
    return ApiResponse.ok(data=vo.model_dump(by_alias=True))
