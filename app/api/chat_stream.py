"""对话 API — /api/chat/stream (SSE 流式对话端点)"""

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db


class ChatRequest(BaseModel):
    """流式对话请求体 (与前端 Vue 3 约定格式完全一致)"""

    question: str = Field(..., min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, alias="conversationId")
    chat_mode: str = Field(default="auto", alias="chatMode")
    doc_ids: list[str] = Field(default_factory=list, alias="docIds")
    selected_document_id: str | None = Field(default=None, alias="selectedDocumentId")
    model_config = {"populate_by_name": True}

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post(
    "/stream",
    summary="流式对话",
    description="流式对话主入口，返回 SSE 事件流。支持 RAG 知识问答、联网搜索 Agent、图谱查询等多种执行模式。自动编排查询并分发到对应执行器。",
)
async def chat_stream(
    request: ChatRequest,
    fastapi_req: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    POST /api/chat/stream
    流式对话主入口，返回 SSE 流。
    """
    from app.chat.service import BusinessChatService

    service = BusinessChatService(db)
    return StreamingResponse(
        service.stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
