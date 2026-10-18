from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import structlog

from app.chat.memory import MemoryContext
from app.chat.schema import ExecutionPlan, SubQuestion
from app.common.enums import ExecutionMode
from app.common.llm_client import get_chat_client
from app.config import get_settings
from app.infra.model_fallback import ModelFallbackManager
from app.orchestrator.query_rewriter import ChatQueryRewriteService
from app.orchestrator.recommendation import RecommendationService
from app.rag.assembly import PromptAssemblyService
from app.rag.engine import RagRetrievalEngine
from app.rag.evaluation import RAGEvaluationService
from scripts.evaluation.datasets import load_dataset
from scripts.evaluation.datasets.base import EvalQuestion, EvalResult

logger = structlog.get_logger(__name__)
settings = get_settings()


def _apply_channel_selection(channels: str, settings_obj) -> None:
    """评测专用：把两路通道隔离，用于测量单通道指标（不改生产默认值）。"""
    if channels == "vector":
        settings_obj.rag.keyword_channel_enabled = False
    elif channels == "keyword":
        settings_obj.rag.vector_channel_enabled = False


def _filter_subset(questions: list, subset: str) -> list:
    """按题号前缀切子集：emp = 85 道自然语言题，lex = 编号类题。"""
    if subset == "all":
        return list(questions)
    return [q for q in questions if str(getattr(q, "id", "")).startswith(subset)]


def _build_plan(
    q: EvalQuestion,
    rewritten: str | None = None,
    keywords: list[str] | None = None,
    sub_questions: list[str] | None = None,
) -> ExecutionPlan:
    """从测试问题构造最小 ExecutionPlan。

    消费改写阶段产出的 ``sub_questions``（与生产 PlanBuilder 对齐），
    使离线评测真实反映多子查询检索路径；无有效子问题时回退为单查询。
    """
    rw = rewritten or q.question
    texts = [s.strip() for s in (sub_questions or []) if s and s.strip()] or [rw]
    return ExecutionPlan(
        mode=ExecutionMode.RETRIEVAL,
        original_question=q.question,
        rewritten_question=rw,
        sub_questions=[
            SubQuestion(
                index=i,
                text=t,
                original=q.question,
                query_context_hints=keywords or [],
            )
            for i, t in enumerate(texts)
        ],
    )


def _ordered_evidences(ctx) -> list:
    """按最终展示顺序取出证据（去重），文本与 ID 序列共用同一份顺序。

    去重键：优先 chunk_id，缺失时退化为内容前 64 字符（与旧实现一致）。
    """
    seen_chunk_ids: set[str] = set()
    all_evidences = []
    for sqe in ctx.sub_question_evidence_list:
        for ev in sqe.evidences:
            if not ev.content:
                continue
            cid = getattr(ev, "chunk_id", None) or ev.content[:64]
            if cid not in seen_chunk_ids:
                seen_chunk_ids.add(cid)
                all_evidences.append(ev)

    all_evidences.sort(
        key=lambda x: (
            float(x.rerank_score)
            if getattr(x, "rerank_score", 0.0) > 0
            else float(getattr(x, "score", 0.0) or 0.0)
        ),
        reverse=True,
    )
    return all_evidences


def _extract_context_texts(ctx) -> list[str]:
    """从 RagRetrievalContext 提取检索到的证据文本，去重并按重排/综合得分降序排列"""
    texts: list[str] = []
    for ev in _ordered_evidences(ctx):
        ref_prefix = (
            f"[{ev.reference_id}] " if getattr(ev, "reference_id", None) is not None else ""
        )
        texts.append(f"{ref_prefix}{ev.content}")
    return texts


def _extract_context_ids(ctx) -> list[str]:
    """与 ``_extract_context_texts`` 同序的 chunk_id 序列（Task 1 的召回判定依据）。"""
    ids: list[str] = []
    for ev in _ordered_evidences(ctx):
        cid = getattr(ev, "chunk_id", None)
        if cid is None:
            continue
        key = str(cid).strip()
        if key:
            ids.append(key)
    return ids


def _extract_context_parent_ids(ctx) -> list[str]:
    """与 ``_extract_context_texts`` 同序的 parent_block_id 序列（章节级召回判定）。"""
    ids: list[str] = []
    for ev in _ordered_evidences(ctx):
        pid = getattr(ev, "parent_block_id", None)
        if pid is None:
            continue
        key = str(pid).strip()
        if key:
            ids.append(key)
    return ids


async def _load_indexed_chunks() -> list[dict[str, Any]]:
    """加载已入库 chunk（id / 父块 / 文本），供 gold 片段对齐使用。"""
    from sqlalchemy import select

    from app.db.models.document import DocumentChunk
    from app.db.session import get_session_factory

    factory = get_session_factory()
    if factory is None:
        return []
    async with factory() as session:
        rows = await session.execute(
            select(
                DocumentChunk.id,
                DocumentChunk.parent_block_id,
                DocumentChunk.chunk_text,
                DocumentChunk.document_id,
            )
        )
        return [
            {
                "chunk_id": row[0],
                "parent_block_id": row[1],
                "chunk_text": row[2],
                "document_id": row[3],
            }
            for row in rows.all()
            if row[2]
        ]


def _apply_id_metrics(
    result,
    question,
    grounded: dict[str, list[str]],
    eval_depth: int,
) -> None:
    """按 chunk_id 判定召回（Task 1）。

    gold 优先取题目显式标注的 ``relevant_chunk_ids``，否则使用片段对齐结果。
    该题无 gold（拒答题）时指标保持 None，不计入均值。
    """
    from scripts.evaluation.metrics import (
        compute_any_of_mrr,
        compute_any_of_recall_at_k,
        compute_id_mrr,
        compute_id_ndcg_at_k,
        compute_id_recall_at_k,
    )

    if not getattr(question, "answerable", True):
        return
    gold_chunks = list(getattr(question, "relevant_chunk_ids", None) or []) or list(
        grounded.get("relevant_chunk_ids") or []
    )
    gold_parents = list(getattr(question, "relevant_parent_ids", None) or []) or list(
        grounded.get("relevant_parent_ids") or []
    )
    retrieved = list(result.retrieved_chunk_ids or [])
    retrieved_parents = list(result.retrieved_parent_ids or [])

    if getattr(question, "gold_mode", "all") == "any_of":
        result.recall_at_5_ids = compute_any_of_recall_at_k(retrieved, gold_chunks, 5)
        result.recall_at_final_k_ids = compute_any_of_recall_at_k(
            retrieved, gold_chunks, eval_depth
        )
        result.mrr_ids = compute_any_of_mrr(retrieved, gold_chunks)
        result.ndcg_at_5_ids = compute_id_ndcg_at_k(retrieved, gold_chunks, 5)
    else:
        result.recall_at_5_ids = compute_id_recall_at_k(retrieved, gold_chunks, 5)
        result.recall_at_final_k_ids = compute_id_recall_at_k(retrieved, gold_chunks, eval_depth)
        result.mrr_ids = compute_id_mrr(retrieved, gold_chunks)
        result.ndcg_at_5_ids = compute_id_ndcg_at_k(retrieved, gold_chunks, 5)
    result.recall_at_5_parent_ids = compute_id_recall_at_k(retrieved_parents, gold_parents, 5)
    result.recall_at_final_k_parent_ids = compute_id_recall_at_k(
        retrieved_parents, gold_parents, eval_depth
    )


def _apply_legacy_metrics(result, question, eval_depth: int) -> None:
    """旧口径召回（gold 片段 vs 提升后父块全文 bigram 重合）。

    只对"可答题"计算：不可答/拒答题没有 gold 片段，旧实现让它们恒记 0 分并拉低均值，
    把"本就不该召回"与"检索没召回"混为一谈。现在改为 None（不进均值），
    由拒答指标（`refusal_rates`）单独衡量。
    """
    from scripts.evaluation.metrics import (
        compute_mrr,
        compute_ndcg_at_k,
        compute_recall_at_k,
    )

    if not getattr(question, "answerable", True):
        return
    rel = list(getattr(question, "relevant_contexts", None) or [])
    if not rel:
        return
    result.recall_at_5 = compute_recall_at_k(result.retrieved_contexts, rel, 5)
    result.recall_at_final_k = compute_recall_at_k(result.retrieved_contexts, rel, eval_depth)
    result.mrr = compute_mrr(result.retrieved_contexts, rel)
    result.ndcg_at_5 = compute_ndcg_at_k(result.retrieved_contexts, rel, 5)
    result.ndcg_at_final_k = compute_ndcg_at_k(result.retrieved_contexts, rel, eval_depth)


def _load_generated_questions(path: str) -> list:
    """读取自动生成的题目（Task 4），转成 EvalQuestion。失败返回空列表。"""
    import json

    from scripts.evaluation.datasets.base import EvalQuestion

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("generated questions load failed", path=path, error=str(e))
        return []
    items = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        logger.warning("generated questions file has no questions list", path=path)
        return []
    out = []
    for item in items:
        try:
            out.append(
                EvalQuestion(
                    id=str(item["id"]),
                    question=str(item["question"]),
                    ground_truth_answer=str(item.get("ground_truth_answer") or ""),
                    relevant_contexts=list(item.get("relevant_contexts") or []),
                    relevant_chunk_ids=[str(x) for x in item.get("relevant_chunk_ids") or []],
                    category=str(item.get("category") or "generated"),
                )
            )
        except Exception as e:  # noqa: BLE001 — 单题字段缺失不影响其余
            logger.warning("generated question skipped", error=str(e)[:120])
    logger.info("generated questions loaded", path=path, count=len(out))
    return out


def _load_gold_file(path: str) -> dict[str, dict[str, list[str]]]:
    """读取预生成的 gold 文件（失败返回空映射，调用方降级为词法对齐）。"""
    import json

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(
            "gold file load failed, falling back to lexical grounding", path=path, error=str(e)
        )
        return {}
    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, dict):
        logger.warning("gold file has no questions map", path=path)
        return {}
    logger.info("gold file loaded", path=path, questions=len(questions), meta=payload.get("meta"))
    return questions


async def _ground_dataset_gold(
    dataset: list, *, gold_file: str = ""
) -> dict[str, dict[str, list[str]]]:
    """把评测集的 gold 文本片段对齐成 chunk_id（失败时降级为空映射，不影响主流程）。"""
    if not dataset:
        return {}
    if gold_file:
        return _load_gold_file(gold_file)
    try:
        chunks = await _load_indexed_chunks()
    except Exception as e:
        logger.warning("gold grounding skipped: cannot load chunks", error=str(e))
        return {}
    if not chunks:
        return {}
    from scripts.evaluation.gold_grounding import ground_gold_chunks

    return ground_gold_chunks(dataset, chunks)


def _compute_stage_attribution(
    relevant_contexts: list[str],
    ctx: Any,
) -> dict[str, Any]:
    """Retrieval Lab 分阶段召回归因分析

    追踪每个应检出证据片段在流水线各阶段的生命周期：
    - hit: 成功进入最终 Prompt 证据集 (final)
    - cutoff_dropped: 经重排后留存，但在 final_top_k 截断时丢失
    - rerank_demoted: 融合后候选池中有，但被 Reranker 降级或过滤
    - fusion_dropped: 检索通道已召回，但在 RRF 融合或 candidate_top_k 阶段丢失
    - unrecalled: 初始检索通道（向量与关键词）均未召回
    """
    if not relevant_contexts:
        return {}

    merged_stages: dict[str, list[str]] = {
        "vector": [],
        "keyword": [],
        "fused": [],
        "reranked": [],
        "final": [],
    }
    for sqe in getattr(ctx, "sub_question_evidence_list", []):
        trace = getattr(sqe, "channel_trace", {}) or {}
        stg = trace.get("stage_candidates", {})
        for k in merged_stages:
            merged_stages[k].extend(stg.get(k, []))

    from scripts.evaluation.metrics import _char_bigrams

    cover_ratio = getattr(settings.rag, "stage_attribution_cover_ratio", 0.35)

    def _is_covered(target: str, candidates: list[str]) -> bool:
        tgt = str(target).strip()
        if not tgt or not candidates:
            return False
        # 短片段（<12 字符）要求更高匹配比率或直接子串包含，避免泛化虚词撞车
        ratio = 0.65 if len(tgt) < 12 else cover_ratio
        if any(tgt.lower() in c.lower() for c in candidates):
            return True
        tgt_bigrams = _char_bigrams(tgt)
        if not tgt_bigrams:
            return False
        tgt_len = len(tgt_bigrams)
        for cand in candidates:
            cand_bigrams = _char_bigrams(cand)
            if cand_bigrams and (len(tgt_bigrams & cand_bigrams) / tgt_len >= ratio):
                return True
        return False

    breakdown = []
    stats = {
        "total": len(relevant_contexts),
        "hit": 0,
        "cutoff_dropped": 0,
        "rerank_demoted": 0,
        "fusion_dropped": 0,
        "unrecalled": 0,
    }

    for rc in relevant_contexts:
        in_final = _is_covered(rc, merged_stages["final"])
        in_rerank = _is_covered(rc, merged_stages["reranked"])
        in_fused = _is_covered(rc, merged_stages["fused"])
        in_vector = _is_covered(rc, merged_stages["vector"])
        in_keyword = _is_covered(rc, merged_stages["keyword"])
        in_channels = in_vector or in_keyword

        if in_final:
            stage = "hit"
        elif in_rerank:
            stage = "cutoff_dropped"
        elif in_fused:
            stage = "rerank_demoted"
        elif in_channels:
            stage = "fusion_dropped"
        else:
            stage = "unrecalled"

        stats[stage] += 1
        breakdown.append({"snippet": rc[:60], "stage": stage})

    return {
        "stats": stats,
        "breakdown": breakdown,
    }


async def evaluate_single(
    q: EvalQuestion,
    engine: RagRetrievalEngine,
    eval_service: RAGEvaluationService | None = None,
    model_fallback: ModelFallbackManager | None = None,
    rewriter: ChatQueryRewriteService | None = None,
    recommender: RecommendationService | None = None,
    retrieval_only: bool = False,
    judge_enabled: bool = True,
    with_executor: bool = False,
) -> EvalResult:
    """对一条测试数据执行完整的 检索→生成→评估 流水线

    with_executor=True 时复刻生产执行器的生成后处理（引用校验 + 质量审核），
    这是 JEV 唯一能接管的位置，缺了它 V3 与 V2 在评测里必然等价。
    """
    result = EvalResult(
        question_id=q.id,
        question=q.question,
        ground_truth_answer=q.ground_truth_answer,
        answerable=q.answerable,
        expected_refusal=q.expected_refusal,
        unanswerable_reason=str(q.metadata.get("unanswerable_reason") or ""),
    )

    # ── 0. 查询改写 ────────────────────────────────────────────────────
    plan = _build_plan(q)
    if rewriter and settings.rag.rewrite_enabled:
        try:
            rewrite_result = await rewriter.rewrite(q.question, history_summary="", force=True)
            sub_qs = list(rewrite_result.sub_questions or [])
            if rewrite_result.rewritten and rewrite_result.rewritten != q.question:
                plan = _build_plan(
                    q,
                    rewritten=rewrite_result.rewritten,
                    keywords=rewrite_result.keywords,
                    sub_questions=sub_qs,
                )
                result.rewritten_question = rewrite_result.rewritten
                logger.info(
                    "查询改写生效",
                    original=q.question[:50],
                    rewritten=rewrite_result.rewritten[:50],
                    keywords=rewrite_result.keywords,
                    sub_question_count=len(sub_qs),
                )
            elif rewrite_result.keywords:
                plan = _build_plan(q, keywords=rewrite_result.keywords, sub_questions=sub_qs)
                logger.info("查询关键词生效", keywords=rewrite_result.keywords)
        except Exception as e:
            logger.warning(
                "查询改写失败，使用原问题", question_id=q.id, error=str(e), exc_info=True
            )

    total_start = time.perf_counter()

    # ── 1. 检索 ────────────────────────────────────────────────────────
    try:
        retrieval_start = time.perf_counter()
        ctx = await engine.retrieve_with_correction(plan)
        result.retrieval_ms = (time.perf_counter() - retrieval_start) * 1000
        result.retrieved_contexts = _extract_context_texts(ctx)
        result.retrieved_chunk_ids = _extract_context_ids(ctx)
        result.retrieved_parent_ids = _extract_context_parent_ids(ctx)
        result.stage_attribution = _compute_stage_attribution(q.relevant_contexts, ctx)
    except Exception as e:
        result.status = "failed"
        result.error = f"retrieve error: {e}"
        logger.warning("evaluation retrieve failed", question_id=q.id, error=str(e), exc_info=True)
        return result

    # 仅检索模式（P1 网格搜索快速通道）：跳过生成与 LLM 评测，仅保留召回/归因指标
    if retrieval_only:
        result.status = "completed"
        result.total_ms = (time.perf_counter() - total_start) * 1000
        return result

    # ── 2. 生成回答 ────────────────────────────────────────────────────
    try:
        generation_start = time.perf_counter()
        assembler = PromptAssemblyService()
        prompt_result = assembler.assemble(plan, ctx.sub_question_evidence_list)

        resp = await model_fallback.chat_completion(
            model=None,
            messages=[
                {"role": "system", "content": prompt_result.system_prompt},
                {"role": "user", "content": prompt_result.user_prompt},
            ],
            temperature=_generation_temperature(),
            max_tokens=settings.llm.max_tokens,
        )
        import typing

        resp_data: Any = typing.cast(Any, resp)
        result.generated_answer = (
            (resp_data.choices[0].message.content or "") if resp_data.choices else ""
        )
        result.generation_ms = (time.perf_counter() - generation_start) * 1000
    except Exception as e:
        result.status = "failed"
        result.error = f"generation error: {e}"
        logger.warning(
            "evaluation generation failed", question_id=q.id, error=str(e), exc_info=True
        )
        return result

    # ── 2b. 推荐追问（可选，不阻塞主流程）─────────────────────────────────
    if recommender and settings.recommendation.enabled:
        try:
            recs = await recommender.generate_recommendations(
                question=q.question,
                answer=result.generated_answer,
                memory_ctx=MemoryContext(),
            )
            if recs:
                result.generated_recommendations = recs
                logger.info("推荐追问生成", question_id=q.id, count=len(recs))
        except Exception as e:
            logger.warning("推荐追问生成失败，跳过", question_id=q.id, error=str(e), exc_info=True)

    # ── 2b2. 执行器后处理（P0-2）：引用校验 + 质量审核 ────────────────
    if with_executor and result.generated_answer:
        from scripts.evaluation.postprocess import (
            citation_accuracy,
            references_from_evidence,
            run_postprocess,
        )

        evidences = [ev for se in ctx.sub_question_evidence_list for ev in se.evidences]
        post = await run_postprocess(
            question=q.question,
            answer=result.generated_answer,
            references=references_from_evidence(evidences),
            fallback=model_fallback,
            run_quality=True,
        )
        result.generated_answer = post.answer
        result.citation_accuracy = citation_accuracy(post.answer, post.bad_refs)
        result.citation_ms = post.citation_ms
        result.quality_ms = post.quality_ms
        result.quality_passed = post.quality_passed
        result.quality_status = post.quality_status
        logger.info(
            "执行器后处理",
            question_id=q.id,
            bad_refs=post.bad_refs,
            citation_accuracy=result.citation_accuracy,
            quality_passed=post.quality_passed,
        )

    result.total_ms = (time.perf_counter() - total_start) * 1000

    # ── 2c. 拒答判定（Task 2）：只对不可答题有意义 ────────────────────
    if q.expected_refusal:
        from scripts.evaluation.refusal import judge_refusal

        result.refused = await judge_refusal(
            q.question, result.generated_answer, fallback=model_fallback
        )
        logger.info(
            "refusal judged",
            question_id=q.id,
            refused=result.refused,
            reason=q.metadata.get("unanswerable_reason"),
        )

    if not judge_enabled:
        result.status = "completed"
        return result

    # ── 3. 评估（使用传入的 eval_service 真实评分，激活代理链路）───
    try:
        service = eval_service or RAGEvaluationService()
        score_map = await service.evaluate_dataset(
            question=q.question,
            answer=result.generated_answer,
            contexts=[c for c in result.retrieved_contexts],
            ground_truth=q.ground_truth_answer,
        )
        result.faithfulness_score = score_map.get("faithfulness")
        result.answer_relevancy_score = score_map.get("answer_relevancy")
        result.context_precision_score = score_map.get("context_precision")
        result.answer_correctness_score = score_map.get("answer_correctness")
        result.context_recall_score = score_map.get("context_recall")
    except Exception as e:
        result.status = "partial"
        result.error = f"evaluation error: {e}"
        logger.warning("evaluation scoring failed", question_id=q.id, error=str(e), exc_info=True)
        return result

    result.status = "completed"
    return result


async def run_evaluation(
    dataset: list[EvalQuestion],
    concurrency: int = 1,
    retrieval_only: bool = False,
    judge_enabled: bool = True,
    with_executor: bool = False,
) -> list[EvalResult]:
    """批量运行离线评估"""
    from app.db.session import close_db, init_db
    from app.infra.es import close_es, init_es
    from app.infra.pg import close_pg, init_pg

    await init_db()
    await init_pg()
    await init_es()

    # Task 0：通道隔离（只影响评测进程内的 settings，不改生产默认值）
    _apply_channel_selection(getattr(args, "channels", "both"), settings)

    # Task 4：按文档切分（dev 调参 / test 验泛化）
    if getattr(args, "split", "all") != "all":
        from scripts.evaluation.splits import filter_by_split

        split_chunks = await _load_indexed_chunks()
        chunk_docs = {str(c["chunk_id"]): c.get("document_id") for c in split_chunks}
        total = len(dataset)
        dataset = filter_by_split(dataset, chunk_docs, args.split)
        logger.info("split applied", split=args.split, kept=len(dataset), total=total)

    # Task 1：gold 片段对齐成 chunk_id（确定性映射，不需要人工或 LLM 标注）
    grounded_gold = await _ground_dataset_gold(dataset, gold_file=args.gold_file)

    try:
        engine = RagRetrievalEngine()
        eval_service = RAGEvaluationService()
        model_fallback = ModelFallbackManager(
            client=get_chat_client(),
        )
        rewriter = ChatQueryRewriteService()
        recommender = RecommendationService()

        semaphore = asyncio.Semaphore(concurrency)

        async def _run_one(q: EvalQuestion) -> EvalResult:
            async with semaphore:
                logger.info("evaluating", question_id=q.id, question=q.question[:60])
                return await evaluate_single(
                    q,
                    engine,
                    eval_service,
                    model_fallback,
                    rewriter=rewriter,
                    recommender=recommender,
                    retrieval_only=retrieval_only,
                    judge_enabled=judge_enabled,
                    with_executor=with_executor,
                )

        tasks = [_run_one(q) for q in dataset]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await close_db()
        await close_es()
        await close_pg()

    # 量化能力 #2：Recall@5/10 + MRR + nDCG@5/10（基于 relevant_contexts 的排序质量）
    final: list[EvalResult] = []
    # 评估深度与 final_top_k 对齐：final_top_k=8 时 R@10 实际只能看到 8 条，指标结构性失真
    eval_depth = max(1, int(settings.rag.final_top_k or 10))
    for i, r in enumerate(results):
        if isinstance(r, EvalResult):
            _apply_legacy_metrics(r, dataset[i], eval_depth)
            _apply_id_metrics(r, dataset[i], grounded_gold.get(dataset[i].id) or {}, eval_depth)
            final.append(r)
        else:
            final.append(
                EvalResult(
                    question_id=dataset[i].id,
                    question=dataset[i].question,
                    status="failed",
                    error=str(r),
                )
            )

    return final


def _jev_coverage() -> dict[str, Any]:
    """JEV 决策覆盖率（P0-1）：证明 V3 跑的是 JEV，而不是 fail-open 回退。"""
    try:
        from app.infra.jev_client import jev_coverage

        return jev_coverage()
    except Exception:  # noqa: BLE001 - 埋点失败不应影响评测
        return {"flags": {}, "totals": {"decided": 0, "failed": 0, "disabled": 0, "attempted": 0}}


_LATENCY_STAGES = ("total", "retrieval", "generation", "citation", "quality")


def _latency_block(results: list[Any]) -> dict[str, Any]:
    """按阶段聚合 p50/p95 延迟（P0-3）。

    V3 的主张是"质量非劣 + 延迟更低"，没有延迟口径这个主张无法证伪。
    只统计 completed 且该阶段有值的样本：retrieval-only 跑没有 generation_ms，
    不能当 0 计入，否则会凭空造出一个"极快"的生成阶段。
    """
    from scripts.evaluation.metrics import percentile

    completed = [r for r in results if getattr(r, "status", "") == "completed"]
    block: dict[str, Any] = {}
    for stage in _LATENCY_STAGES:
        values = [
            float(v)
            for r in completed
            if (v := getattr(r, f"{stage}_ms", None)) is not None and float(v) > 0
        ]
        block[f"latency_{stage}_p50_ms"] = round(percentile(values, 50), 1) if values else None
        block[f"latency_{stage}_p95_ms"] = round(percentile(values, 95), 1) if values else None
        block[f"latency_{stage}_samples"] = len(values)
    block["latency_samples"] = block.get("latency_total_samples", 0)
    return block


def _generation_temperature() -> float:
    """评测生成温度：eval_temperature 优先，否则沿用线上 temperature。"""
    eval_temp = getattr(settings.llm, "eval_temperature", None)
    return settings.llm.temperature if eval_temp is None else float(eval_temp)


def evaluate_gates(
    gates: list[tuple[str, float, float | None]],
) -> tuple[list[str], list[tuple[str, float, float]]]:
    """判定门禁：阈值 0 跳过；样本缺失记 skipped；低于阈值记 violations。"""
    skipped = [name for name, threshold, value in gates if threshold > 0 and value is None]
    violations = [
        (name, threshold, float(value))
        for name, threshold, value in gates
        if threshold > 0 and value is not None and float(value) < threshold
    ]
    return skipped, violations


def _fmt_num(value: float | None, width: int = 5) -> str:
    """无有效评分样本时显示 N/A，避免与"真实 0 分"混淆。"""
    return f"{'N/A':<{width}}" if value is None else f"{value:.3f}"


def _print_report(
    results: list[EvalResult], run_tag: str
) -> tuple[dict[str, float], dict[str, Any]]:
    """打印报告并返回各指标平均分与阶段归因统计（供门禁与溯源）"""

    def _avg(vals: list[float]) -> float | None:
        # 无样本一律 None：返回 0.0 会让"没评"与"真实 0 分"混为一谈，
        # 也会把均值拉低、把门禁判失败。
        if not vals:
            return None
        return sum(vals) / len(vals)

    completed = [r for r in results if r.status == "completed"]
    partial = [r for r in results if r.status == "partial"]
    failed = [r for r in results if r.status == "failed"]

    # 仅聚合"评分成功"的样本：失败(None)指标被排除，避免与真实 0 分混淆
    metric_fields = {
        "faithfulness": "faithfulness_score",
        "answer_relevancy": "answer_relevancy_score",
        "context_precision": "context_precision_score",
        "answer_correctness": "answer_correctness_score",
        "context_recall": "context_recall_score",
    }
    judge_failed = {
        name: sum(1 for r in completed if getattr(r, field) is None)
        for name, field in metric_fields.items()
    }

    faithfulness = [r.faithfulness_score for r in completed if r.faithfulness_score is not None]
    relevancy = [
        r.answer_relevancy_score for r in completed if r.answer_relevancy_score is not None
    ]
    precision = [
        r.context_precision_score for r in completed if r.context_precision_score is not None
    ]
    correctness = [
        r.answer_correctness_score for r in completed if r.answer_correctness_score is not None
    ]
    recall = [r.context_recall_score for r in completed if r.context_recall_score is not None]
    # 评估深度与 final_top_k 对齐（final_top_k=8 时不报 R@10）
    eval_depth = max(1, int(settings.rag.final_top_k or 10))
    recall5 = [r.recall_at_5 for r in completed if r.recall_at_5 is not None]
    recall_final = [r.recall_at_final_k for r in completed if r.recall_at_final_k is not None]
    mrr = [r.mrr for r in completed if r.mrr is not None]
    ndcg5 = [r.ndcg_at_5 for r in completed if r.ndcg_at_5 is not None]
    ndcg_final = [r.ndcg_at_final_k for r in completed if r.ndcg_at_final_k is not None]
    # Task 1：按证据 ID 判定的召回（None = 该题无 gold，不进均值）
    recall5_ids = [r.recall_at_5_ids for r in completed if r.recall_at_5_ids is not None]
    recall_final_ids = [
        r.recall_at_final_k_ids for r in completed if r.recall_at_final_k_ids is not None
    ]
    mrr_ids = [r.mrr_ids for r in completed if r.mrr_ids is not None]
    ndcg5_ids = [r.ndcg_at_5_ids for r in completed if r.ndcg_at_5_ids is not None]
    recall5_pids = [
        r.recall_at_5_parent_ids for r in completed if r.recall_at_5_parent_ids is not None
    ]
    recall_final_pids = [
        r.recall_at_final_k_parent_ids
        for r in completed
        if r.recall_at_final_k_parent_ids is not None
    ]

    citation_acc = [r.citation_accuracy for r in completed if r.citation_accuracy is not None]
    quality_judged = [r for r in completed if r.quality_passed is not None]
    quality_pass_rate = (
        sum(1 for r in quality_judged if r.quality_passed) / len(quality_judged)
        if quality_judged
        else None
    )
    # fail-open 的"没审成"必须单列，否则 quality_pass_rate 会被 unknown 抬高
    quality_unknown = sum(1 for r in quality_judged if r.quality_status in {"unknown", "error"})
    quality_unknown_rate = quality_unknown / len(quality_judged) if quality_judged else None

    from scripts.evaluation.refusal import refusal_rates

    refusal = refusal_rates(completed)
    corpus_gap_cases = sum(
        1
        for r in completed
        if r.expected_refusal and r.unanswerable_reason == "source_document_absent"
    )

    avg = {
        "faithfulness": _avg(faithfulness),
        "recall_at_5": _avg(recall5),
        "recall_at_final_k": _avg(recall_final),
        "mrr": _avg(mrr),
        "ndcg_at_5": _avg(ndcg5),
        "ndcg_at_final_k": _avg(ndcg_final),
        "answer_relevancy": _avg(relevancy),
        "context_precision": _avg(precision),
        "answer_correctness": _avg(correctness),
        "context_recall": _avg(recall),
        # Task 1：chunk 级（主口径）与章节级（辅助口径）
        "recall_at_5_ids": _avg(recall5_ids),
        "recall_at_final_k_ids": _avg(recall_final_ids),
        "mrr_ids": _avg(mrr_ids),
        "ndcg_at_5_ids": _avg(ndcg5_ids),
        "recall_at_5_parent_ids": _avg(recall5_pids),
        "recall_at_final_k_parent_ids": _avg(recall_final_pids),
        "grounded_questions": len(recall5_ids),
        # P0-2：执行器后处理的产出（None = 该题没有引用 / 未跑后处理）
        "citation_accuracy": _avg(citation_acc) if citation_acc else None,
        "citation_samples": len(citation_acc),
        "quality_pass_rate": quality_pass_rate,
        "quality_unknown_rate": quality_unknown_rate,
        "quality_samples": len(quality_judged),
        # Task 2：拒答表现（None = 本轮没有不可答题，不参与门禁）
        "correct_refusal_rate": refusal["correct_refusal_rate"],
        "false_answer_rate": refusal["false_answer_rate"],
        "refusal_cases": refusal["refusal_cases"],
        "corpus_gap_cases": corpus_gap_cases,
    }
    avg.update(_latency_block(results))

    stage_totals: dict[str, Any] = {
        "total_snippets": 0,
        "hit": 0,
        "cutoff_dropped": 0,
        "rerank_demoted": 0,
        "fusion_dropped": 0,
        "unrecalled": 0,
    }
    for r in completed:
        if not r.answerable:
            continue
        stg = r.stage_attribution.get("stats", {})
        for k in ["hit", "cutoff_dropped", "rerank_demoted", "fusion_dropped", "unrecalled"]:
            stage_totals[k] += stg.get(k, 0)
        stage_totals["total_snippets"] += stg.get("total", 0)

    stage_totals["judge_failed"] = judge_failed

    tot = stage_totals["total_snippets"]
    if tot > 0:
        stage_totals["hit_rate"] = round(stage_totals["hit"] / tot, 4)
        stage_totals["cutoff_drop_rate"] = round(stage_totals["cutoff_dropped"] / tot, 4)
        stage_totals["rerank_demote_rate"] = round(stage_totals["rerank_demoted"] / tot, 4)
        stage_totals["fusion_drop_rate"] = round(stage_totals["fusion_dropped"] / tot, 4)
        stage_totals["unrecalled_rate"] = round(stage_totals["unrecalled"] / tot, 4)

    logger.info("=" * 60)
    logger.info("  Offline RAG Evaluation Report — round %s", run_tag)
    logger.info(
        "  Completed: %d / %d (partial=%d, failed=%d)",
        len(completed),
        len(results),
        len(partial),
        len(failed),
    )

    def _fmt(samples: list[float]) -> str:
        return _fmt_num(_avg(samples))

    logger.info("  ├──────────────────────┬──────────┤")
    logger.info("  │ Faithfulness         │ %s    │", _fmt(faithfulness))
    logger.info("  │ Answer Relevancy     │ %s    │", _fmt(relevancy))
    logger.info("  │ Context Precision    │ %s    │", _fmt(precision))
    logger.info("  │ Answer Correctness   │ %s    │", _fmt(correctness))
    logger.info("  │ Context Recall       │ %s    │", _fmt(recall))
    logger.info(
        "  │ Recall@5 / Recall@%-2d │ %s / %s │",
        eval_depth,
        _fmt_num(avg.get("recall_at_5")),
        _fmt_num(avg.get("recall_at_final_k")),
    )
    logger.info(
        "  │ MRR / nDCG@%-2d        │ %s / %s │",
        eval_depth,
        _fmt_num(avg.get("mrr")),
        _fmt_num(avg.get("ndcg_at_final_k")),
    )
    if refusal["refusal_cases"]:
        logger.info(
            "  │ 拒答正确率 / 编造率  │ %s / %s │",
            f"{refusal['correct_refusal_rate']:.3f}",
            f"{refusal['false_answer_rate']:.3f}",
        )
    _judge_failed_total = sum(judge_failed.values())
    if _judge_failed_total:
        logger.info("  │ Judge failures       │ %-8d │", _judge_failed_total)
    if avg.get("latency_samples"):
        logger.info("  ├──────────────────────────────────────────────┤")
        logger.info("  │ 延迟 (ms, p50 / p95)                        │")
        for stage, label in (
            ("total", "端到端"),
            ("retrieval", "检索"),
            ("generation", "生成"),
            ("citation", "引用校验"),
            ("quality", "质量审核"),
        ):
            p50 = avg.get(f"latency_{stage}_p50_ms")
            if p50 is None:
                continue
            p95 = avg.get(f"latency_{stage}_p95_ms")
            n = avg.get(f"latency_{stage}_samples", 0)
            logger.info(
                "  │ • %-6s %9.1f / %9.1f  (n=%d)          │",
                label,
                p50,
                p95,
                n,
            )
    if avg.get("quality_samples") or avg.get("citation_samples"):
        logger.info("  ├──────────────────────────────────────────────┤")
        logger.info("  │ 执行器后处理 (P0-2)                          │")
        if avg.get("citation_accuracy") is not None:
            logger.info(
                "  │ • 引用准确率:     %s  (n=%d)      │",
                f"{avg['citation_accuracy']:.3f}",
                int(avg.get("citation_samples", 0)),
            )
        if avg.get("quality_pass_rate") is not None:
            logger.info(
                "  │ • 质量审核通过率: %s  (n=%d)      │",
                f"{avg['quality_pass_rate']:.3f}",
                int(avg.get("quality_samples", 0)),
            )
        if avg.get("quality_unknown_rate") is not None:
            logger.info(
                "  │ • 质量审核未知率: %s  (fail-open)  │",
                f"{avg['quality_unknown_rate']:.3f}",
            )
    if tot > 0:
        logger.info("  ├──────────────────────────────────────────────┤")
        logger.info("  │ Retrieval Lab 召回归因 (Stage Attribution)   │")
        logger.info("  │ • 应检证据总数:   %4d                        │", tot)
        logger.info(
            "  │ • 成功保留(Hit):  %4d (%5.1f%%)              │",
            stage_totals["hit"],
            stage_totals["hit_rate"] * 100,
        )
        logger.info(
            "  │ • 最终截断丢失:   %4d (%5.1f%%)              │",
            stage_totals["cutoff_dropped"],
            stage_totals["cutoff_drop_rate"] * 100,
        )
        logger.info(
            "  │ • 重排降级丢失:   %4d (%5.1f%%)              │",
            stage_totals["rerank_demoted"],
            stage_totals["rerank_demote_rate"] * 100,
        )
        logger.info(
            "  │ • 融合截断丢失:   %4d (%5.1f%%)              │",
            stage_totals["fusion_dropped"],
            stage_totals["fusion_drop_rate"] * 100,
        )
        logger.info(
            "  │ • 初始检索未召回: %4d (%5.1f%%)              │",
            stage_totals["unrecalled"],
            stage_totals["unrecalled_rate"] * 100,
        )
    logger.info("  └──────────────────────┴──────────┘")

    logger.info("\n  Per-question breakdown:")
    for r in completed:
        f = f"{r.faithfulness_score:.2f}" if r.faithfulness_score is not None else "N/A"
        cr = f"{r.context_recall_score:.2f}" if r.context_recall_score is not None else "N/A"
        ac = (
            f"{r.answer_correctness_score:.2f}" if r.answer_correctness_score is not None else "N/A"
        )
        rw_flag = " [rewritten]" if r.rewritten_question else ""
        stg_stat = r.stage_attribution.get("stats", {})
        stg_str = (
            f" [Hit {stg_stat.get('hit', 0)}/{stg_stat.get('total', 0)}]"
            if stg_stat.get("total", 0) > 0
            else ""
        )
        logger.info("    %6s  F=%s  CR=%s  AC=%s%s%s", r.question_id, f, cr, ac, rw_flag, stg_str)
        if r.rewritten_question:
            logger.info("             ⟶ %s", r.rewritten_question[:80])
        if r.generated_recommendations:
            for rec in r.generated_recommendations[:2]:
                logger.info("             ↳ %s", rec[:60])

    if failed:
        for r in failed:
            logger.warning("    %6s  FAILED: %s", r.question_id, r.error)
    if partial:
        for r in partial:
            logger.warning("    %6s  PARTIAL: %s", r.question_id, r.error)

    cov = _jev_coverage()
    totals = cov["totals"]
    if totals["attempted"] or totals["disabled"]:
        logger.info("  ├──────────────────────────────────────────────┤")
        logger.info("  │ JEV 决策覆盖 (P0-1)                          │")
        logger.info(
            "  │ • 成功决策/尝试:  %4d / %4d                  │",
            totals["decided"],
            totals["attempted"],
        )
        logger.info("  │ • 回退失败:       %4d                        │", totals["failed"])
        logger.info("  │ • 开关关闭跳过:   %4d                        │", totals["disabled"])
        for flag, stat in sorted(cov["flags"].items()):
            if not stat.get("calls"):
                continue
            logger.info(
                "  │   - %-28s p50=%6.1fms p95=%6.1fms │",
                flag,
                stat["p50_ms"] or 0.0,
                stat["p95_ms"] or 0.0,
            )

    logger.info("%s", "=" * 60)
    return avg, stage_totals


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Offline RAG Evaluation (regression gate)")
    parser.add_argument("--round", type=str, default="latest", help="Round tag for report")
    parser.add_argument("--questions", type=int, default=0, help="Number of questions (0 = all)")
    # P1-3 门禁：低于任一阈值则退出码 1（可接入 CI / pre-commit）
    parser.add_argument("--min-faithfulness", type=float, default=0.6)
    parser.add_argument("--min-relevancy", type=float, default=0.6)
    parser.add_argument("--min-precision", type=float, default=0.6)
    parser.add_argument("--min-recall", type=float, default=0.6)
    parser.add_argument("--min-correctness", type=float, default=0.6)
    # 检索层门禁：0 = 跳过；用 chunk_id 口径的 R@5（不依赖 LLM judge，可在 retrieval-only 下跑）
    parser.add_argument("--min-recall-ids", type=float, default=0.0)
    parser.add_argument("--json-report", type=str, default="", help="Write JSON report to path")
    parser.add_argument(
        "--gold-file",
        type=str,
        default="",
        help="预生成的 gold chunk_id 文件（scripts.evaluation.ground_gold 产出）；缺省时用词法自动对齐",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="跳过 5 个 LLM judge 指标（仍生成回答并测拒答），用于快速迭代",
    )
    parser.add_argument(
        "--judge-model",
        type=str,
        default="",
        help="锁定评估裁判使用的 LLM 模型（默认为 settings.llm.model，如 deepseek-v4-flash）",
    )
    parser.add_argument(
        "--compare",
        type=str,
        default="",
        help="量化能力 #3：对比两份 JSON 报告，如 --compare base.json opt.json（输出指标 diff）",
    )
    parser.add_argument(
        "--variant",
        type=str,
        default="",
        choices=["", "v1", "v2", "v3"],
        help="消融实验分支: v1 (纯向量+纯LLM), v2 (双通道+纯LLM), v3 (双通道+JEV+LLM)",
    )
    parser.add_argument("--concurrency", type=int, default=2, help="评估并发数")
    parser.add_argument(
        "--sample-per-category",
        type=int,
        default=0,
        help="从5个企业测评类别中各采样N题组成严谨均衡的基准子集 (0 表示全量)",
    )
    parser.add_argument(
        "--reranker-on",
        action="store_true",
        help="量化能力 #5：强制开启 Reranker（A/B 用，与默认关闭对比）",
    )

    parser.add_argument(
        "--reranker-off",
        action="store_true",
        help="量化能力 #5：强制关闭 Reranker（A/B 用）",
    )
    # P1 调优网格：命令行覆盖检索/融合/重排参数（0 或负值表示沿用配置默认）
    parser.add_argument("--vector-top-k", type=int, default=0, help="覆盖向量通道 top-k")
    parser.add_argument("--keyword-top-k", type=int, default=0, help="覆盖关键词通道 top-k")
    parser.add_argument("--candidate-top-k", type=int, default=0, help="覆盖 RRF 融合候选数")
    parser.add_argument("--final-top-k", type=int, default=0, help="覆盖最终证据数")
    parser.add_argument("--rrf-k", type=int, default=0, help="覆盖 RRF k")
    parser.add_argument("--rrf-vector-weight", type=float, default=-1.0, help="覆盖 RRF 向量权重")
    parser.add_argument(
        "--rrf-keyword-weight", type=float, default=-1.0, help="覆盖 RRF 关键词权重"
    )
    parser.add_argument("--rerank-top-n", type=int, default=0, help="覆盖 Reranker top_n")
    parser.add_argument(
        "--rerank-relative-ratio", type=float, default=-1.0, help="覆盖重排相对阈值 ratio"
    )
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="P1 网格搜索快速通道：仅检索与召回归因，跳过生成与 LLM 评测",
    )
    parser.add_argument(
        "--with-executor",
        action="store_true",
        help="复刻生产执行器的生成后处理（引用校验 + 质量审核），让 JEV 参与评测",
    )
    parser.add_argument(
        "--multi-hop-split",
        action="store_true",
        help="P2 强制开启生产多跳拆分（复合/多条件问题拆为多个检索子查询）",
    )
    parser.add_argument(
        "--no-multi-hop-split",
        action="store_true",
        help="P2 强制关闭生产多跳拆分（A/B 基线对照用）",
    )
    parser.add_argument(
        "--no-rewrite",
        action="store_true",
        help="跳过查询改写 LLM 调用（零成本验证用）",
    )
    parser.add_argument(
        "--keyword-only",
        action="store_true",
        help="仅关键词通道（关闭向量通道，跳过 embedding）",
    )
    parser.add_argument(
        "--generated-file",
        default="",
        help="追加自动生成的题目文件（Task 4 扩容）",
    )
    parser.add_argument(
        "--split",
        choices=["all", "dev", "test"],
        default="all",
        help="按文档切分：dev 调参、test 验泛化（--generated-file 时才有意义）",
    )
    parser.add_argument(
        "--channels",
        choices=["both", "vector", "keyword"],
        default="both",
        help="通道隔离（仅评测用）：vector=关关键词通道，keyword=关向量通道",
    )
    parser.add_argument(
        "--subset",
        choices=["all", "emp", "lex"],
        default="all",
        help="题库子集：emp=85 道自然语言题，lex=编号类题",
    )
    parser.add_argument(
        "--free",
        action="store_true",
        help="零成本模式 = --retrieval-only + --no-rewrite + --reranker-off",
    )
    args = parser.parse_args()

    dataset = load_dataset()
    if args.sample_per_category > 0:
        n = args.sample_per_category
        cat1 = [q for q in dataset if 1 <= int(q.id.replace("emp", "")) <= 20][:n]
        cat2 = [q for q in dataset if 21 <= int(q.id.replace("emp", "")) <= 38][:n]
        cat3 = [q for q in dataset if 39 <= int(q.id.replace("emp", "")) <= 55][:n]
        cat4 = [q for q in dataset if 56 <= int(q.id.replace("emp", "")) <= 70][:n]
        cat5 = [q for q in dataset if 71 <= int(q.id.replace("emp", "")) <= 85][:n]
        dataset = cat1 + cat2 + cat3 + cat4 + cat5
    elif args.questions:
        dataset = dataset[: args.questions]

    if args.generated_file:
        dataset = dataset + _load_generated_questions(args.generated_file)

    # 题库子集与通道隔离（必须在 gold 对齐之前，gold 只对留下的题做）
    dataset = _filter_subset(dataset, args.subset)
    # dev/test 切分需要 chunk→document 映射，放到 run_evaluation 里 init_db 之后做

    from app.config import get_settings as _gs

    _settings = _gs()
    if args.judge_model:
        _settings.rag.evaluation_model = args.judge_model

    judge_model_name = _settings.rag.evaluation_model or _settings.llm.model

    def _set_online_jev(enabled: bool) -> None:
        # 仅开启 SUT 在线决策原语（意图分流、安全护栏、语义充分性拦截）
        _settings.jev.evidence_sufficiency_enabled = enabled
        _settings.jev.intent_detection_enabled = enabled
        _settings.jev.guardrail_enabled = enabled
        # 评测指标必须锁定单一强 LLM 裁判，严禁 JEV 接管评测指标！
        _settings.jev.faithfulness_eval_enabled = False
        _settings.jev.answer_relevancy_enabled = False
        _settings.jev.answer_correctness_enabled = False
        _settings.jev.context_precision_enabled = False
        _settings.jev.context_recall_enabled = False

    if args.variant == "v1":
        _settings.rag.keyword_channel_enabled = False
        _settings.rerank.enabled = False
        _set_online_jev(False)
    elif args.variant == "v2":
        _settings.rag.keyword_channel_enabled = True
        _settings.rerank.enabled = True
        _set_online_jev(False)
    elif args.variant == "v3":
        _settings.rag.keyword_channel_enabled = True
        _settings.rerank.enabled = True
        _settings.rag.corrective_retrieval_enabled = True
        _set_online_jev(True)

    if args.reranker_on:
        _settings.rerank.enabled = True
    if args.reranker_off:
        _settings.rerank.enabled = False

    # P1 调优网格：命令行参数覆盖（仅在显式传入时生效）
    if args.vector_top_k > 0:
        _settings.rag.vector_top_k = args.vector_top_k
    if args.keyword_top_k > 0:
        _settings.rag.keyword_top_k = args.keyword_top_k
    if args.candidate_top_k > 0:
        _settings.rag.candidate_top_k = args.candidate_top_k
    if args.final_top_k > 0:
        _settings.rag.final_top_k = args.final_top_k
    if args.rrf_k > 0:
        _settings.rag.rrf_k = args.rrf_k
    if args.rrf_vector_weight >= 0:
        _settings.rag.rrf_vector_weight = args.rrf_vector_weight
    if args.rrf_keyword_weight >= 0:
        _settings.rag.rrf_keyword_weight = args.rrf_keyword_weight
    if args.rerank_top_n > 0:
        _settings.rerank.top_n = args.rerank_top_n
    if args.rerank_relative_ratio >= 0:
        _settings.rag.rerank_relative_ratio = args.rerank_relative_ratio
    if args.multi_hop_split:
        _settings.rag.multi_hop_split_enabled = True
    if args.no_multi_hop_split:
        _settings.rag.multi_hop_split_enabled = False

    # A7 零成本验证开关
    if args.no_rewrite:
        _settings.rag.rewrite_enabled = False
    if args.keyword_only:
        _settings.rag.vector_channel_enabled = False
    if args.free:
        _settings.rag.rewrite_enabled = False
        _settings.rag.vector_channel_enabled = False
        _settings.rerank.enabled = False
        args.retrieval_only = True

    logger.info(
        "Running evaluation round %s (variant=%s) with %d questions (keyword=%s, reranker=%s, online_jev=%s, judge_model=%s)...",
        args.round,
        args.variant or "custom",
        len(dataset),
        _settings.rag.keyword_channel_enabled,
        _settings.rerank.enabled,
        _settings.jev.intent_detection_enabled,
        judge_model_name,
    )

    results = asyncio.run(
        run_evaluation(
            dataset,
            concurrency=args.concurrency,
            retrieval_only=args.retrieval_only,
            judge_enabled=not args.no_judge,
            with_executor=args.with_executor,
        )
    )

    avg, stage_summary = _print_report(results, args.round)

    if args.json_report:
        with open(args.json_report, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "provenance": {
                        "judge_model": judge_model_name,
                        "jev_coverage": _jev_coverage(),
                        "with_executor": bool(args.with_executor),
                        "variant": args.variant or "custom",
                        "keyword_channel_enabled": _settings.rag.keyword_channel_enabled,
                        "rerank_enabled": _settings.rerank.enabled,
                        "online_jev_enabled": bool(_settings.jev.intent_detection_enabled),
                        "vector_top_k": _settings.rag.vector_top_k,
                        "keyword_top_k": _settings.rag.keyword_top_k,
                        "candidate_top_k": _settings.rag.candidate_top_k,
                        "final_top_k": _settings.rag.final_top_k,
                        "retrieval_eval_depth": max(1, int(_settings.rag.final_top_k or 10)),
                        "rrf_k": _settings.rag.rrf_k,
                        "rrf_vector_weight": _settings.rag.rrf_vector_weight,
                        "rrf_keyword_weight": _settings.rag.rrf_keyword_weight,
                        "rerank_top_n": _settings.rerank.top_n,
                        "rerank_min_score": _settings.rag.rerank_min_score,
                        "rerank_relative_ratio": _settings.rag.rerank_relative_ratio,
                        "rerank_skip_min_similarity": _settings.rag.rerank_skip_min_similarity,
                        "rerank_rank1_guard_enabled": _settings.rag.rerank_rank1_guard_enabled,
                        "multi_hop_split_enabled": _settings.rag.multi_hop_split_enabled,
                        "max_sub_questions": _settings.rag.max_sub_questions,
                        "judge_temperature": 0.0,
                        "eval_context_max_chars": _settings.rag.eval_context_max_chars,
                        "reference_snippet_max_chars": _settings.rag.reference_snippet_max_chars,
                        "vector_channel_enabled": _settings.rag.vector_channel_enabled,
                        "total_questions": len(results),
                    },
                    "round": args.round,
                    "total": len(results),
                    "averages": avg,
                    "stage_attribution_summary": stage_summary,
                    "failed": [r.error for r in results if r.status == "failed"],
                    "results": [
                        {
                            "question_id": r.question_id,
                            "question": r.question,
                            "rewritten_question": r.rewritten_question,
                            "ground_truth": r.ground_truth_answer,
                            "generated_answer": r.generated_answer[:500],
                            "retrieved_contexts": r.retrieved_contexts,
                            "stage_attribution": r.stage_attribution,
                            "faithfulness_score": r.faithfulness_score,
                            "answer_relevancy_score": r.answer_relevancy_score,
                            "context_precision_score": r.context_precision_score,
                            "answer_correctness_score": r.answer_correctness_score,
                            "context_recall_score": r.context_recall_score,
                            "recall_at_5": r.recall_at_5,
                            "recall_at_final_k": r.recall_at_final_k,
                            "mrr": r.mrr,
                            "ndcg_at_5": r.ndcg_at_5,
                            "ndcg_at_final_k": r.ndcg_at_final_k,
                            "recall_at_5_ids": r.recall_at_5_ids,
                            "recall_at_final_k_ids": r.recall_at_final_k_ids,
                            "mrr_ids": r.mrr_ids,
                            "ndcg_at_5_ids": r.ndcg_at_5_ids,
                            "recall_at_5_parent_ids": r.recall_at_5_parent_ids,
                            "recall_at_final_k_parent_ids": r.recall_at_final_k_parent_ids,
                            "retrieved_chunk_ids": r.retrieved_chunk_ids,
                            "expected_refusal": r.expected_refusal,
                            "refused": r.refused,
                            "total_ms": round(r.total_ms, 1) if r.total_ms else None,
                            "retrieval_ms": round(r.retrieval_ms, 1) if r.retrieval_ms else None,
                            "generation_ms": round(r.generation_ms, 1) if r.generation_ms else None,
                        }
                        for r in results
                    ],
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )
        logger.info("JSON report written to %s", args.json_report)

    # 量化能力 #3：对比两份报告
    if args.compare:
        import json as _json

        try:
            base_path, opt_path = args.compare.split(",")
            with open(base_path, encoding="utf-8") as _bf, open(opt_path, encoding="utf-8") as _of:
                base = _json.load(_bf)
                opt = _json.load(_of)
        except Exception as e:
            logger.error("compare failed: %s", e)
            sys.exit(2)
        b_avg, o_avg = base["averages"], opt["averages"]
        print("\n=== 优化对比（base → opt）===")
        for metric in sorted(set(b_avg) | set(o_avg)):
            if metric.startswith("latency_"):
                continue  # 延迟单位是 ms，单独成表
            b = b_avg.get(metric)
            o = o_avg.get(metric)
            if b is None or o is None:
                if b != o:
                    print(f"  {metric:<20} {_fmt_num(b)} → {_fmt_num(o)}  (样本不足，不比差值)")
                continue
            delta = o - b
            arrow = "▲" if delta > 0.005 else ("▼" if delta < -0.005 else "＝")
            print(f"  {metric:<20} {b:.3f} → {o:.3f}  {arrow} {delta:+.3f}")

        if any(k.startswith("latency_") for k in set(b_avg) | set(o_avg)):
            print("\n=== 延迟对比（ms，p50 / p95，负值=更快）===")
            for stage, label in (
                ("total", "端到端"),
                ("retrieval", "检索"),
                ("generation", "生成"),
            ):
                bp50 = b_avg.get(f"latency_{stage}_p50_ms")
                op50 = o_avg.get(f"latency_{stage}_p50_ms")
                if bp50 is None or op50 is None:
                    continue
                bp95 = b_avg.get(f"latency_{stage}_p95_ms")
                op95 = o_avg.get(f"latency_{stage}_p95_ms")
                print(
                    f"  {label:<6} p50 {bp50:8.1f} → {op50:8.1f}  ({op50 - bp50:+8.1f})"
                    f"   p95 {bp95:8.1f} → {op95:8.1f}  ({op95 - bp95:+8.1f})"
                )

        # 配对 bootstrap：85 题量级下 ±0.02 的均值差可能完全来自噪声，
        # 因此对逐题指标做配对重采样，给出 95% CI 与显著性判定。
        from scripts.evaluation.metrics import (
            extract_metric_series,
            paired_bootstrap_delta,
        )

        print("\n=== 显著性（配对 bootstrap，2000 次重采样，按 question_id 配对）===")
        for metric in (
            "recall_at_5",
            "recall_at_final_k",
            "mrr",
            "ndcg_at_5",
            "ndcg_at_final_k",
            "faithfulness",
            "context_recall",
            "recall_at_5_ids",
            "recall_at_final_k_ids",
            "mrr_ids",
            "ndcg_at_5_ids",
            "total_ms",
            "retrieval_ms",
            "generation_ms",
        ):
            b_vals, o_vals = extract_metric_series(base, opt, metric)
            if not b_vals:
                continue
            r = paired_bootstrap_delta(b_vals, o_vals)
            verdict = "显著" if r["significant"] else "噪声（不足以判定）"
            if metric.endswith("_ms"):
                verdict += " [延迟：Δ<0 为更快]"
            print(
                f"  {metric:<18} Δ{r['delta']:+.4f}  "
                f"95%CI[{r['ci_low']:+.4f}, {r['ci_high']:+.4f}]  "
                f"p={r['p_value']:.3f}  n={r['n']}  {verdict}"
            )

    # 门禁判定：阈值 0 表示跳过该指标；retrieval_only 模式下跳过生成指标门禁
    gates: list[tuple[str, float, float | None]] = []
    if args.min_recall_ids > 0:
        # 检索层门禁不依赖 judge，任何模式下都应生效
        gates.append(("recall_at_5_ids", args.min_recall_ids, avg.get("recall_at_5_ids")))
    if not args.retrieval_only and not args.no_judge:
        gates.extend(
            [
                ("faithfulness", args.min_faithfulness, avg["faithfulness"]),
                ("answer_relevancy", args.min_relevancy, avg["answer_relevancy"]),
                ("context_precision", args.min_precision, avg["context_precision"]),
                ("context_recall", args.min_recall, avg["context_recall"]),
                ("answer_correctness", args.min_correctness, avg["answer_correctness"]),
            ]
        )
    if gates:
        skipped, violations = evaluate_gates(gates)
        if skipped:
            logger.warning("门禁跳过（无有效样本）：%s", ", ".join(skipped))
        if violations:
            for name, threshold, actual in violations:
                logger.error("GATE FAILED: %s = %.3f < %.3f", name, actual, threshold)
            logger.error("Regression gate failed (%d violations)", len(violations))
            sys.exit(1)
        logger.info("Regression gate passed ✓")
    elif args.no_judge:
        logger.info("Judge-disabled evaluation completed ✓（仅生成 + 拒答 + 召回）")
    else:
        logger.info("Retrieval-only evaluation completed ✓")
