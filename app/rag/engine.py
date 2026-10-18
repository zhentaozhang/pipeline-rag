"""
RAG 双通道检索引擎主入口

流程：
1. asyncio 并行执行 SubQuestion 检索（含超时 + exceptionally 降级）
2. 每个 SubQuestion 内 channels 并行执行
3. EvidenceGate 过滤低质量命中
4. RRF 融合（K 由 settings.rag.rrf_k 决定，默认 30）
5. ParentBlock 提升（Child 检索 → Parent 上下文）
6. Rerank 精排（可选）
7. Top-K 截取 → 分配 Reference ID → 留痕溯源 (Trace)
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

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

# P2-6 查询类型自适应融合：含精确标识符（数字/编号/条款/版本/许可证等）的查询偏关键词通道
_ID_LIKE_PATTERN = re.compile(
    r"\d|第\s*[0-9一二三四五六七八九十百]+\s*[条点项款]|版本|编号|许可证|"
    r"\bGPL\b|\bMIT\b|\bCVE\b|\bPMP\b"
)


def _query_type_multipliers(
    text: str, keyword_bias: float, vector_bias: float
) -> tuple[float, float]:
    """返回 (vector_mult, keyword_mult)：精确标识型查询 → 偏关键词；概念型 → 偏向量。"""
    return (1.0, keyword_bias) if _ID_LIKE_PATTERN.search(text or "") else (vector_bias, 1.0)


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

        if plan.sub_questions:
            sub_questions = plan.sub_questions
        elif plan.retrieval_sub_questions:
            sub_questions = [
                SubQuestion(
                    index=i,
                    text=q,
                    original=plan.original_question,
                    tenant_id=plan.tenant_id,
                    doc_ids=plan.retrieval_document_ids,
                )
                for i, q in enumerate(plan.retrieval_sub_questions)
            ]
        else:
            sub_q = plan.retrieval_question or plan.original_question
            sub_questions = [
                SubQuestion(
                    index=0,
                    text=sub_q,
                    original=plan.original_question,
                    tenant_id=plan.tenant_id,
                    doc_ids=plan.retrieval_document_ids,
                )
            ]

        # ── 子问题并行，每个有超时保护 ─────────────────────────────
        per_sub_timeout = max(settings.rag.sub_question_timeout_ms / 1000.0, 0.001)

        _collected_spans: list[SpanContext] = []

        async def _retrieve_with_timeout(
            sq: SubQuestion, idx: int
        ) -> tuple[SubQuestionEvidence, list[str]]:
            # 每个子问题用局部 notes，结束后按序号合并 —— 否则并行完成顺序会污染提示词顺序
            local_notes: list[str] = []
            try:
                evidence = await asyncio.wait_for(
                    self._retrieve_one(
                        sq,
                        idx + 1,
                        plan,
                        context.used_channels,
                        local_notes,
                        collected_spans_out=_collected_spans,
                        tracer=tracer,
                    ),
                    timeout=per_sub_timeout,
                )
                return evidence, local_notes
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
                local_notes.append(f"子问题{idx + 1}检索失败或超时，已自动忽略。")
                return SubQuestionEvidence(
                    sub_question=sq,
                    evidences=[],
                    channel_trace={},
                    fused_candidate_count=0,
                    parent_candidate_count=0,
                    reranked_candidate_count=0,
                ), local_notes

        max_concurrency = max(1, getattr(settings.rag, "sub_question_max_concurrency", 3))
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _throttled_retrieve_with_timeout(
            sq: SubQuestion, idx: int
        ) -> tuple[SubQuestionEvidence, list[str]]:
            async with semaphore:
                return await _retrieve_with_timeout(sq, idx)

        tasks = [_throttled_retrieve_with_timeout(sq, i) for i, sq in enumerate(sub_questions)]
        gathered = await asyncio.gather(*tasks)
        evidence_list = [item[0] for item in gathered]
        for _, sub_notes in gathered:
            context.retrieval_notes.extend(sub_notes)

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
        """Corrective Retrieval：证据不足时改写查询重查，最多 corrective_retrieval_max_rounds 轮。

        P3-8：当 ``iterative_multi_hop_enabled`` 开启时，改走迭代式多跳累积（默认关，行为不变）。
        """
        if getattr(settings.rag, "iterative_multi_hop_enabled", False):
            return await self.retrieve_iterative_multi_hop(plan, tracer=tracer)

        context = await self.retrieve(plan, tracer=tracer)
        max_rounds = settings.rag.corrective_retrieval_max_rounds
        if not settings.rag.corrective_retrieval_enabled or max_rounds <= 0:
            return context

        base_question = (plan.rewritten_question or plan.original_question).strip()
        corrected = False
        for _ in range(max_rounds):
            if await self._evidence_is_sufficient(base_question, context):
                break
            rewritten = await self._rewrite_query(base_question)
            if not rewritten or rewritten == base_question:
                break
            corrected = True
            base_question = rewritten
            # 这里覆盖而非追加子问题：本分支只在 context.is_empty（全部子问题零命中）时
            # 进入，被替换的子问题并未产出任何证据，重跑它们纯属浪费检索成本。
            # 但仍把"多子问题扇出被折叠为单查询"记入 note，让降级可见。
            collapsed_sub_questions = len(plan.sub_questions)
            plan.retrieval_question = rewritten
            plan.retrieval_sub_questions = [rewritten]
            from app.chat.schema import SubQuestion

            plan.sub_questions = [
                SubQuestion(
                    index=0,
                    text=rewritten,
                    original=plan.original_question,
                    tenant_id=plan.tenant_id,
                    doc_ids=plan.retrieval_document_ids,
                )
            ]
            previous_context = context
            context = await self.retrieve(plan, tracer=tracer)
            if not previous_context.is_empty and not context.is_empty:
                context = self._merge_corrective_context(previous_context, context)
            folded = (
                f"（原 {collapsed_sub_questions} 个子问题均无命中，已折叠为单查询）"
                if collapsed_sub_questions > 1
                else ""
            )
            context.retrieval_notes.append(
                f"检索证据不足，已按改写查询重查：{rewritten[:80]}{folded}"
            )

        if corrected:
            logger.info(
                "corrective_retrieval_done",
                retrieval_question=context.retrieval_question[:50],
                still_empty=context.is_empty,
                notes=context.retrieval_notes,
            )
        return context

    # ── P3-8 迭代式多跳检索（默认关）─────────────────────────────────────

    async def retrieve_iterative_multi_hop(
        self, plan: ExecutionPlan, tracer: Any = None
    ) -> RagRetrievalContext:
        """检索 → 用已获证据生成"下一跳查询" → 再检索，累积去重（最多 N 跳）。

        收敛由 `_next_hop_query` 决定：返回空/与上一跳相同即停止。任何异常都被
        `iterate_hops` 吞掉并就地收敛，绝不影响主链路。
        """
        context = await self.retrieve(plan, tracer=tracer)
        max_hops = max(1, int(getattr(settings.rag, "iterative_multi_hop_max_hops", 2) or 2))
        base_question = (plan.rewritten_question or plan.original_question or "").strip()
        if not base_question or max_hops <= 1:
            return context

        from app.rag.multi_hop import iterate_hops

        async def _retrieve_hop(query: str) -> RagRetrievalContext:
            hop_plan = plan.model_copy(deep=True)
            hop_plan.retrieval_question = query
            hop_plan.retrieval_sub_questions = [query]
            hop_plan.sub_questions = [
                SubQuestion(
                    index=0,
                    text=query,
                    original=plan.original_question,
                    tenant_id=plan.tenant_id,
                    doc_ids=plan.retrieval_document_ids,
                )
            ]
            return await self.retrieve(hop_plan, tracer=tracer)

        context, hops = await iterate_hops(
            base_question,
            context,
            max_hops=max_hops,
            next_query_fn=self._next_hop_query,
            retrieve_fn=_retrieve_hop,
            merge_fn=self._merge_contexts,
        )
        context = cast("RagRetrievalContext", context)
        if hops > 1:
            context.retrieval_notes.append(f"迭代多跳检索完成：共 {hops} 跳。")
            logger.info(
                "iterative_multi_hop_done",
                hops=hops,
                retrieval_question=base_question[:50],
                evidence_count=sum(len(se.evidences) for se in context.sub_question_evidence_list),
            )
        return context

    async def _next_hop_query(self, question: str, context: RagRetrievalContext) -> str:
        """基于已获证据生成"能补全答案"的下一跳检索查询；证据已足够时返回空串。"""
        evidence_texts = [
            (ev.content or "")[:400]
            for se in context.sub_question_evidence_list
            for ev in se.evidences
            if ev.content
        ]
        if not evidence_texts:
            return ""
        prompt = (
            f"问题：{question}\n\n"
            "已检索到的证据片段：\n"
            + "\n---\n".join(evidence_texts[:6])
            + "\n\n请判断上述证据是否已足以完整回答问题。"
            "若已足够，只输出空行；若仍缺少关键信息，输出一句**新的检索查询**"
            "（只输出查询本身，不要解释、不要复述原文）。"
        )
        try:
            from app.common.llm_client import get_chat_client, llm_breaker

            client = get_chat_client()
            async with llm_breaker():
                resp = await client.chat.completions.create(
                    model=settings.llm.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=64,
                )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:  # noqa: BLE001 — 生成失败即收敛
            logger.warning("next_hop_query_failed", error=str(e)[:120])
            return ""

    def _merge_contexts(
        self, base: RagRetrievalContext, extra: RagRetrievalContext
    ) -> RagRetrievalContext:
        """把新一跳的证据**去重累积**进 base（不改写已有引用编号，最后统一重排）。"""
        seen = {
            self._build_unique_key(ev)
            for se in base.sub_question_evidence_list
            for ev in se.evidences
        }
        for se in extra.sub_question_evidence_list:
            fresh = [ev for ev in se.evidences if self._build_unique_key(ev) not in seen]
            for ev in fresh:
                seen.add(self._build_unique_key(ev))
            if fresh:
                base.sub_question_evidence_list.append(
                    SubQuestionEvidence(
                        sub_question=se.sub_question,
                        evidences=fresh,
                        channel_trace=se.channel_trace,
                    )
                )
        base.used_channels.update(extra.used_channels)
        base.retrieval_notes.extend(extra.retrieval_notes)
        self._assign_reference_ids(base.sub_question_evidence_list)
        return base

    async def _evidence_is_sufficient(self, question: str, context: RagRetrievalContext) -> bool:
        """判定检索证据是否足以回答问题（JEV Noul 语义充分性）。

        规则：空证据一定不足。JEV 关闭/异常时退化为"非空即充分"（保持原行为，绝不误触发纠错）。
        """
        if context.is_empty:
            return False

        evidence_texts = [
            ev.content[:400]
            for se in context.sub_question_evidence_list
            for ev in se.evidences
            if ev.content
        ]
        if not evidence_texts:
            return False

        from app.infra.jev_client import jev_decide

        def _parse(answers: dict) -> bool:
            res = answers.get("sufficient")
            if not isinstance(res, dict) or "noul" not in res:
                raise ValueError("JEV response missing sufficient evaluation")
            return float(res["noul"]) >= 0.5

        result = await jev_decide(
            "evidence_sufficiency_enabled",
            state=f"问题：{question}\n\n检索到的证据片段：\n" + "\n---\n".join(evidence_texts[:6]),
            questions={
                "sufficient": {
                    "type": "noul",
                    "instructions": "上述检索到的证据是否足以直接、完整地回答问题（无需再检索）？",
                }
            },
            parse=_parse,
            log_context="JEV 证据充分性判定",
        )
        if result is None:
            # JEV 关闭/异常 → 未知。保守口径：行为仍按"充分"处理（绝不误触发纠错），
            # 但必须留痕——否则"纠错检索从未执行"在报告里完全不可见。
            from app.observability.metrics import DEGRADATION_TOTAL

            DEGRADATION_TOTAL.labels(reason="evidence_sufficiency_unknown").inc()
            context.retrieval_notes.append(
                "证据充分性无法判定（JEV 未启用或不可用），本轮按充分处理、跳过纠错检索。"
            )
            logger.info("evidence_sufficiency_unknown", question=question[:50])
            return True
        return result

    @staticmethod
    def _merge_evidence_lists(
        previous: RagRetrievalContext, fresh: RagRetrievalContext
    ) -> list[Evidence]:
        """按 chunk_id 与新一轮证据求并集，分数取 max（顺序稳定）。"""
        merged: dict[str, Evidence] = {}
        for source in (previous, fresh):
            for se in source.sub_question_evidence_list:
                for ev in se.evidences:
                    key = ev.chunk_id or (ev.content or "")[:64]
                    existing = merged.get(key)
                    if existing is None:
                        merged[key] = ev
                        continue
                    existing.score = max(existing.score or 0.0, ev.score or 0.0)
                    existing.rerank_score = max(
                        getattr(existing, "rerank_score", 0.0) or 0.0,
                        getattr(ev, "rerank_score", 0.0) or 0.0,
                    )
        return sorted(
            merged.values(),
            key=lambda e: ((getattr(e, "rerank_score", 0.0) or 0.0), (e.score or 0.0)),
            reverse=True,
        )

    def _merge_corrective_context(
        self, previous: RagRetrievalContext, fresh: RagRetrievalContext
    ) -> RagRetrievalContext:
        """把纠错重查的新证据并回上一轮上下文，避免"重查即丢弃已召回片段"。"""
        merged = self._merge_evidence_lists(previous, fresh)
        if not merged:
            return fresh
        first = fresh.sub_question_evidence_list[0] if fresh.sub_question_evidence_list else None
        if first is None:
            return fresh
        fresh.sub_question_evidence_list = [
            SubQuestionEvidence(
                sub_question=first.sub_question,
                evidences=merged,
                channel_trace=first.channel_trace,
                fused_candidate_count=first.fused_candidate_count,
                parent_candidate_count=first.parent_candidate_count,
                reranked_candidate_count=first.reranked_candidate_count,
            )
        ]
        self._assign_reference_ids(fresh.sub_question_evidence_list)
        fresh.retrieval_notes.append(f"纠错重查结果已与上一轮证据合并：去重后 {len(merged)} 条。")
        return fresh

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
        vec_weight = getattr(settings.rag, "rrf_vector_weight", 1.0)
        kw_weight = getattr(settings.rag, "rrf_keyword_weight", 1.0)
        if getattr(settings.rag, "query_adaptive_weight_enabled", False):
            v_mult, k_mult = _query_type_multipliers(
                sub_q.text,
                getattr(settings.rag, "adaptive_keyword_bias", 1.6),
                getattr(settings.rag, "adaptive_vector_bias", 1.6),
            )
            vec_weight *= v_mult
            kw_weight *= k_mult
        merged = rrf_fusion(
            vector_accepted,
            keyword_accepted,
            k=getattr(settings.rag, "rrf_k", 60),
            vector_weight=vec_weight,
            keyword_weight=kw_weight,
        )[: settings.rag.candidate_top_k]
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

        # ── Rerank (在子块粒度上重排，避免 Parent 大块物理截断与注意力稀释) ────
        rerank_started_at = datetime.now(UTC)
        t_rerank = time.monotonic()
        reranked = await self._maybe_rerank(
            sub_q.text, merged, sub_question_index, notes, used_channels
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
                    metadata={"input": len(merged), "output": len(reranked)},
                )
            )

        reranked_filtered = self._apply_rerank_filter(reranked)

        # ── ParentBlock 提升 (将经过精排重选的子块聚合提升为父块) ──────────────
        parent_started_at = datetime.now(UTC)
        t_parent = time.monotonic()
        parent_candidates = await ParentBlockElevator().elevate(reranked_filtered, session=self.db)
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
                    metadata={"input": len(reranked_filtered), "output": len(parent_candidates)},
                )
            )

        final_docs = parent_candidates[: settings.rag.final_top_k]

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

        stage_candidates = {
            "vector": [d.content for d in vector_accepted if d.content],
            "keyword": [d.content for d in keyword_accepted if d.content],
            "fused": [d.content for d in merged if d.content],
            "reranked": [d.content for d in reranked_filtered if d.content],
            "parent": [d.content for d in parent_candidates if d.content],
            "final": [d.content for d in final_docs if d.content],
        }

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
                "reranked": len(reranked),
                "parent": len(parent_candidates),
                "stage_candidates": stage_candidates,
            },
            fused_candidate_count=len(merged),
            reranked_candidate_count=len(reranked),
            parent_candidate_count=len(parent_candidates),
        )

    async def _parallel_channel_retrieve(
        self, sub_q: SubQuestion, sub_question_index: int, notes: list[str]
    ) -> list[RetrievalChannelResult]:
        from app.rag.channels.keyword import KeywordRetrievalChannel
        from app.rag.channels.vector import VectorRetrievalChannel

        vector_channel = VectorRetrievalChannel()
        keyword_channel = KeywordRetrievalChannel()
        channel_timeout = max(settings.rag.channel_timeout_ms / 1000.0, 0.001)

        async def _channel_retrieve(channel, channel_name: str) -> RetrievalChannelResult:
            started_at = time.monotonic()
            docs: list[Evidence] = []
            error_message = ""
            try:
                docs = await asyncio.wait_for(channel.retrieve(sub_q), timeout=channel_timeout)
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

            if not error_message:
                # 通道内部吞掉的异常（如 embedding/PG/ES 故障）也要归因成"通道故障"，
                # 否则会被上层读成"知识库为空"（both_channels_empty）。
                swallowed = str(getattr(channel, "last_error", "") or "").strip()
                if swallowed:
                    from app.observability.metrics import DEGRADATION_TOTAL

                    DEGRADATION_TOTAL.labels(reason="retrieval_channel_failed").inc()
                    logger.warning("检索通道内部异常", channel=channel_name, error=swallowed)
                    notes.append(
                        f"子问题{sub_question_index}通道[{channel_name}]异常已降级：{swallowed[:80]}"
                    )
                    error_message = swallowed

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

        channel_tasks = []
        if getattr(settings.rag, "vector_channel_enabled", True):
            channel_tasks.append(_channel_retrieve(vector_channel, "vector"))
        if settings.rag.keyword_channel_enabled:
            channel_tasks.append(_channel_retrieve(keyword_channel, "keyword"))

        return await asyncio.gather(*channel_tasks) if channel_tasks else []

    @staticmethod
    def _apply_rank1_guard(
        first_stage: list[Evidence],
        reranked: list[Evidence],
        margin: float,
    ) -> list[Evidence]:
        """R2 rank-1 保护：若第一阶段首候选被重排降级、但分差在 margin 内，则恢复其榜首位置。

        依据：重排器常把高置信 rank-1 命中降级（MRR 下降），在榜首价值高于深列表覆盖时是负收益。
        仅在 rerank_rank1_guard_enabled 开启时调用，默认不改变行为。
        """
        if not first_stage or not reranked:
            return reranked
        first_id = getattr(first_stage[0], "chunk_id", None)
        if not first_id:
            return reranked
        idx = next((i for i, e in enumerate(reranked) if e.chunk_id == first_id), -1)
        if idx <= 0:
            return reranked
        top_rr = reranked[0].rerank_score or 0.0
        first_rr = reranked[idx].rerank_score or 0.0
        if first_rr >= top_rr - margin:
            reranked.insert(0, reranked.pop(idx))
        return reranked

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

        # R1 条件重排：首候选已是高置信（如强向量命中）时跳过重排，避免降级 rank-1。
        skip_min = getattr(settings.rag, "rerank_skip_min_similarity", 0.0) or 0.0
        if skip_min > 0:
            top = max(candidates, key=lambda e: self._resolve_score(e) or -1.0)
            top_score = self._resolve_score(top)
            if top_score is not None and top_score >= skip_min:
                notes.append(
                    f"子问题{sub_question_index}首候选置信度{top_score:.3f}≥{skip_min}，已跳过重排。"
                )
                logger.info(
                    "rerank_skipped_high_confidence",
                    sub_question_index=sub_question_index,
                    top_score=top_score,
                    threshold=skip_min,
                )
                return candidates

        try:
            from app.rag.reranker import Reranker

            reranked = await Reranker().rerank(query, candidates)
            self._mark_used_channel(used_channels, "rerank")
            if getattr(settings.rag, "rerank_rank1_guard_enabled", False):
                before_id = reranked[0].chunk_id if reranked else None
                reranked = self._apply_rank1_guard(
                    candidates,
                    reranked,
                    getattr(settings.rag, "rerank_rank1_guard_margin", 0.15) or 0.0,
                )
                if reranked and reranked[0].chunk_id != before_id:
                    notes.append(f"子问题{sub_question_index}已触发 rank-1 保护。")
                    logger.info("rerank_rank1_guarded", sub_question_index=sub_question_index)
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

    def _apply_rerank_filter(self, docs: list[Evidence]) -> list[Evidence]:
        scored = [e for e in docs if e.rerank_score is not None]
        if not scored:
            return docs
        abs_min = getattr(settings.rag, "rerank_min_score", 0.0) or 0.0
        ratio = getattr(settings.rag, "rerank_relative_ratio", 0.0) or 0.0
        top_score = max((e.rerank_score or 0.0) for e in scored)
        # 相对阈值：当 ratio > 0 时按相对最高分动态放行（加 0.02 底线滤纯负噪点），
        # 彻底避免整体低分区间（如 0.15~0.25）被 0.35 绝对下限一刀切；未配 ratio 时使用绝对下限。
        threshold = max(0.02, top_score * ratio) if ratio > 0 else abs_min

        if threshold > 0:
            filtered = [e for e in scored if (e.rerank_score or 1.0) >= threshold]
            # D3 不变量：阈值不得把证据集砍到目标深度以下，否则上下文被饥饿、召回坍塌。
            # 触发时跳过阈值（保留全部已重排候选），截断交给 final_top_k。
            target_depth = min(int(getattr(settings.rag, "final_top_k", 8) or 8), len(scored))
            if (
                getattr(settings.rag, "rerank_filter_starvation_guard_enabled", True)
                and len(filtered) < target_depth
            ):
                logger.warning(
                    "rerank_filter_starved",
                    threshold=round(threshold, 4),
                    kept=len(filtered),
                    target_depth=target_depth,
                    candidates=len(scored),
                )
                docs = scored
            else:
                # 兜底：阈值语义失效时至少保留最高分 top-1，避免空证据拒答
                docs = (
                    filtered
                    if filtered
                    else sorted(scored, key=lambda e: e.rerank_score or 0.0, reverse=True)[:1]
                )
        else:
            docs = scored
        return docs

    def _apply_rerank_filter_and_topk(self, docs: list[Evidence]) -> list[Evidence]:
        return self._apply_rerank_filter(docs)[: settings.rag.final_top_k]

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
        """证据闸门过滤：各通道独立门限判定，杜绝向量阈值污染关键词通道。"""
        if not result.documents:
            return result

        doc_scores = [(e, self._resolve_score(e)) for e in result.documents]

        if result.channel_name == "vector":
            # 默认绝对阈值；vector_relative_ratio>0 时改用相对阈值 top_score*ratio（对齐关键词通道语义）
            rel = getattr(settings.rag, "vector_relative_ratio", 0.0) or 0.0
            top_raw = max((s for _, s in doc_scores if s is not None), default=None)
            threshold = (
                top_raw * rel
                if (rel > 0 and top_raw is not None)
                else settings.rag.min_vector_similarity
            )
            filtered: list[Evidence] = []
            for e, score in doc_scores:
                if score is not None and score >= threshold:
                    e.gate_passed = True
                    filtered.append(e)
                else:
                    e.gate_passed = False
            # 软近邻兜底：全部低于阈值时，若 top-1 落在 near_miss 比例内，予以保底保留
            near_miss = getattr(settings.rag, "vector_near_miss_ratio", 0.85)
            if not filtered and doc_scores:
                top_e, top_s = max(doc_scores, key=lambda x: x[1] if x[1] is not None else -1.0)
                if top_s is not None and top_s >= threshold * near_miss:
                    top_e.gate_passed = True
                    filtered.append(top_e)
                    logger.info(
                        "vector_gate_near_miss_fallback",
                        top_score=top_s,
                        min_threshold=threshold,
                    )
            return RetrievalChannelResult(channel_name=result.channel_name, documents=filtered)

        if result.channel_name == "keyword":
            valid_scores = [score for _, score in doc_scores if score is not None]
            top_score = max(valid_scores, default=None)
            if top_score is None or top_score <= 0:
                return result
            floor = top_score * max(0.0, settings.rag.keyword_score_ratio)
            filtered = []
            for e, score in doc_scores:
                if score is not None and score >= floor:
                    e.gate_passed = True
                    filtered.append(e)
                else:
                    e.gate_passed = False
            return RetrievalChannelResult(channel_name=result.channel_name, documents=filtered)

        for e, score in doc_scores:
            if score is None:
                e.gate_passed = False

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
