"""
RAG 双通道检索引擎主入口

流程：
1. asyncio 并行执行 SubQuestion 检索（含超时 + exceptionally 降级）
2. 每个 SubQuestion 内 channels 并行执行
3. EvidenceGate 过滤低质量命中
4. RRF 融合（K=60）
5. ParentBlock 提升（Child 检索 → Parent 上下文）
6. Rerank 精排（可选）
7. Top-K 截取 → 分配 Reference ID → 留痕溯源 (Trace)
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from app.chat.schema import Evidence, ExecutionPlan, SubQuestion, SubQuestionEvidence
from app.config import get_settings
from app.observability.enums import SpanKind, SpanStatus
from app.observability.metrics import (
    RETRIEVAL_CHANNEL_DURATION,
    RETRIEVAL_CHANNEL_TOTAL,
    RETRIEVAL_EMPTY_TOTAL,
)
from app.observability.models import SpanContext
from app.observability.tracer import next_id_str
from app.rag.fusion import rrf_fusion
from app.rag.parent_block import ParentBlockElevator

logger = structlog.get_logger(__name__)
settings = get_settings()


@dataclass
class RagRetrievalContext:
    """RAG 检索上下文：保存各子问题的检索结果"""

    retrieval_question: str = ""
    sub_question_evidence_list: list[SubQuestionEvidence] = field(default_factory=list)
    retrieval_notes: list[str] = field(default_factory=list)
    used_channels: set[str] = field(default_factory=set)

    @property
    def is_empty(self) -> bool:
        return not self.sub_question_evidence_list or all(
            not se.evidences for se in self.sub_question_evidence_list
        )


@dataclass
class RetrievalChannelResult:
    """单个检索通道的结果"""

    channel_name: str
    documents: list[Evidence] = field(default_factory=list)
    duration_ms: int = 0
    error_message: str = ""
    recalled_count: int = 0
    accepted_count: int = 0
    avg_score: float = 0.0


class RagRetrievalEngine:
    """
    双通道 RAG 检索引擎，包含：
    - 子问题并行 + 通道并行
    - EvidenceGate
    - RRF 融合
    - ParentBlock 提升
    - Rerank
    - 引用ID分配
    - 留痕记录
    """

    def __init__(self, db=None) -> None:
        self.db = db

    async def retrieve(self, plan: ExecutionPlan, tracer: Any = None) -> RagRetrievalContext:
        """完整检索流程入口。"""
        context = RagRetrievalContext(
            retrieval_question=plan.retrieval_question or plan.original_question,
            used_channels=set(),
            retrieval_notes=[],
        )

        from app.rag.retrieve_request_factory import DocumentRetrieveRequestFactory

        plan = await DocumentRetrieveRequestFactory().build(plan)

        retrieval_sub_qs = plan.retrieval_sub_questions
        if retrieval_sub_qs:
            sub_questions = [
                SubQuestion(index=i, text=q, original=plan.original_question)
                for i, q in enumerate(retrieval_sub_qs)
            ]
        elif plan.sub_questions:
            sub_questions = plan.sub_questions
        else:
            sub_q = plan.retrieval_question or plan.original_question
            sub_questions = [SubQuestion(index=0, text=sub_q, original=plan.original_question)]

        # ── 子问题并行，每个有超时保护 ─────────────────────────────
        per_sub_timeout = max(settings.rag.sub_question_timeout_ms / 1000.0, 0.001)

        _collected_spans: list[SpanContext] = []

        async def _retrieve_with_timeout(sq: SubQuestion, idx: int):
            try:
                return await asyncio.wait_for(
                    self._retrieve_one(
                        sq,
                        idx + 1,
                        plan,
                        context.used_channels,
                        context.retrieval_notes,
                        collected_spans_out=_collected_spans,
                        tracer=tracer,
                    ),
                    timeout=per_sub_timeout,
                )
            except Exception as e:
                # 体检 C5：静默降级可见化
                from app.observability.metrics import DEGRADATION_TOTAL

                DEGRADATION_TOTAL.labels(reason="sub_question_timeout").inc()
                logger.warning(
                    "子问题检索失败或超时，已自动忽略",
                    sub_question_index=idx + 1,
                    sub_question=sq.text[:50],
                    error=str(e),
                    exc_info=True,
                )
                context.retrieval_notes.append(f"子问题{idx + 1}检索失败或超时，已自动忽略。")
                return SubQuestionEvidence(
                    sub_question=sq,
                    evidences=[],
                    channel_trace={},
                    fused_candidate_count=0,
                    parent_candidate_count=0,
                    reranked_candidate_count=0,
                )

        tasks = [_retrieve_with_timeout(sq, i) for i, sq in enumerate(sub_questions)]
        evidence_list = await asyncio.gather(*tasks)

        # 把并行阶段收集的 span 挂到 tracer 上（此时不再并发）
        if tracer and _collected_spans:
            for sp in _collected_spans:
                tracer.append_span(sp)

        accepted_count = sum(1 for se in evidence_list if se.evidences)
        logger.info(
            "RAG 检索完成",
            retrieval_question=context.retrieval_question[:50],
            original_sub_count=len(sub_questions),
            accepted_sub_count=accepted_count,
            notes=context.retrieval_notes,
        )

        self._assign_reference_ids(evidence_list)
        context.sub_question_evidence_list = evidence_list
        return context

    async def retrieve_with_correction(
        self, plan: ExecutionPlan, tracer: Any = None
    ) -> RagRetrievalContext:
        """Corrective Retrieval：证据不足时改写查询重查，最多 corrective_retrieval_max_rounds 轮。"""
        context = await self.retrieve(plan, tracer=tracer)
        max_rounds = settings.rag.corrective_retrieval_max_rounds
        if not settings.rag.corrective_retrieval_enabled or max_rounds <= 0:
            return context

        base_question = (plan.rewritten_question or plan.original_question).strip()
        corrected = False
        for _ in range(max_rounds):
            if not context.is_empty:
                break
            rewritten = await self._rewrite_query(base_question)
            if not rewritten or rewritten == base_question:
                break
            corrected = True
            plan.retrieval_question = rewritten
            plan.retrieval_sub_questions = [rewritten]
            context = await self.retrieve(plan, tracer=tracer)
            context.retrieval_notes.append(
                f"检索证据不足，已按改写查询重查：{rewritten[:80]}"
            )

        if corrected:
            logger.info(
                "corrective_retrieval_done",
                retrieval_question=context.retrieval_question[:50],
                still_empty=context.is_empty,
                notes=context.retrieval_notes,
            )
        return context

    async def _rewrite_query(self, question: str) -> str:
        """复用查询改写服务，强制改写为更利于检索的形式。"""
        if not question:
            return ""
        try:
            from app.orchestrator.query_rewriter import ChatQueryRewriteService

            result = await ChatQueryRewriteService().rewrite(question, force=True)
            return (result.rewritten or "").strip()
        except Exception as e:
            logger.warning("corrective_retrieval_rewrite_failed", error=str(e), exc_info=True)
            return ""

    async def _retrieve_one(
        self,
        sub_q: SubQuestion,
        sub_question_index: int,
        plan: ExecutionPlan,
        used_channels: set[str],
        notes: list[str],
        collected_spans_out: list[SpanContext] | None = None,
        tracer: Any = None,
    ) -> SubQuestionEvidence:
        """单个子问题的完整检索管道。"""
        trace_id = tracer.trace_id if tracer else ""
        parent_span_id = tracer.current_span_id if tracer else None

        raw_results = await self._parallel_channel_retrieve(sub_q, sub_question_index, notes)
        if not raw_results:
            return SubQuestionEvidence(
                sub_question=sub_q,
                evidences=[],
                channel_trace={},
                fused_candidate_count=0,
                parent_candidate_count=0,
                reranked_candidate_count=0,
            )

        # ── 创建通道 span（使用预录制的 timing）────────────────────
        for r in raw_results:
            if collected_spans_out is not None:
                ended_at = datetime.now(UTC)
                sp = SpanContext(
                    span_id=next_id_str(),
                    trace_id=trace_id,
                    parent_span_id=parent_span_id,
                    kind=SpanKind.CHANNEL,
                    name=f"{r.channel_name}_channel",
                    status=SpanStatus.ERROR if r.error_message else SpanStatus.OK,
                    started_at=ended_at - timedelta(milliseconds=r.duration_ms),
                    ended_at=ended_at,
                    duration_ms=r.duration_ms,
                    metadata={
                        "recalled": r.recalled_count,
                        "accepted": r.accepted_count,
                        "avg_score": r.avg_score,
                    },
                )
                collected_spans_out.append(sp)

        channel_results = [self._apply_evidence_gate(r) for r in raw_results]
        for result in channel_results:
            if result.documents:
                self._mark_used_channel(used_channels, result.channel_name)

        vector_accepted = next(
            (r.documents for r in channel_results if r.channel_name == "vector"), []
        )
        keyword_accepted = next(
            (r.documents for r in channel_results if r.channel_name == "keyword"), []
        )

        # ── 查询自适应 Top-k 截断（调研 P2，默认关）─────────────
        _adaptive_k_settings = getattr(settings, "adaptive_k", None)
        if _adaptive_k_settings is not None and _adaptive_k_settings.enabled:
            from app.rag.adaptive_k import adaptive_truncate

            ak = _adaptive_k_settings
            vector_accepted = adaptive_truncate(
                vector_accepted, ak.min_k, ak.max_k, ak.ratio_threshold
            )
            keyword_accepted = adaptive_truncate(
                keyword_accepted, ak.min_k, ak.max_k, ak.ratio_threshold
            )
            logger.debug(
                "adaptive-k truncation",
                vector=len(vector_accepted),
                keyword=len(keyword_accepted),
            )

        # ── RRF 融合 ───────────────────────────────────────────
        rrf_started_at = datetime.now(UTC)
        t_rrf = time.monotonic()
        merged = rrf_fusion(vector_accepted, keyword_accepted)[: settings.rag.candidate_top_k]
        rrf_duration_ms = int((time.monotonic() - t_rrf) * 1000)
        if collected_spans_out is not None:
            collected_spans_out.append(
                SpanContext(
                    span_id=next_id_str(),
                    trace_id=trace_id,
                    parent_span_id=parent_span_id,
                    kind=SpanKind.PIPELINE,
                    name="rrf_fusion",
                    status=SpanStatus.OK,
                    started_at=rrf_started_at,
                    ended_at=rrf_started_at + timedelta(milliseconds=rrf_duration_ms),
                    duration_ms=rrf_duration_ms,
                    metadata={
                        "input_vector": len(vector_accepted),
                        "input_keyword": len(keyword_accepted),
                        "output": len(merged),
                    },
                )
            )

        # ── ParentBlock 提升 ────────────────────────────────────
        parent_started_at = datetime.now(UTC)
        t_parent = time.monotonic()
        parent_candidates = await ParentBlockElevator().elevate(merged, session=self.db)
        parent_duration_ms = int((time.monotonic() - t_parent) * 1000)
        if collected_spans_out is not None:
            collected_spans_out.append(
                SpanContext(
                    span_id=next_id_str(),
                    trace_id=trace_id,
                    parent_span_id=parent_span_id,
                    kind=SpanKind.PIPELINE,
                    name="parent_block",
                    status=SpanStatus.OK,
                    started_at=parent_started_at,
                    ended_at=parent_started_at + timedelta(milliseconds=parent_duration_ms),
                    duration_ms=parent_duration_ms,
                    metadata={"input": len(merged), "output": len(parent_candidates)},
                )
            )

        # ── Rerank ─────────────────────────────────────────────
        rerank_started_at = datetime.now(UTC)
        t_rerank = time.monotonic()
        reranked = await self._maybe_rerank(
            sub_q.text, parent_candidates, sub_question_index, notes, used_channels
        )
        rerank_duration_ms = int((time.monotonic() - t_rerank) * 1000)
        if collected_spans_out is not None:
            collected_spans_out.append(
                SpanContext(
                    span_id=next_id_str(),
                    trace_id=trace_id,
                    parent_span_id=parent_span_id,
                    kind=SpanKind.RETRIEVAL,
                    name="reranker",
                    status=SpanStatus.OK,
                    started_at=rerank_started_at,
                    ended_at=rerank_started_at + timedelta(milliseconds=rerank_duration_ms),
                    duration_ms=rerank_duration_ms,
                    metadata={"input": len(parent_candidates), "output": len(reranked)},
                )
            )

        final_docs = self._apply_rerank_filter_and_topk(reranked)

        self._mark_selection(final_docs, sub_question_index, channel_results, notes)
        self._record_empty_retrieval_metrics(
            final_docs,
            raw_results,
            vector_accepted,
            keyword_accepted,
            merged,
            sub_question_index,
            sub_q,
        )

        return SubQuestionEvidence(
            sub_question=sub_q,
            evidences=final_docs,
            channel_trace={
                "vector_recalled": len(
                    next((r.documents for r in raw_results if r.channel_name == "vector"), [])
                ),
                "keyword_recalled": len(
                    next((r.documents for r in raw_results if r.channel_name == "keyword"), [])
                ),
                "vector_accepted": len(vector_accepted),
                "keyword_accepted": len(keyword_accepted),
                "fused": len(merged),
                "parent": len(parent_candidates),
                "reranked": len(reranked),
            },
            fused_candidate_count=len(merged),
            parent_candidate_count=len(parent_candidates),
            reranked_candidate_count=len(reranked),
        )

    async def _parallel_channel_retrieve(
        self, sub_q: SubQuestion, sub_question_index: int, notes: list[str]
    ) -> list[RetrievalChannelResult]:
        from app.rag.channels.keyword import KeywordRetrievalChannel
        from app.rag.channels.vector import VectorRetrievalChannel

        vector_channel = VectorRetrievalChannel()
        keyword_channel = KeywordRetrievalChannel()
        channel_timeout = max(settings.rag.channel_timeout_ms / 1000.0, 0.001)

        async def _channel_retrieve(channel_fn, channel_name: str) -> RetrievalChannelResult:
            started_at = time.monotonic()
            docs: list[Evidence] = []
            error_message = ""
            try:
                docs = await asyncio.wait_for(channel_fn(sub_q), timeout=channel_timeout)
            except Exception as e:
                # 体检 C5：静默降级可见化
                from app.observability.metrics import DEGRADATION_TOTAL

                DEGRADATION_TOTAL.labels(reason="retrieval_channel_failed").inc()
                logger.warning(
                    "检索通道失败",
                    sub_question_index=sub_question_index,
                    sub_question=sub_q.text[:50],
                    channel=channel_name,
                    error=str(e),
                    exc_info=True,
                )
                notes.append(
                    f"子问题{sub_question_index}通道[{channel_name}]检索失败或超时，已自动降级。"
                )
                error_message = str(e)

            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            scores = [
                e.original_score or e.score or 0.0
                for e in docs
                if e.original_score is not None or e.score is not None
            ]
            avg_score = sum(scores) / len(scores) if scores else 0.0

            state = "error" if error_message else "success"
            RETRIEVAL_CHANNEL_TOTAL.labels(channel=channel_name, state=state).inc()
            RETRIEVAL_CHANNEL_DURATION.labels(channel=channel_name).observe(elapsed_ms / 1000.0)

            return RetrievalChannelResult(
                channel_name=channel_name,
                documents=docs,
                duration_ms=elapsed_ms,
                error_message=error_message,
                recalled_count=len(docs),
                accepted_count=len(docs),
                avg_score=round(avg_score, 4),
            )

        channel_tasks = [_channel_retrieve(vector_channel.retrieve, "vector")]
        if settings.rag.keyword_channel_enabled:
            channel_tasks.append(_channel_retrieve(keyword_channel.retrieve, "keyword"))

        return await asyncio.gather(*channel_tasks) if channel_tasks else []

    async def _maybe_rerank(
        self,
        query: str,
        candidates: list[Evidence],
        sub_question_index: int,
        notes: list[str],
        used_channels: set[str],
    ) -> list[Evidence]:
        if not settings.rerank.enabled or len(candidates) <= 1:
            return candidates
        try:
            from app.rag.reranker import Reranker

            reranked = await Reranker().rerank(query, candidates)
            self._mark_used_channel(used_channels, "rerank")
            return reranked
        except Exception as e:
            logger.warning(
                "rerank 失败，降级为跳过重排",
                sub_question_index=sub_question_index,
                error=str(e),
                exc_info=True,
            )
            notes.append(f"子问题{sub_question_index}重排失败，已降级跳过。")
            return candidates

    def _apply_rerank_filter_and_topk(self, docs: list[Evidence]) -> list[Evidence]:
        min_rerank = settings.rag.rerank_min_score or 0.0
        if min_rerank > 0 and any(e.rerank_score is not None for e in docs):
            filtered = [e for e in docs if (e.rerank_score or 1.0) >= min_rerank]
            # 兜底：阈值语义失效（该查询整体低分区间）时保留最高分 top-1，
            # 避免空证据导致拒答（实证："请假"类查询相关块仅 0.05-0.17）
            docs = filtered or sorted(
                docs, key=lambda e: e.rerank_score or 0.0, reverse=True
            )[:1]
        return docs[: settings.rag.final_top_k]

    def _mark_selection(
        self,
        final_docs: list[Evidence],
        sub_question_index: int,
        channel_results: list[RetrievalChannelResult],
        notes: list[str],
    ) -> None:
        for rank, e in enumerate(final_docs, start=1):
            e.is_selected = True
            e.final_rank = rank
            e.selection_reason = "已选入最终 Prompt"
        notes.append(
            f"子问题{sub_question_index}检索完成："
            + "，".join(f"{r.channel_name}={len(r.documents)}" for r in channel_results)
            + f"，final={len(final_docs)}"
        )

    def _record_empty_retrieval_metrics(
        self,
        final_docs: list[Evidence],
        raw_results: list[RetrievalChannelResult],
        vector_accepted: list[Evidence],
        keyword_accepted: list[Evidence],
        merged: list[Evidence],
        sub_question_index: int,
        sub_q: SubQuestion,
    ) -> None:
        if final_docs:
            return
        vector_empty = not any(r.documents for r in raw_results if r.channel_name == "vector")
        keyword_empty = all(not r.documents for r in raw_results if r.channel_name == "keyword")
        all_channels_empty = settings.rag.keyword_channel_enabled and (
            vector_empty and keyword_empty
        )
        channel_failed = any(r.error_message for r in raw_results)
        if all_channels_empty:
            RETRIEVAL_EMPTY_TOTAL.labels(reason="both_channels_empty").inc()
        elif channel_failed:
            RETRIEVAL_EMPTY_TOTAL.labels(reason="channel_error").inc()
        else:
            RETRIEVAL_EMPTY_TOTAL.labels(reason="all_gate_filtered").inc()
        logger.warning(
            "empty retrieval",
            sub_question_index=sub_question_index,
            sub_question=sub_q.text[:80],
            vector_count=len(vector_accepted),
            keyword_count=len(keyword_accepted),
            merged_count=len(merged),
            final_count=len(final_docs),
        )

    def _resolve_score(self, evidence: Evidence) -> float | None:
        """解析得分：优先 original_score，其次 score；null-safe。"""
        if evidence.original_score is not None:
            return evidence.original_score
        if evidence.score is not None:
            return evidence.score
        return None

    def _apply_evidence_gate(self, result: RetrievalChannelResult) -> RetrievalChannelResult:
        """证据闸门过滤：排除 null 得分的低质量文档。"""
        if not result.documents:
            return result

        doc_scores = [(e, self._resolve_score(e)) for e in result.documents]

        for e, score in doc_scores:
            if score is None or score < settings.rag.min_vector_similarity:
                e.gate_passed = False

        if result.channel_name == "vector":
            filtered = [
                e
                for e, score in doc_scores
                if score is not None and score >= settings.rag.min_vector_similarity
            ]
            return RetrievalChannelResult(channel_name=result.channel_name, documents=filtered)

        if result.channel_name == "keyword":
            valid_scores = [score for _, score in doc_scores if score is not None]
            top_score = max(valid_scores, default=None)
            if top_score is None or top_score <= 0:
                return result
            floor = top_score * max(0.0, settings.rag.keyword_score_ratio)
            filtered = [e for e, score in doc_scores if score is not None and score >= floor]
            return RetrievalChannelResult(channel_name=result.channel_name, documents=filtered)

        return result

    @staticmethod
    def _build_unique_key(ev: Evidence) -> str:
        """构建去重键（委托到 assembly.py 的 _unique_key 避免重复）"""
        from app.rag.assembly import PromptAssemblyService

        return PromptAssemblyService._unique_key(ev)

    @staticmethod
    def _mark_used_channel(used_channels: set[str], channel: str) -> None:
        """标记已使用通道（set 天然去重）"""
        used_channels.add(channel)

    def _assign_reference_ids(self, evidence_list: list[SubQuestionEvidence]) -> None:
        """跨子问题分配引用 ID，保证一个唯一 key 只对应一个 ID。"""
        ref_counter = 1
        assigned: dict[str, str] = {}
        for se in evidence_list:
            for ev in se.evidences:
                unique_key = self._build_unique_key(ev)
                if unique_key not in assigned:
                    assigned[unique_key] = str(ref_counter)
                    ref_counter += 1
                ev.reference_id = int(assigned[unique_key])
