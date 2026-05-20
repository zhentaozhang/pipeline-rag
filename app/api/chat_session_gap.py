"""对话 API — /api/chat/* (GAP 兼容、RAG 评估)"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


class SessionIdRequest(BaseModel):
    conversation_id: str = Field(..., alias="conversationId")
    model_config = {"populate_by_name": True}


class RetrievalObserveRequest(BaseModel):
    conversation_id: str = Field(..., alias="conversationId")
    exchange_id: str = Field(..., alias="exchangeId")
    model_config = {"populate_by_name": True}


class RAGEvaluationRequest(BaseModel):
    conversation_id: str = Field(..., alias="conversationId")
    exchange_id: str = Field(..., alias="exchangeId")
    model_config = {"populate_by_name": True}


@router.post(
    "/document/options",
    summary="可选文档列表",
)
async def get_document_options(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.api.schemas.response import ApiResponse
    from app.db.models.document import Document

    result = await db.execute(
        select(Document).where(Document.index_status == 3).order_by(Document.document_name)
    )
    docs = result.scalars().all()
    data = [
        {
            "docId": str(d.doc_id),
            "title": d.document_name or "",
            "knowledgeScopeName": d.knowledge_scope_name or "",
            "businessCategory": d.business_category or "",
            "documentTags": (d.document_tags or "").split(",") if d.document_tags else [],
        }
        for d in docs
    ]
    return ApiResponse.ok(data=data)


@router.post(
    "/session/summary/rebuild",
    summary="重新生成会话摘要",
)
async def rebuild_summary(
    request: SessionIdRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.api.schemas.response import ApiResponse
    from app.chat.memory_service import PersistentConversationMemoryService

    memory_service = PersistentConversationMemoryService(db)
    await memory_service.rebuild_summary(request.conversation_id)
    summary_view = None

    return ApiResponse.ok(
        data={
            "conversationId": request.conversation_id,
            "summary": summary_view.summary_text if summary_view else "",
        }
    )


@router.post(
    "/exchange/retrieval/results",
    summary="检索结果详情",
)
async def get_retrieval_results(
    request: RetrievalObserveRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.api.schemas.response import ApiResponse
    from app.db.models.rag_observability import ConversationRetrievalResult

    stmt = (
        select(ConversationRetrievalResult)
        .where(
            ConversationRetrievalResult.conversation_id == request.conversation_id,
            ConversationRetrievalResult.exchange_id == int(request.exchange_id),
        )
        .order_by(ConversationRetrievalResult.id)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    data = []
    for r in items:
        phase = "RETRIEVAL"
        if r.gate_passed:
            phase = "FUSION"
            if (
                (r.rerank_score and float(r.rerank_score) > 0)
                or r.is_selected
                or (r.selection_reason and "finalTopK" in r.selection_reason)
            ):
                phase = "RERANK"

        data.append(
            {
                "sub_question": r.sub_question,
                "phase": phase,
                "chunk_id": str(r.chunk_id) if r.chunk_id else None,
                "score": float(r.rerank_score or r.rrf_score or r.original_score or 0.0),
                "rank": r.final_rank or r.rrf_rank or r.channel_rank or 999,
                "gate_passed": bool(r.gate_passed),
                "is_selected": bool(r.is_selected),
            }
        )
    return ApiResponse.ok(data=data)


@router.post(
    "/exchange/channel/executions",
    summary="检索通道执行详情",
)
async def get_channel_executions(
    request: RetrievalObserveRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.api.schemas.response import ApiResponse
    from app.db.models.rag_observability import ConversationChannelExecution

    stmt = select(ConversationChannelExecution).where(
        ConversationChannelExecution.conversation_id == request.conversation_id,
        ConversationChannelExecution.exchange_id == int(request.exchange_id),
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    data = [
        {
            "sub_question": c.sub_question,
            "channel": str(c.channel_type).upper(),
            "recalled_count": c.recalled_count,
            "accepted_count": c.accepted_count,
        }
        for c in items
    ]
    return ApiResponse.ok(data=data)


@router.post(
    "/exchange/evaluation",
    summary="RAG 质量评估结果",
)
async def get_rag_evaluation(
    request: RAGEvaluationRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.api.schemas.response import ApiResponse
    from app.db.models.rag_observability import ConversationRAGEvaluation

    stmt = select(ConversationRAGEvaluation).where(
        ConversationRAGEvaluation.conversation_id == request.conversation_id,
        ConversationRAGEvaluation.exchange_id == int(request.exchange_id),
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if record is None:
        return ApiResponse.ok(
            data={
                "exchangeId": int(request.exchange_id),
                "evalStatus": "pending",
                "evalMessage": None,
            }
        )

    data = {
        "exchangeId": record.exchange_id,
        "faithfulnessScore": float(record.faithfulness_score)
        if record.faithfulness_score
        else None,
        "answerRelevancyScore": float(record.answer_relevancy_score)
        if record.answer_relevancy_score
        else None,
        "contextPrecisionScore": float(record.context_precision_score)
        if record.context_precision_score
        else None,
        "evalStatus": record.eval_status,
        "evalMessage": record.eval_message,
        "evaluatedAt": record.evaluated_at.isoformat() if record.evaluated_at else None,
    }
    return ApiResponse.ok(data=data)


@router.post(
    "/evaluation/summary",
    summary="RAG 评估全局汇总",
)
async def get_rag_evaluation_summary(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from sqlalchemy import func, select

    from app.api.schemas.response import ApiResponse
    from app.db.models.rag_observability import ConversationRAGEvaluation

    stmt = select(
        func.count(ConversationRAGEvaluation.id),
        func.avg(ConversationRAGEvaluation.faithfulness_score),
        func.avg(ConversationRAGEvaluation.answer_relevancy_score),
        func.avg(ConversationRAGEvaluation.context_precision_score),
    ).where(ConversationRAGEvaluation.eval_status == "completed")

    result = await db.execute(stmt)
    row = result.one()

    data = {
        "totalCount": row[0] or 0,
        "avgFaithfulness": float(row[1]) if row[1] else None,
        "avgAnswerRelevancy": float(row[2]) if row[2] else None,
        "avgContextPrecision": float(row[3]) if row[3] else None,
    }
    return ApiResponse.ok(data=data)
