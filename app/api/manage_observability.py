"""管理 API — /manage/observe/* + /manage/evaluation/* (可观测性面板、RAG 评估)"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import get_current_user
from app.api.schemas.manage_schema import (
    ChannelExecutionVO,
    ExchangeTraceVO,
    RetrievalResultVO,
)
from app.api.schemas.response import ApiResponse
from app.db.session import get_db

logger = structlog.get_logger(__name__)

router: APIRouter = APIRouter()


class EvaluationDatasetPageRequest(BaseModel):
    page_no: int = Field(1, alias="pageNo")
    page_size: int = Field(20, alias="pageSize")


class EvaluationRunRequest(BaseModel):
    dataset_ids: list[int] | None = Field(default=None, alias="datasetId")
    model_config = {"populate_by_name": True}


class EvaluationDeleteRequest(BaseModel):
    dataset_id: int = Field(..., alias="datasetId")
    model_config = {"populate_by_name": True}


# ── 可观测性面板 ──────────────────────────────────────────────────────────────


@router.get(
    "/observe/exchanges/{conversation_id}",
    summary="对话执行链路 Trace",
    description="获取单轮对话的完整执行链路，包含通道执行统计（向量/关键词检索的召回/采纳数）和检索结果详情（Chunk 评分排名）。",
)
async def get_exchange_trace(
    conversation_id: str,
    exchange_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    """GET /manage/observe/exchanges — 单轮对话执行链路 Trace"""
    from app.manage.service.document_service import (
        get_exchange_channel_executions,
        get_exchange_retrieval_results,
    )

    channels = await get_exchange_channel_executions(db, conversation_id, exchange_id)
    retrievals = await get_exchange_retrieval_results(db, conversation_id, exchange_id)

    channel_vos = []
    for c in channels:
        channel_vos.append(
            ChannelExecutionVO(
                sub_question=c.sub_question,
                channel=c.channel_type,
                recalled_count=c.recalled_count,
                accepted_count=c.accepted_count,
            )
        )

    retrieval_vos = []
    for r in retrievals:
        phase = "RETRIEVAL"
        if r.gate_passed:
            phase = "FUSION"
            if (
                (r.rerank_score and float(r.rerank_score) > 0)
                or r.is_selected
                or (r.selection_reason and "finalTopK" in r.selection_reason)
            ):
                phase = "RERANK"
        retrieval_vos.append(
            RetrievalResultVO(
                sub_question=r.sub_question,
                phase=phase,
                chunk_id=str(r.chunk_id) if r.chunk_id else None,  # type: ignore[arg-type]
                score=float(r.rerank_score or r.rrf_score or r.original_score or 0.0),
                rank=r.final_rank or r.rrf_rank or r.channel_rank or 999,
            )
        )

    vo = ExchangeTraceVO(
        conversation_id=conversation_id,
        exchange_id=exchange_id,
        channel_executions=channel_vos,
        retrieval_results=retrieval_vos,
    )
    return ApiResponse.ok(data=vo.model_dump(by_alias=True))


# ── RAG 评估 ──────────────────────────────────────────────────────────────────


@router.post(
    "/evaluation/dataset/page/query",
    summary="查询评估数据集",
    description="分页查询 RAG 评估的 Golden Dataset 数据项",
)
async def list_evaluation_dataset(
    req: EvaluationDatasetPageRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    from app.manage.service.document_service import query_evaluation_dataset_page

    records, total = await query_evaluation_dataset_page(db, req.page_no, req.page_size)

    data_list = [
        {
            "id": str(r.id),
            "question": r.question,
            "groundTruth": r.ground_truth,
            "status": r.status,
            "sourceType": r.source_type,
            "conversationId": r.conversation_id,
            "faithfulnessScore": float(r.faithfulness_score)
            if r.faithfulness_score is not None
            else None,
            "answerRelevancyScore": float(r.answer_relevancy_score)
            if r.answer_relevancy_score is not None
            else None,
            "contextPrecisionScore": float(r.context_precision_score)
            if r.context_precision_score is not None
            else None,
            "contextRecallScore": float(r.context_recall_score)
            if r.context_recall_score is not None
            else None,
            "answerCorrectnessScore": float(r.answer_correctness_score)
            if r.answer_correctness_score is not None
            else None,
            "evalMessage": r.eval_message,
            "evaluatedAt": r.evaluated_at.isoformat() if r.evaluated_at else None,
            "createdAt": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]
    return ApiResponse.ok(
        data={
            "records": data_list,
            "total": total,
            "pageNo": req.page_no,
            "pageSize": req.page_size,
        }
    )


@router.post(
    "/evaluation/dataset/run",
    summary="触发评估任务",
    description="对指定 ID 或所有待评估状态的数据触发 Ragas 评估 Celery 任务",
)
async def run_evaluation_dataset(
    req: EvaluationRunRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    from app.chat.tasks import task_evaluate_dataset_item
    from app.manage.service.document_service import run_evaluation_dataset

    records = await run_evaluation_dataset(db, req.dataset_ids)

    if not records:
        return ApiResponse.ok(data={"message": "没有找到需要评估的数据", "count": 0})

    for r in records:
        task_evaluate_dataset_item.delay(r.id)

    return ApiResponse.ok(
        data={"message": f"已成功触发 {len(records)} 条评估任务", "count": len(records)}
    )


@router.post(
    "/evaluation/dataset/delete",
    summary="删除评估数据",
    description="删除 Golden Dataset 中的一条记录",
)
async def delete_evaluation_dataset(
    req: EvaluationDeleteRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    from app.manage.service.document_service import delete_evaluation_record

    await delete_evaluation_record(db, req.dataset_id)
    return ApiResponse.ok(data={"message": "删除成功"})
