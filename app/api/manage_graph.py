"""管理 API — /manage/graph/* (图谱关系干预)"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import get_current_user
from app.api.schemas.response import ApiResponse
from app.db.session import get_db

logger = structlog.get_logger(__name__)

router: APIRouter = APIRouter()


class GraphBlacklistRequest(BaseModel):
    """图谱黑名单请求"""

    source_node: str
    target_node: str
    action: str = "block"


# ── 图谱管理 ──────────────────────────────────────────────────────────────────


@router.post(
    "/graph/blacklist",
    summary="更新图谱关系黑名单",
    description="更新文档结构图谱的关系黑名单，可阻断异常关联或强制建立链接。通过 Redis 存储干预策略。",
)
async def update_graph_blacklist(
    request: GraphBlacklistRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    """POST /manage/graph/blacklist — 更新图谱关系黑名单（阻断异常关联）"""
    import redis.asyncio as aioredis

    from app.config import get_settings

    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis.url, decode_responses=True)

    key = f"graph_blacklist:{request.source_node}:{request.target_node}"
    try:
        if request.action == "remove":
            await redis_client.delete(key)
        else:
            await redis_client.set(key, request.action)
    except Exception as e:
        return ApiResponse.fail(f"Redis 操作失败: {str(e)}")
    finally:
        await redis_client.aclose()

    return ApiResponse.ok(message="图谱干预策略已更新")
