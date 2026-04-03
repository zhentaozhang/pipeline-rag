"""对话 API — /api/chat/* (会话管理、会话列表)"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.chat_session import (
    PinRequest,
    RenameRequest,
    SessionIdRequest,
    SessionListRequest,
    StopRequest,
)
from app.api.schemas.response import ApiResponse
from app.chat import session_service as svc
from app.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/session/stop", summary="停止会话生成")
async def chat_stop(
    request: StopRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await svc.stop_session(request.conversation_id)
    return ApiResponse.ok(data=data)


@router.post("/session/detail", summary="获取会话详情")
async def get_session_detail(
    request: SessionIdRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await svc.get_session_detail(db, request.conversation_id)
    if data is None:
        return ApiResponse.fail("会话不存在: " + request.conversation_id)
    return ApiResponse.ok(data=data)


@router.post("/session/reset", summary="删除会话")
async def reset_session(
    request: SessionIdRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await svc.reset_session(db, request.conversation_id)
    return ApiResponse.ok(data=data)


@router.post("/session/rename", summary="重命名会话")
async def rename_session(
    request: RenameRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await svc.rename_session(db, request.conversation_id, request.title)
    return ApiResponse.ok(data=data)


@router.post("/session/recover", summary="恢复已删除会话")
async def recover_session(
    request: SessionIdRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await svc.recover_session(db, request.conversation_id)
    return ApiResponse.ok(data=data)


@router.post("/session/pin", summary="置顶/取消置顶会话")
async def pin_session(
    request: PinRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await svc.pin_session(db, request.conversation_id, request.pinned)
    return ApiResponse.ok(data=data)


@router.post("/session/list", summary="会话列表")
async def list_sessions_post(
    body: SessionListRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    req = body or SessionListRequest()
    data = await svc.list_sessions(db, req)
    return ApiResponse.ok(data=data)
