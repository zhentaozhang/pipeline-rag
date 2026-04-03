"""对话 API — /api/chat/exchange/* (对话轮次)"""

import json
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import ChatTurnStatus
from app.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


class ExchangeIdRequest(BaseModel):
    conversation_id: str = Field(..., alias="conversationId")
    exchange_id: int = Field(..., alias="exchangeId")
    model_config = {"populate_by_name": True}

    @field_validator("exchange_id", mode="before")
    @classmethod
    def coerce_exchange_id(cls, v: Any) -> int:
        return int(v)


class EvaluationFeedbackRequest(BaseModel):
    conversation_id: str = Field(..., alias="conversationId")
    exchange_id: int = Field(..., alias="exchangeId")
    ground_truth: str = Field(..., alias="groundTruth", min_length=1)
    model_config = {"populate_by_name": True}


class ExchangeRatingRequest(BaseModel):
    conversation_id: str = Field(..., alias="conversationId")
    exchange_id: int = Field(..., alias="exchangeId")
    rating: int = Field(..., ge=-1, le=1, description="1=点赞, -1=踩")
    comment: str | None = Field(None, max_length=500)
    model_config = {"populate_by_name": True}


def _camel_case_keys(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if not d:
        return d
    keys = list(d.keys())
    for k in keys:
        parts = k.split("_")
        camel = parts[0] + "".join(p.capitalize() for p in parts[1:]) if "_" in k else k
        if camel != k:
            d[camel] = d.pop(k)
    for v in d.values():
        if isinstance(v, dict):
            _camel_case_keys(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    _camel_case_keys(item)
    return d


@router.post(
    "/exchange/detail",
    summary="获取对话轮次详情",
)
async def get_exchange_detail(request: "ExchangeIdRequest", db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select

    from app.api.schemas.chat_schema import ExchangeVO
    from app.api.schemas.response import ApiResponse
    from app.chat.store import ConversationArchiveStore
    from app.db.models.conversation import ConversationExchange
    from app.db.models.rag_observability import ConversationTraceStage

    try:
        archive_store = ConversationArchiveStore(db)
        session_record = await archive_store.get_session(request.conversation_id)
        if not session_record:
            return ApiResponse.fail("会话不存在: " + request.conversation_id)

        stmt = select(ConversationExchange).where(
            ConversationExchange.id == request.exchange_id,
            ConversationExchange.conversation_id == request.conversation_id,
        )
        exchange = (await db.execute(stmt)).scalar_one_or_none()

        if not exchange:
            return ApiResponse.fail("轮次不存在: " + str(request.exchange_id))

        try:
            references = json.loads(exchange.references) if exchange.references else []
        except (json.JSONDecodeError, TypeError):
            references = []
        try:
            recommendations = (
                json.loads(exchange.recommendations) if exchange.recommendations else []
            )
        except (json.JSONDecodeError, TypeError):
            recommendations = []
        try:
            used_tools = json.loads(exchange.used_tools) if exchange.used_tools else []
        except (json.JSONDecodeError, TypeError):
            used_tools = []
        try:
            debug_trace = (
                json.loads(exchange.debug_trace_json) if exchange.debug_trace_json else None
            )
        except (json.JSONDecodeError, TypeError):
            debug_trace = None
        try:
            thinking_steps = json.loads(exchange.thinking_steps) if exchange.thinking_steps else []
        except (json.JSONDecodeError, TypeError):
            thinking_steps = []

        VALID_TURN_STATUSES = (1, 2, 3, 4)
        turn_status_name = (
            ChatTurnStatus(exchange.turn_status).name
            if exchange.turn_status in VALID_TURN_STATUSES
            else None
        )

        exec_mode = exchange.execution_mode
        if not exec_mode and debug_trace:
            exec_mode = debug_trace.get("execution_mode") or debug_trace.get("executionMode") or ""

        exchange_data = ExchangeVO(
            id=str(exchange.id),
            conversation_id=exchange.conversation_id,
            question=exchange.question,
            answer=exchange.answer,
            tokens_used=exchange.tokens_used,
            created_at=exchange.created_at.isoformat() if exchange.created_at else None,
            execution_mode=exec_mode or "",
            turn_status=exchange.turn_status,
            first_response_time_ms=exchange.first_response_time_ms,
            thinking_steps=exchange.thinking_steps or "",
            references=references,
            recommendations=recommendations,
        ).model_dump(by_alias=True)

        exchange_data["exchangeId"] = str(exchange.id)
        exchange_data["status"] = turn_status_name
        exchange_data["editTime"] = exchange.updated_at.isoformat() if exchange.updated_at else None
        exchange_data["totalResponseTimeMs"] = exchange.total_response_time_ms
        exchange_data["errorMessage"] = exchange.error_message or ""
        exchange_data["usedTools"] = used_tools
        exchange_data["debugTrace"] = _camel_case_keys(debug_trace)
        exchange_data["thinkingSteps"] = thinking_steps

        trace_stmt = (
            select(ConversationTraceStage)
            .where(
                ConversationTraceStage.conversation_id == request.conversation_id,
                ConversationTraceStage.exchange_id == request.exchange_id,
            )
            .order_by(ConversationTraceStage.id)
        )
        trace_result = await db.execute(trace_stmt)
        stages = trace_result.scalars().all()
        stage_traces = [
            {
                "stageId": s.id,
                "stageCode": s.stage_code,
                "stageName": s.stage_name or s.stage_code,
                "stageState": (
                    ChatTurnStatus(s.stage_state).name
                    if s.stage_state in VALID_TURN_STATUSES
                    else None
                ),
                "stageOrder": s.stage_order,
                "stageLevel": s.stage_level,
                "parentStageId": s.parent_stage_id,
                "startTime": s.start_time.isoformat() if s.start_time else None,
                "endTime": s.end_time.isoformat() if s.end_time else None,
                "durationMs": s.duration_ms,
                "summaryText": s.summary_text or "",
                "errorMessage": s.error_message or "",
                "snapshotJson": s.snapshot_json or "",
            }
            for s in stages
        ]

        return ApiResponse.ok(
            data={
                "exchange": exchange_data,
                "stageTraces": stage_traces,
            }
        )
    except Exception:
        logger.error("获取对话轮次详情异常", exc_info=True)
        return ApiResponse.fail("获取对话轮次详情失败，请稍后重试")


@router.post(
    "/exchange/feedback",
    summary="提交会话反馈 (Ground Truth)",
)
async def submit_exchange_feedback(
    request: EvaluationFeedbackRequest,
    fastapi_req: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.api.schemas.response import ApiResponse
    from app.db.models.conversation import ConversationExchange
    from app.db.models.rag_observability import RagEvaluationDataset

    stmt = select(ConversationExchange).where(
        ConversationExchange.id == request.exchange_id,
        ConversationExchange.conversation_id == request.conversation_id,
    )
    exchange = (await db.execute(stmt)).scalar_one_or_none()
    if not exchange:
        return ApiResponse.fail("对话轮次不存在")

    tenant_id = getattr(fastapi_req, "tenant_id", "default")

    dataset = RagEvaluationDataset(
        tenant_id=tenant_id,
        question=exchange.question,
        ground_truth=request.ground_truth,
        contexts=exchange.references,
        exchange_id=request.exchange_id,
        conversation_id=request.conversation_id,
        source_type="user_feedback",
    )
    db.add(dataset)
    await db.commit()

    return ApiResponse.ok(data={"message": "感谢您的反馈，已加入评测库。"})


@router.post(
    "/rate",
    summary="点赞/踩反馈",
)
async def rate_exchange(
    request: ExchangeRatingRequest,
    fastapi_req: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.api.schemas.response import ApiResponse
    from app.db.models.rag_observability import ChatExchangeFeedback
    from app.observability.metrics import EXCHANGE_RATING_TOTAL

    tenant_id = getattr(fastapi_req, "tenant_id", "default")
    feedback = ChatExchangeFeedback(
        conversation_id=request.conversation_id,
        exchange_id=request.exchange_id,
        tenant_id=tenant_id,
        rating=request.rating,
        comment=request.comment,
    )
    db.add(feedback)
    await db.commit()

    label = "thumbs_up" if request.rating == 1 else "thumbs_down"
    EXCHANGE_RATING_TOTAL.labels(rating=label).inc()
    logger.info("exchange rated", rating=label, exchange_id=request.exchange_id)

    return ApiResponse.ok(data={"message": "感谢您的评价！"})
