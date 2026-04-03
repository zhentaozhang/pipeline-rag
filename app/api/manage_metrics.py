"""
管理 API — /manage/metrics/* (运维看板)

提供运营总览、Token 趋势、各阶段性能基准三个端点。
"""

import structlog
from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import get_current_user
from app.api.schemas.response import ApiResponse
from app.db.session import get_db
from app.manage.service.metrics_service import MetricsService

logger = structlog.get_logger(__name__)

router: APIRouter = APIRouter()


class OverviewRequest(BaseModel):
    pass


class TrendRequest(BaseModel):
    days: int = 14


@router.post(
    "/metrics/overview",
    summary="运营总览",
    description="汇总 Token 用量、成本、活跃会话数、失败率、平均响应时间。",
)
async def metrics_overview(
    _: OverviewRequest = Body(default={}),
    db: AsyncSession = Depends(get_db),
    __: str = Depends(get_current_user),
) -> dict:
    svc = MetricsService(db)
    overview = await svc.get_overview()
    return ApiResponse.ok(data=overview.to_dict())


@router.post(
    "/metrics/usage-trend",
    summary="Token 用量趋势",
    description="最近 N 天每日 Token 消耗和 LLM 调用次数。",
)
async def metrics_usage_trend(
    req: TrendRequest = Body(default={"days": 14}),
    db: AsyncSession = Depends(get_db),
    __: str = Depends(get_current_user),
) -> dict:
    svc = MetricsService(db)
    trend = await svc.get_usage_trend(days=req.days)
    return ApiResponse.ok(data=trend)

