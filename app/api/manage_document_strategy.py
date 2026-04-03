"""管理 API — /manage/document/strategy/* (切块策略 + 索引构建)"""

from typing import Any

import structlog
from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import get_current_user
from app.api.schemas.manage_schema import (
    StrategyConfirmRequest,
    StrategyPipelineVO,
    StrategyPlanResponse,
    StrategyPlanStepVO,
    StrategyPlanVO,
)
from app.api.schemas.response import ApiResponse
from app.common.enums import (
    DocumentChunkSourceTypeEnum,
    DocumentStrategyRoleEnum,
)
from app.common.utils import safe_int
from app.db.session import get_db

logger = structlog.get_logger(__name__)

router: APIRouter = APIRouter()

_SOURCE_TYPE_NAMES = {
    DocumentChunkSourceTypeEnum.ORIGINAL: "结构切分",
    DocumentChunkSourceTypeEnum.ENRICHED: "语义切分",
    3: "递归切分",
    4: "LLM 切分",
}
_STRATEGY_ROLE_NAMES = {
    DocumentStrategyRoleEnum.PRIMARY: "主要策略",
    DocumentStrategyRoleEnum.FALLBACK: "兜底策略",
    DocumentStrategyRoleEnum.OPTIMIZE: "优化策略",
    DocumentStrategyRoleEnum.ENHANCE: "增强策略",
}


@router.post(
    "/document/strategy/recommend",
    summary="推荐切块策略",
)
async def recommend_strategy(
    doc_id: str = Body(..., alias="documentId", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    from app.manage.service.document_strategy_service import recommend_strategy

    await recommend_strategy(db, doc_id)
    return ApiResponse.ok(message="strategy recommended")


@router.post(
    "/document/strategy/plan/query",
    summary="查询策略计划",
)
async def query_strategy_plan(
    document_id: str = Body(..., alias="documentId", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    from app.manage.service.document_service import get_document_by_doc_id
    from app.manage.service.document_strategy_service import query_strategy_plan

    plan = await query_strategy_plan(db, document_id)
    if not plan:
        doc = await get_document_by_doc_id(db, document_id)
        return ApiResponse.ok(
            data=StrategyPlanResponse(
                plan_ready=False,
                document_id=document_id,
                parse_status=str(doc.parse_status) if doc else None,
            ).model_dump(by_alias=True)
        )

    def _to_step_vo(s: dict[str, Any]) -> StrategyPlanStepVO:
        st = s.get("strategy_type", 0)
        sr = s.get("strategy_role", 0)
        return StrategyPlanStepVO(
            plan_step_id=str(s.get("id", "")),
            step_no=s.get("step_no", 0),
            strategy_type=st,
            strategy_role=sr,
            strategy_name=_SOURCE_TYPE_NAMES.get(st, ""),
            strategy_role_name=_STRATEGY_ROLE_NAMES.get(sr, ""),
            recommend_reason=s.get("recommend_reason"),
        )

    plan_vo = StrategyPlanVO(
        plan_id=str(plan["plan"].get("id", "")),
        plan_status=plan["plan"].get("plan_status", 0),
        recommend_reason=plan["plan"].get("recommend_reason"),
        parent_pipeline=StrategyPipelineVO(
            steps=[_to_step_vo(s) for s in plan.get("parent_steps", [])],
        ),
        child_pipeline=StrategyPipelineVO(
            steps=[_to_step_vo(s) for s in plan.get("child_steps", [])],
        ),
    )
    resp = StrategyPlanResponse(plan_ready=True, document_id=document_id, plan=plan_vo)
    return ApiResponse.ok(data=resp.model_dump(by_alias=True))


@router.post(
    "/document/strategy/confirm",
    summary="确认切块策略",
)
async def confirm_strategy(
    req: "StrategyConfirmRequest",
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    from app.manage.service.document_strategy_service import confirm_strategy, normalize_steps

    user_id = safe_int(req.operator_id, default=1)

    parent_types = [int(s.get("strategyType", 0)) for s in req.parent_steps]
    child_types = [int(s.get("strategyType", 0)) for s in req.child_steps]
    if parent_types or child_types:
        await normalize_steps(db, req.document_id, int(req.base_plan_id), parent_types, child_types)

    await confirm_strategy(db, req.document_id, int(req.base_plan_id), user_id or 1)
    return ApiResponse.ok(message="strategy confirmed")


@router.post(
    "/document/index/build",
    summary="构建文档索引",
    description="提交文档索引构建任务，触发 Celery 异步流水线重新执行 Chunking → Vectorize → Index 全流程。",
)
async def reindex_document(
    document_id: str = Body(..., alias="documentId", embed=True),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    """POST /manage/document/index/build"""

    from app.manage.service.document_service import create_index_task, get_document_by_doc_id

    doc = await get_document_by_doc_id(db, document_id)
    if not doc:
        return ApiResponse.fail("Document not found")

    from app.common.enums import DocumentIndexStatusEnum

    doc.index_status = DocumentIndexStatusEnum.BUILDING.value

    task_id = await create_index_task(db, doc)
    logger.info("build index submitted", doc_id=document_id, task_id=task_id)

    return ApiResponse.ok(message="重新索引任务已提交", data={"taskId": str(task_id)})
