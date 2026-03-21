from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.models import Score, SpanContext, Trace


class MySQLTraceStore:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def save_trace(self, trace: Trace) -> None:
        stmt = text("""
            INSERT INTO trace_observability
                (trace_id, conversation_id, exchange_id, session_id,
                 root_span_id, input, output, metadata, tags, created_at, flushed_at)
            VALUES
                (:trace_id, :conversation_id, :exchange_id, :session_id,
                 :root_span_id, :input, :output, :metadata, :tags, :created_at, :flushed_at)
            ON DUPLICATE KEY UPDATE
                output = VALUES(output),
                flushed_at = VALUES(flushed_at)
        """)
        await self._db.execute(stmt, {
            "trace_id": trace.trace_id,
            "conversation_id": trace.conversation_id,
            "exchange_id": trace.exchange_id,
            "session_id": trace.session_id,
            "root_span_id": trace.root_span_id,
            "input": _truncated_json(trace.input),
            "output": _truncated_json(trace.output),
            "metadata": _json(trace.metadata),
            "tags": _json(trace.tags),
            "created_at": trace.created_at,
            "flushed_at": trace.flushed_at,
        })

    async def save_spans(self, spans: list[SpanContext]) -> None:
        if not spans:
            return
        stmt = text("""
            INSERT INTO trace_observability_span
                (span_id, trace_id, parent_span_id, kind, name, status,
                 started_at, ended_at, duration_ms, input, output, metadata, tags)
            VALUES
                (:span_id, :trace_id, :parent_span_id, :kind, :name, :status,
                 :started_at, :ended_at, :duration_ms, :input, :output, :metadata, :tags)
            ON DUPLICATE KEY UPDATE
                status = VALUES(status),
                ended_at = VALUES(ended_at),
                duration_ms = VALUES(duration_ms),
                output = VALUES(output)
        """)
        params = [
            {
                "span_id": sp.span_id,
                "trace_id": sp.trace_id,
                "parent_span_id": sp.parent_span_id,
                "kind": sp.kind.value,
                "name": sp.name,
                "status": sp.status.value,
                "started_at": sp.started_at,
                "ended_at": sp.ended_at,
                "duration_ms": sp.duration_ms,
                "input": _truncated_json(sp.input),
                "output": _truncated_json(sp.output),
                "metadata": _json(sp.metadata),
                "tags": _json(sp.tags),
            }
            for sp in spans
        ]
        await self._db.execute(stmt, params)

    async def save_scores(self, scores: list[Score]) -> None:
        if not scores:
            return
        stmt = text("""
            INSERT INTO trace_observability_score
                (score_id, trace_id, span_id, metric_name, value, reason, metadata, created_at)
            VALUES
                (:score_id, :trace_id, :span_id, :metric_name, :value, :reason, :metadata, :created_at)
            ON DUPLICATE KEY UPDATE
                value = VALUES(value),
                reason = VALUES(reason)
        """)
        params = [
            {
                "score_id": sc.score_id,
                "trace_id": sc.trace_id,
                "span_id": sc.span_id,
                "metric_name": sc.metric_name,
                "value": sc.value,
                "reason": sc.reason,
                "metadata": _json(sc.metadata),
                "created_at": sc.created_at,
            }
            for sc in scores
        ]
        await self._db.execute(stmt, params)


_MAX_IO_LENGTH = 65535


def _json(val: Any) -> str | None:
    if val is None:
        return None
    return json.dumps(val, default=str)


def _truncated_json(val: Any) -> str | None:
    if val is None:
        return None
    s = json.dumps(val, default=str)
    if len(s) > _MAX_IO_LENGTH:
        return s[:_MAX_IO_LENGTH]
    return s
