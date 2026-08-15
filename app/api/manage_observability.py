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


# ── Trace 链路观测（P2-2：自研 trace 三表的只读查询 UI 数据源）───────────────


class TracePageRequest(BaseModel):
    page_no: int = Field(1, alias="pageNo")
    page_size: int = Field(20, alias="pageSize", ge=1, le=100)
    conversation_id: str | None = Field(default=None, alias="conversationId")
    status: str | None = None  # error / ok（按 span 聚合状态过滤）
    date_from: str | None = Field(default=None, alias="from")
    date_to: str | None = Field(default=None, alias="to")
    model_config = {"populate_by_name": True}


async def _query_traces(
    db: AsyncSession,
    page_no: int,
    page_size: int,
    conversation_id: str | None,
    status: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[list[dict[str, Any]], int]:
    """trace 列表（原生 SQL：三表无 ORM 模型）"""
    from sqlalchemy import text

    where = ["1=1"]
    params: dict[str, Any] = {}
    if conversation_id:
        where.append("t.conversation_id = :conversation_id")
        params["conversation_id"] = conversation_id
    if date_from:
        where.append("t.created_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        where.append("t.created_at <= :date_to")
        params["date_to"] = date_to
    if status:
        where.append(
            "t.trace_id IN (SELECT trace_id FROM trace_observability_span WHERE status = :status)"
        )
        params["status"] = status
    where_sql = " AND ".join(where)

    total = (
        await db.execute(text(f"SELECT COUNT(*) FROM trace_observability t WHERE {where_sql}"), params)
    ).scalar() or 0

    rows = (
        await db.execute(
            text(
                f"""
                SELECT t.trace_id, t.conversation_id, t.exchange_id, t.root_span_id,
                       t.output, t.created_at, t.flushed_at,
                       (SELECT COUNT(*) FROM trace_observability_span s WHERE s.trace_id = t.trace_id) AS span_count,
                       (SELECT MIN(s.duration_ms) FROM trace_observability_span s
                         WHERE s.trace_id = t.trace_id AND s.parent_span_id IS NULL) AS root_duration_ms,
                       (SELECT MAX(s.status) FROM trace_observability_span s
                         WHERE s.trace_id = t.trace_id) AS span_status
                FROM trace_observability t
                WHERE {where_sql}
                ORDER BY t.created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": page_size, "offset": (page_no - 1) * page_size},
        )
    ).mappings()

    records = []
    for r in rows:
        records.append(
            {
                "traceId": r["trace_id"],
                "conversationId": r["conversation_id"],
                "exchangeId": r["exchange_id"],
                "spanCount": r["span_count"] or 0,
                "durationMs": float(r["root_duration_ms"]) if r["root_duration_ms"] else None,
                "status": r["span_status"] or "ok",
                "outputPreview": (r["output"] or "")[:300],
                "createdAt": r["created_at"].isoformat() if r["created_at"] else None,
            }
        )
    return records, int(total)


@router.get(
    "/observe/traces",
    summary="Trace 链路列表",
    description="分页查询自研 trace（trace_observability 三表），支持按会话/状态/时间过滤，返回关键指标卡片。",
)
async def list_traces(
    page_no: int = 1,
    page_size: int = 20,
    conversation_id: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    from sqlalchemy import text

    records, total = await _query_traces(
        db, page_no, page_size, conversation_id, status, date_from, date_to
    )

    # 关键指标卡片
    stats_row_mapping = (
        await db.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM trace_observability) AS total_traces,
                  (SELECT COUNT(*) FROM trace_observability
                    WHERE created_at >= CURDATE()) AS today_traces,
                  (SELECT COUNT(DISTINCT trace_id) FROM trace_observability_span
                    WHERE status = 'error') AS error_traces,
                  (SELECT ROUND(AVG(duration_ms), 1) FROM trace_observability_span
                    WHERE parent_span_id IS NULL) AS avg_root_duration_ms
                """
            )
        )
    ).mappings().first()
    stats_row: dict[str, Any] = dict(stats_row_mapping) if stats_row_mapping else {}

    stats = {
        "totalTraces": stats_row.get("total_traces") or 0,
        "todayTraces": stats_row.get("today_traces") or 0,
        "errorTraces": stats_row.get("error_traces") or 0,
        "avgRootDurationMs": float(stats_row.get("avg_root_duration_ms") or 0),
    }
    return ApiResponse.ok(
        data={
            "records": records,
            "total": total,
            "pageNo": page_no,
            "pageSize": page_size,
            "stats": stats,
        }
    )


@router.get(
    "/observe/traces/{trace_id}",
    summary="Trace 链路详情",
    description="单个 trace 的完整链路：trace 元信息 + span 瀑布（树形父子关系）+ 评估分数。",
)
async def get_trace_detail(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict[str, Any]:
    from sqlalchemy import text

    trace_row = (
        await db.execute(
            text(
                """
                SELECT trace_id, conversation_id, exchange_id, session_id, root_span_id,
                       input, output, metadata, tags, created_at, flushed_at
                FROM trace_observability WHERE trace_id = :trace_id
                """
            ),
            {"trace_id": trace_id},
        )
    ).mappings().first()
    if not trace_row:
        return ApiResponse.ok(data=None, message="trace 不存在")

    import json as _json

    def _loads(v: str | None) -> Any:
        if not v:
            return None
        try:
            return _json.loads(v)
        except Exception:
            return v

    spans = (
        await db.execute(
            text(
                """
                SELECT span_id, parent_span_id, kind, name, status,
                       started_at, ended_at, duration_ms, input, output
                FROM trace_observability_span
                WHERE trace_id = :trace_id
                ORDER BY started_at ASC
                """
            ),
            {"trace_id": trace_id},
        )
    ).mappings()
    span_list = [
        {
            "spanId": s["span_id"],
            "parentSpanId": s["parent_span_id"],
            "kind": s["kind"],
            "name": s["name"],
            "status": s["status"],
            "startedAt": s["started_at"].isoformat() if s["started_at"] else None,
            "endedAt": s["ended_at"].isoformat() if s["ended_at"] else None,
            "durationMs": s["duration_ms"],
            "input": _loads(s["input"]),
            "output": _loads(s["output"]),
        }
        for s in spans
    ]

    scores = (
        await db.execute(
            text(
                """
                SELECT score_id, span_id, metric_name, value, reason, created_at
                FROM trace_observability_score
                WHERE trace_id = :trace_id
                ORDER BY created_at ASC
                """
            ),
            {"trace_id": trace_id},
        )
    ).mappings()
    score_list = [
        {
            "scoreId": s["score_id"],
            "spanId": s["span_id"],
            "metricName": s["metric_name"],
            "value": float(s["value"]) if s["value"] is not None else None,
            "reason": s["reason"],
            "createdAt": s["created_at"].isoformat() if s["created_at"] else None,
        }
        for s in scores
    ]

    return ApiResponse.ok(
        data={
            "traceId": trace_row["trace_id"],
            "conversationId": trace_row["conversation_id"],
            "exchangeId": trace_row["exchange_id"],
            "sessionId": trace_row["session_id"],
            "rootSpanId": trace_row["root_span_id"],
            "input": _loads(trace_row["input"]),
            "output": _loads(trace_row["output"]),
            "metadata": _loads(trace_row["metadata"]),
            "tags": _loads(trace_row["tags"]),
            "createdAt": trace_row["created_at"].isoformat() if trace_row["created_at"] else None,
            "flushedAt": trace_row["flushed_at"].isoformat() if trace_row["flushed_at"] else None,
            "spans": span_list,
            "scores": score_list,
        }
    )
