from __future__ import annotations

import random
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any, cast

import structlog
from prometheus_client import Counter, Gauge, Histogram

from app.observability.enums import SpanKind, SpanStatus
from app.observability.models import Score, SpanContext, Trace
from app.observability.storage import MySQLTraceStore

logger = structlog.get_logger(__name__)

# ── Prometheus 指标 ──────────────────────────────────────────────

STAGE_DURATION_SECONDS = Histogram(
    "stage_duration_seconds",
    "Stage duration in seconds",
    ["kind", "name", "status"],
)
STAGE_CALL_TOTAL = Counter(
    "stage_call_total",
    "Stage call count",
    ["kind", "name", "status"],
)

LLM_CALL_TOTAL = Counter(
    "llm_call_total",
    "LLM call count",
    ["model", "status"],
)
LLM_TOKEN_TOTAL = Counter(
    "llm_token_total",
    "LLM token count",
    ["model", "token_type"],
)
LLM_CALL_DURATION_SECONDS = Histogram(
    "llm_call_duration_seconds",
    "LLM call duration in seconds",
    ["model"],
)
LLM_COST_TOTAL = Counter(
    "llm_cost_total",
    "LLM cost total (USD)",
    ["model"],
)

# Prompt Caching（P0）：缓存命中/未命中 input token，命中率 = hit/(hit+miss)
LLM_CACHE_HIT_TOKEN_TOTAL = Counter(
    "llm_cache_hit_token_total",
    "LLM prompt tokens served from context cache",
    ["model"],
)
LLM_CACHE_MISS_TOKEN_TOTAL = Counter(
    "llm_cache_miss_token_total",
    "LLM prompt tokens not served from context cache",
    ["model"],
)

RETRIEVAL_EMPTY_TOTAL = Counter(
    "retrieval_empty_total",
    "Empty retrieval count",
    ["reason"],
)
RETRIEVAL_CHANNEL_TOTAL = Counter(
    "retrieval_channel_total",
    "Retrieval channel count",
    ["channel", "state"],
)

RETRIEVAL_CHANNEL_DURATION = Histogram(
    "retrieval_channel_duration_seconds",
    "Retrieval channel duration in seconds",
    ["channel"],
)

EVALUATION_SCORE = Gauge(
    "evaluation_score",
    "Evaluation metric score",
    ["metric_name"],
)

EVALUATION_SCORE_HISTOGRAM = Histogram(
    "evaluation_score_bucket",
    "Evaluation score distribution",
    ["metric_name"],
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

# ── Tracer ───────────────────────────────────────────────────────


class _DummySpan:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def span(self, **kwargs):
        return self

    def attach_score(self, **kwargs):
        pass

    @property
    def span_id(self):
        return ""

    @property
    def trace_id(self):
        return ""

    metadata: dict[str, Any] = {}
    output = None


_DUMMY_SPAN = _DummySpan()


class _DummyTracer:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def root(self, **kwargs):
        return _DUMMY_SPAN

    async def flush(self):
        pass

    def attach_score(self, **kwargs):
        pass

    def record_generation(self, *args, **kwargs):
        pass

    @property
    def langfuse_enabled(self):
        return False

    @property
    def current_span_id(self):
        return None

    @property
    def trace_id(self):
        return ""


class _SpanManager:
    def __init__(self, tracer: Tracer, span: SpanContext):
        self._tracer = tracer
        self._span = span

    async def __aenter__(self) -> SpanContext:
        self._span.started_at = datetime.now(UTC)
        self._tracer._push(self._span)
        return self._span

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        now = datetime.now(UTC)
        self._span.ended_at = now
        self._span.duration_ms = (now - self._span.started_at).total_seconds() * 1000
        if exc_type:
            self._span.status = SpanStatus.ERROR
        self._tracer._pop()

    def span(
        self, name: str, kind: SpanKind = SpanKind.PIPELINE, *, input: Any = None
    ) -> _SpanManager:
        child = SpanContext(
            span_id=next_id_str(),
            trace_id=self._span.trace_id,
            parent_span_id=self._span.span_id,
            kind=kind,
            name=name,
            input=input,
        )
        return _SpanManager(self._tracer, child)

    def attach_score(self, metric_name: str, value: float, *, reason: str | None = None) -> None:
        score = Score(
            score_id=next_id_str(),
            trace_id=self._span.trace_id,
            span_id=self._span.span_id,
            metric_name=metric_name,
            value=value,
            reason=reason,
        )
        self._span.scores.append(score)
        EVALUATION_SCORE.labels(metric_name=metric_name).set(value)
        EVALUATION_SCORE_HISTOGRAM.labels(metric_name=metric_name).observe(value)

    @property
    def span_id(self) -> str:
        return self._span.span_id

    @property
    def trace_id(self) -> str:
        return self._span.trace_id


def next_id_str() -> str:
    return uuid.uuid4().hex[:16]


class Tracer:
    def __init__(
        self,
        db: Any,
        trace_id: str,
        conversation_id: str,
        exchange_id: int,
        sample_rate: float = 1.0,
    ) -> None:
        self._db = db
        self._trace_id = trace_id
        self._conversation_id = conversation_id
        self._exchange_id = exchange_id
        self._active = random.random() < sample_rate
        self._stack: deque[SpanContext] = deque()
        self._completed_spans: list[SpanContext] = []
        self._trace: Trace | None = None
        self._root_span: SpanContext | None = None

        # Langfuse 并行上报（enabled 且采样命中时）
        self._lf_exporter: Any = None
        self._lf_obs: dict[str, Any] = {}
        self._lf_root_obs: Any = None
        if self._active:
            from app.observability.langfuse_client import get_langfuse

            _lf_client = get_langfuse()
            if _lf_client is not None:
                from app.observability.langfuse_backend import LangfuseTraceExporter

                self._lf_exporter = LangfuseTraceExporter(
                    _lf_client, trace_id, conversation_id, exchange_id
                )

    async def __aenter__(self) -> Tracer:
        if not self._active:
            return _DummyTracer()  # type: ignore[return-value]
        self._trace = Trace(
            trace_id=self._trace_id,
            conversation_id=self._conversation_id,
            exchange_id=self._exchange_id,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if not self._active:
            return
        while self._stack:
            self._pop()
        await self.flush()

    def span(
        self, name: str, kind: SpanKind = SpanKind.PIPELINE, *, input: Any = None
    ) -> _SpanManager:
        if not self._active:
            return cast(_SpanManager, _DUMMY_SPAN)
        parent = self._stack[-1] if self._stack else self._root_span
        span = SpanContext(
            span_id=next_id_str(),
            trace_id=self._trace_id,
            parent_span_id=parent.span_id if parent else None,
            kind=kind,
            name=name,
            input=input,
        )
        return _SpanManager(self, span)

    def root(
        self, name: str, kind: SpanKind = SpanKind.PIPELINE, *, input: Any = None
    ) -> _SpanManager:
        if not self._active:
            return _DUMMY_SPAN  # type: ignore[return-value]
        span = SpanContext(
            span_id=next_id_str(),
            trace_id=self._trace_id,
            kind=kind,
            name=name,
            input=input,
        )
        self._root_span = span
        if self._trace:
            self._trace.root_span_id = span.span_id
        if self._lf_exporter is not None:
            if self._trace is not None:
                self._lf_exporter.session_id = self._trace.session_id
            self._lf_root_obs = self._lf_exporter.start_root(
                name, input=input, kind=kind.value
            )
        return _SpanManager(self, span)

    async def flush(self) -> None:
        if not self._active or not self._trace:
            return
        self._trace.flushed_at = datetime.now(UTC)
        spans = self._completed_spans
        self._completed_spans = []

        # 包含根 span（它不在 _completed_spans 中）
        root_span = self._root_span
        all_spans = spans[:]
        if root_span:
            all_spans.append(root_span)

        self._populate_trace_from_spans(all_spans)
        store = MySQLTraceStore(self._db)
        try:
            # 流式链路中事务可能已被穿插的 commit/close 打乱（InvalidRequestError:
            # transaction already begun）——先结束隐式事务再 begin，保证 flush 干净
            from contextlib import suppress

            with suppress(Exception):
                await self._db.commit()
            async with self._db.begin():
                await store.save_trace(self._trace)
                await store.save_spans(all_spans)
                all_scores = [s for sp in all_spans for s in sp.scores]
                if all_scores:
                    await store.save_scores(all_scores)
        except Exception:
            logger.exception("trace flush failed", trace_id=self._trace_id)

        self._lf_finish()

    def _populate_trace_from_spans(self, spans: list[SpanContext]) -> None:
        if not self._trace:
            return
        if not self._trace.input:
            first_span = next((s for s in spans if s.input is not None), None)
            if first_span and first_span.input is not None:
                self._trace.input = (
                    str(first_span.input)
                    if not isinstance(first_span.input, str)
                    else first_span.input
                )
        if not self._trace.output:
            last_span = next((s for s in reversed(spans) if s.output is not None), None)
            if last_span and last_span.output is not None:
                self._trace.output = (
                    str(last_span.output)
                    if not isinstance(last_span.output, str)
                    else last_span.output
                )

    def attach_score(
        self,
        metric_name: str,
        value: float,
        *,
        reason: str | None = None,
        span_id: str | None = None,
    ) -> None:
        if not self._active:
            return
        target_span = None
        if span_id:
            for sp in self._stack:
                if sp.span_id == span_id:
                    target_span = sp
                    break
        if not target_span and self._stack:
            target_span = self._stack[-1]
        if not target_span and self._root_span:
            target_span = self._root_span
        if target_span:
            score = Score(
                score_id=next_id_str(),
                trace_id=self._trace_id,
                span_id=target_span.span_id,
                metric_name=metric_name,
                value=value,
                reason=reason,
            )
            target_span.scores.append(score)
            EVALUATION_SCORE.labels(metric_name=metric_name).set(value)
            EVALUATION_SCORE_HISTOGRAM.labels(metric_name=metric_name).observe(value)
            self._lf_score(target_span, metric_name, value, reason)

    def record_generation(
        self,
        name: str,
        *,
        model: str,
        input: Any = None,
        output: Any = None,
        usage: dict[str, int] | None = None,
        cost: dict[str, float] | None = None,
        level: str | None = None,
    ) -> None:
        """记录一次 LLM generation（挂在当前活跃 span 或根 span 下）。Langfuse 未启用时短路。"""
        if self._lf_exporter is None:
            return
        parent_obs = None
        if self._stack:
            parent_obs = self._lf_obs.get(self._stack[-1].span_id)
        if parent_obs is None:
            parent_obs = self._lf_root_obs
        if parent_obs is None:
            return
        self._lf_exporter.record_generation(
            parent_obs,
            name,
            model=model,
            input=input,
            output=output,
            usage_details=usage,
            cost_details=cost,
            level=level,
        )

    def append_span(self, span: SpanContext) -> None:
        if self._active:
            self._record_span_prometheus(span)
            self._completed_spans.append(span)
            self._lf_append(span)

    @property
    def current_span_id(self) -> str | None:
        if self._stack:
            return self._stack[-1].span_id
        if self._root_span:
            return self._root_span.span_id
        return None

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def langfuse_enabled(self) -> bool:
        return self._lf_exporter is not None

    # ── internal ─────────────────────────────────────────────
    def _push(self, span: SpanContext) -> None:
        self._stack.append(span)
        self._lf_start(span)

    def _pop(self) -> SpanContext | None:
        if not self._stack:
            return None
        span = self._stack.pop()
        self._lf_end(span)
        self._record_span_prometheus(span)
        self._completed_spans.append(span)
        return span

    @staticmethod
    def _record_span_prometheus(span: SpanContext) -> None:
        kind = span.kind.value
        name = span.name
        status = span.status.value
        STAGE_DURATION_SECONDS.labels(kind=kind, name=name, status=status).observe(
            (span.duration_ms or 0) / 1000
        )
        STAGE_CALL_TOTAL.labels(kind=kind, name=name, status=status).inc()

    # ── Langfuse 并行上报（enabled 时；未启用则 _lf_exporter 为 None，全部短路）──
    def _lf_parent_obs(self, span: SpanContext) -> Any:
        parent_obs = (
            self._lf_obs.get(span.parent_span_id or "") if span.parent_span_id else None
        )
        if parent_obs is None:
            parent_obs = self._lf_root_obs
        return parent_obs

    def _lf_start(self, span: SpanContext) -> None:
        if self._lf_exporter is None:
            return
        parent_obs = self._lf_parent_obs(span)
        if parent_obs is None:
            return
        obs = self._lf_exporter.start_span(
            parent_obs, span.name, input=span.input, kind=span.kind.value
        )
        self._lf_obs[span.span_id] = obs

    def _lf_append(self, span: SpanContext) -> None:
        """上报已完成的 span（如检索通道 span）：创建 observation 并立即结束。"""
        if self._lf_exporter is None:
            return
        parent_obs = self._lf_parent_obs(span)
        if parent_obs is None:
            return
        obs = self._lf_exporter.start_span(
            parent_obs, span.name, input=span.input, kind=span.kind.value
        )
        level = "ERROR" if span.status == SpanStatus.ERROR else None
        self._lf_exporter.end_span(obs, output=span.output, level=level)

    def _lf_end(self, span: SpanContext) -> None:
        if self._lf_exporter is None:
            return
        obs = self._lf_obs.pop(span.span_id, None)
        if obs is None:
            return
        level = "ERROR" if span.status == SpanStatus.ERROR else None
        self._lf_exporter.end_span(obs, output=span.output, level=level)

    def _lf_score(self, span: SpanContext, name: str, value: float, reason: str | None) -> None:
        if self._lf_exporter is None:
            return
        obs = self._lf_obs.get(span.span_id)
        if obs is None and self._root_span is not None and span.span_id == self._root_span.span_id:
            obs = self._lf_root_obs
        if obs is not None:
            self._lf_exporter.add_score(obs, name, value, reason=reason)

    def _lf_finish(self) -> None:
        if self._lf_exporter is None:
            return
        if self._lf_root_obs is not None:
            self._lf_exporter.end_span(
                self._lf_root_obs, output=self._trace.output if self._trace else None
            )
        self._lf_exporter.flush()
