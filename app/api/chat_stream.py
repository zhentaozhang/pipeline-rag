"""对话 API — /api/chat/stream (SSE 流式对话端点)

断线续传（第二轮架构评审·可以优化 4）：事件同时写入 Redis 缓冲（TTL 3min），
客户端断线后带 `resume` 参数重连 → 服务端重放未消费事件（含 DONE 则直接收尾；
原流仍在执行则重放后进入正常流，由租约锁返回「执行中」提示）。
"""

import json

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

logger = structlog.get_logger(__name__)

_BUFFER_KEY_PREFIX = "pipeline_rag:sse:buf"
_BUFFER_TTL_S = 180
_BUFFER_MAX_EVENTS = 500


class ChatRequest(BaseModel):
    """流式对话请求体 (与前端 React 约定格式完全一致)"""

    question: str = Field(..., min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, alias="conversationId")
    chat_mode: str = Field(default="auto", alias="chatMode")
    doc_ids: list[str] = Field(default_factory=list, alias="docIds")
    selected_document_id: str | None = Field(default=None, alias="selectedDocumentId")
    user_key: str | None = Field(default=None, alias="userKey")  # P3：用户级事实记忆维度
    model_config = {"populate_by_name": True}


router = APIRouter()


def _buffer_key(conversation_id: str) -> str:
    return f"{_BUFFER_KEY_PREFIX}:{conversation_id}"


async def _append_event(conversation_id: str, raw: str) -> None:
    """事件写入 Redis 缓冲（失败静默降级，不影响主流程）"""
    if not conversation_id:
        return
    try:
        from app.infra.redis_lease import get_redis

        redis = get_redis()
        key = _buffer_key(conversation_id)
        await redis.rpush(key, raw)
        await redis.ltrim(key, -_BUFFER_MAX_EVENTS, -1)
        await redis.expire(key, _BUFFER_TTL_S)
    except Exception:
        logger.warning("sse buffer append failed", conversation_id=conversation_id, exc_info=True)


async def _replay_events(conversation_id: str, resume: int) -> list[str]:
    """重放缓冲中第 resume 条之后（0 基）的事件；缓冲不可用返回空列表"""
    if not conversation_id or resume <= 0:
        return []
    try:
        from app.infra.redis_lease import get_redis

        redis = get_redis()
        key = _buffer_key(conversation_id)
        raw = await redis.lrange(key, resume, -1)
        return [str(e) for e in raw]
    except Exception:
        logger.warning("sse buffer replay failed", conversation_id=conversation_id, exc_info=True)
        return []


def _contains_done(events: list[str]) -> bool:
    for raw in events:
        line = raw.strip()
        if line.startswith("data:"):
            line = line[len("data:"):].strip()
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if payload.get("type") == "done":
            return True
    return False


@router.post(
    "/stream",
    summary="流式对话",
    description="流式对话主入口，返回 SSE 事件流。支持 RAG 知识问答、联网搜索 Agent、图谱查询等多种执行模式。自动编排查询并分发到对应执行器。断线重连可传 ?resume=N 续传未消费事件。",
)
async def chat_stream(
    request: ChatRequest,
    fastapi_req: Request,
    db: AsyncSession = Depends(get_db),
    resume: int = Query(default=0, ge=0, le=_BUFFER_MAX_EVENTS, description="已消费事件数（断线续传）"),
) -> StreamingResponse:
    """
    POST /api/chat/stream?resume=N
    流式对话主入口，返回 SSE 流。
    """
    from app.chat.service import BusinessChatService

    conversation_id = request.conversation_id or ""

    async def _event_source():
        # 断线续传：先重放未消费缓冲
        if resume > 0:
            replayed = await _replay_events(conversation_id, resume)
            for raw in replayed:
                yield raw
            if _contains_done(replayed):
                logger.info("sse resumed from buffer", conversation_id=conversation_id, count=len(replayed))
                return

        # 正常流式执行（事件同步写缓冲）
        service = BusinessChatService(db)
        async for raw in service.stream(request):
            await _append_event(conversation_id, raw)
            yield raw

    return StreamingResponse(
        _event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
