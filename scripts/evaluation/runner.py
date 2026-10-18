from __future__ import annotations

import asyncio
import time
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


def _extract_context_texts(ctx) -> list[str]:
    """从 RagRetrievalContext 提取检索到的证据文本，去重并按重排/综合得分降序排列"""
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
    texts: list[str] = []
    for ev in all_evidences:
        ref_prefix = (
            f"[{ev.reference_id}] " if getattr(ev, "reference_id", None) is not None else ""
        )
        texts.append(f"{ref_prefix}{ev.content}")
    return texts


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
) -> EvalResult:
    """对一条测试数据执行完整的 检索→生成→评估 流水线"""
    result = EvalResult(
        question_id=q.id,
        question=q.question,
        ground_truth_answer=q.ground_truth_answer,
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
            temperature=settings.llm.temperature,
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

    result.total_ms = (time.perf_counter() - total_start) * 1000

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
) -> list[EvalResult]:
    """批量运行离线评估"""
    from app.db.session import close_db, init_db
    from app.infra.es import close_es, init_es
    from app.infra.pg import close_pg, init_pg

    await init_db()
    await init_pg()
    await init_es()

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
                )

        tasks = [_run_one(q) for q in dataset]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await close_db()
        await close_es()
        await close_pg()

    # 量化能力 #2：Recall@5/10 + MRR + nDCG@5/10（基于 relevant_contexts 的排序质量）
    from scripts.evaluation.metrics import (
        compute_mrr,
        compute_ndcg_at_k,
        compute_recall_at_k,
    )

    final: list[EvalResult] = []
    # 评估深度与 final_top_k 对齐：final_top_k=8 时 R@10 实际只能看到 8 条，指标结构性失真
    eval_depth = max(1, int(settings.rag.final_top_k or 10))
    for i, r in enumerate(results):
        if isinstance(r, EvalResult):
            rel = dataset[i].relevant_contexts
            r.recall_at_5 = compute_recall_at_k(r.retrieved_contexts, rel, 5)
            r.recall_at_final_k = compute_recall_at_k(r.retrieved_contexts, rel, eval_depth)
            r.mrr = compute_mrr(r.retrieved_contexts, rel)
            r.ndcg_at_5 = compute_ndcg_at_k(r.retrieved_contexts, rel, 5)
            r.ndcg_at_final_k = compute_ndcg_at_k(r.retrieved_contexts, rel, eval_depth)
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


def _print_report(
    results: list[EvalResult], run_tag: str
) -> tuple[dict[str, float], dict[str, Any]]:
    """打印报告并返回各指标平均分与阶段归因统计（供门禁与溯源）"""

    def _avg(vals: list[float]) -> float:
        if not vals:
            return 0.0
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
    }

    stage_totals: dict[str, Any] = {
        "total_snippets": 0,
        "hit": 0,
        "cutoff_dropped": 0,
        "rerank_demoted": 0,
        "fusion_dropped": 0,
        "unrecalled": 0,
    }
    for r in completed:
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
        # 无有效评分样本时显示 N/A，避免与"真实 0 分"混淆
        return f"{_avg(samples):.3f}" if samples else "N/A  "

    logger.info("  ├──────────────────────┬──────────┤")
    logger.info("  │ Faithfulness         │ %s    │", _fmt(faithfulness))
    logger.info("  │ Answer Relevancy     │ %s    │", _fmt(relevancy))
    logger.info("  │ Context Precision    │ %s    │", _fmt(precision))
    logger.info("  │ Answer Correctness   │ %s    │", _fmt(correctness))
    logger.info("  │ Context Recall       │ %s    │", _fmt(recall))
    logger.info(
        "  │ Recall@5 / Recall@%-2d │ %.3f / %.3f │",
        eval_depth,
        avg.get("recall_at_5", 0.0),
        avg.get("recall_at_final_k", 0.0),
    )
    logger.info(
        "  │ MRR / nDCG@%-2d        │ %.3f / %.3f │",
        eval_depth,
        avg.get("mrr", 0.0),
        avg.get("ndcg_at_final_k", 0.0),
    )
    _judge_failed_total = sum(judge_failed.values())
    if _judge_failed_total:
        logger.info("  │ Judge failures       │ %-8d │", _judge_failed_total)
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
    parser.add_argument("--json-report", type=str, default="", help="Write JSON report to path")
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
        )
    )

    avg, stage_summary = _print_report(results, args.round)

    if args.json_report:
        with open(args.json_report, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "provenance": {
                        "judge_model": judge_model_name,
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
            b = b_avg.get(metric, 0.0)
            o = o_avg.get(metric, 0.0)
            delta = o - b
            arrow = "▲" if delta > 0.005 else ("▼" if delta < -0.005 else "＝")
            print(f"  {metric:<20} {b:.3f} → {o:.3f}  {arrow} {delta:+.3f}")

    # 门禁判定：阈值 0 表示跳过该指标；retrieval_only 模式下跳过生成指标门禁
    if not args.retrieval_only:
        gates = [
            ("faithfulness", args.min_faithfulness, avg["faithfulness"]),
            ("answer_relevancy", args.min_relevancy, avg["answer_relevancy"]),
            ("context_precision", args.min_precision, avg["context_precision"]),
            ("context_recall", args.min_recall, avg["context_recall"]),
            ("answer_correctness", args.min_correctness, avg["answer_correctness"]),
        ]
        violations = [g for g in gates if g[1] > 0 and g[2] < g[1]]
        if violations:
            for name, threshold, actual in violations:
                logger.error("GATE FAILED: %s = %.3f < %.3f", name, actual, threshold)
            logger.error("Regression gate failed (%d violations)", len(violations))
            sys.exit(1)
        logger.info("Regression gate passed ✓")
    else:
        logger.info("Retrieval-only evaluation completed ✓")
