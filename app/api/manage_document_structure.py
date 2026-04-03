"""管理 API — /manage/document/structure/* (文档结构节点)"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import get_current_user
from app.api.schemas.response import ApiResponse
from app.db.session import get_db

logger = structlog.get_logger(__name__)

router: APIRouter = APIRouter()


@router.get(
    "/document/structure/node/list",
    summary="文档结构节点列表",
)
async def list_structure_nodes(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    from app.manage.service.document_structure_node_service import list_structure_nodes

    data = await list_structure_nodes(db, doc_id)
    return ApiResponse.ok(data=data)


@router.get(
    "/document/structure/node/graph",
    summary="文档结构图谱",
)
async def get_structure_graph(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    from app.manage.service.document_structure_node_service import get_structure_graph

    node_list, edge_list = await get_structure_graph(db, doc_id)
    return ApiResponse.ok(data={"nodes": node_list, "edges": edge_list})


@router.get(
    "/document/structure/strategy/pipeline",
    summary="策略流水线配置",
)
async def get_strategy_pipeline(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    from app.manage.service.document_service import get_strategy_plan_by_doc_id

    plan = await get_strategy_plan_by_doc_id(db, doc_id)
    if not plan:
        return ApiResponse.fail("Strategy plan not found")

    return ApiResponse.ok(data=plan)
