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
from scripts.evaluation.metrics import compute_answer_correctness, compute_context_recall

logger = structlog.get_logger(__name__)
settings = get_settings()


def _build_plan(
    q: EvalQuestion,
    rewritten: str | None = None,
    keywords: list[str] | None = None,
) -> ExecutionPlan:
    """从测试问题构造最小 ExecutionPlan，可指定改写后的问题和搜索关键词"""
    rw = rewritten or q.question
    return ExecutionPlan(
        mode=ExecutionMode.RETRIEVAL,
        original_question=q.question,
        rewritten_question=rw,
        sub_questions=[
            SubQuestion(
                index=0,
                text=rw,
                original=q.question,
                query_context_hints=keywords or [],
            )
        ],
    )


def _extract_context_texts(ctx) -> list[str]:
    """从 RagRetrievalContext 提取检索到的证据文本"""
    texts: list[str] = []
    for sqe in ctx.sub_question_evidence_list:
        for ev in sqe.evidences:
            if ev.content:
                texts.append(f"[{ev.reference_id}] {ev.content}")
    return texts


async def evaluate_single(
    q: EvalQuestion,
    engine: RagRetrievalEngine,
    eval_service: RAGEvaluationService,
    model_fallback: ModelFallbackManager,
    rewriter: ChatQueryRewriteService | None = None,
    recommender: RecommendationService | None = None,
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
            if rewrite_result.rewritten and rewrite_result.rewritten != q.question:
                plan = _build_plan(
                    q,
                    rewritten=rewrite_result.rewritten,
                    keywords=rewrite_result.keywords,
                )
                result.rewritten_question = rewrite_result.rewritten
                logger.info(
                    "查询改写生效",
                    original=q.question[:50],
                    rewritten=rewrite_result.rewritten[:50],
                    keywords=rewrite_result.keywords,
                )
            elif rewrite_result.keywords:
                plan = _build_plan(q, keywords=rewrite_result.keywords)
                logger.info("查询关键词生效", keywords=rewrite_result.keywords)
        except Exception as e:
            logger.warning(
                "查询改写失败，使用原问题", question_id=q.id, error=str(e), exc_info=True
            )

    total_start = time.perf_counter()

    # ── 1. 检索 ────────────────────────────────────────────────────────
    try:
        retrieval_start = time.perf_counter()
        ctx = await engine.retrieve(plan)
        result.retrieval_ms = (time.perf_counter() - retrieval_start) * 1000
        result.retrieved_contexts = _extract_context_texts(ctx)
    except Exception as e:
        result.status = "failed"
        result.error = f"retrieve error: {e}"
        logger.warning("evaluation retrieve failed", question_id=q.id, error=str(e), exc_info=True)
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

    # ── 3. 评估 ────────────────────────────────────────────────────────
    try:
        # 3a. 已有 3 个指标
        scores = await eval_service.evaluate(
            conversation_id="offline",
            exchange_id=-1,
            question=q.question,
            answer=result.generated_answer,
            contexts=[c for c in result.retrieved_contexts],
        )
        result.faithfulness_score = scores.get("faithfulness_score")
        result.answer_relevancy_score = scores.get("answer_relevancy_score")
        result.context_precision_score = scores.get("context_precision_score")

        # 3b. 新增 2 个指标
        result.answer_correctness_score = await compute_answer_correctness(
            model_fallback,
            q.question,
            result.generated_answer,
            q.ground_truth_answer,
        )
        result.context_recall_score = compute_context_recall(
            result.retrieved_contexts,
            q.relevant_contexts,
        )
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
                )

        tasks = [_run_one(q) for q in dataset]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await close_db()
        await close_es()
        await close_pg()

    final: list[EvalResult] = []
    for i, r in enumerate(results):
        if isinstance(r, EvalResult):
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


def _print_report(results: list[EvalResult], run_tag: str) -> None:
    """Print a formatted evaluation report to stdout."""
    completed = [r for r in results if r.status == "completed"]
    failed = [r for r in results if r.status == "failed"]
    partial = [r for r in results if r.status == "partial"]

    logger.info("\n%s", "=" * 60)
    logger.info("  Round %s — Report", run_tag)
    logger.info("%s", "=" * 60)
    logger.info("  Total:    %d", len(results))
    logger.info("  Passed:   %d", len(completed))
    logger.info("  Failed:   %d", len(failed))
    logger.info("  Partial:  %d", len(partial))

    if not completed:
        logger.info("  (no completed results)")
        return

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

    def _avg(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    logger.info("\n  ┌──────────────────────┬──────────┐")
    logger.info("  │ Metric               │ Average  │")
    logger.info("  ├──────────────────────┼──────────┤")
    logger.info("  │ Faithfulness         │ %.3f    │", _avg(faithfulness))
    logger.info("  │ Answer Relevancy     │ %.3f    │", _avg(relevancy))
    logger.info("  │ Context Precision    │ %.3f    │", _avg(precision))
    logger.info("  │ Answer Correctness   │ %.3f    │", _avg(correctness))
    logger.info("  │ Context Recall       │ %.3f    │", _avg(recall))
    logger.info("  └──────────────────────┴──────────┘")

    logger.info("\n  Per-question breakdown:")
    for r in completed:
        f = f"{r.faithfulness_score:.2f}" if r.faithfulness_score is not None else "N/A"
        cr = f"{r.context_recall_score:.2f}" if r.context_recall_score is not None else "N/A"
        ac = (
            f"{r.answer_correctness_score:.2f}" if r.answer_correctness_score is not None else "N/A"
        )
        rw_flag = " [rewritten]" if r.rewritten_question else ""
        logger.info("    %6s  F=%s  CR=%s  AC=%s%s", r.question_id, f, cr, ac, rw_flag)
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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Offline RAG Evaluation")
    parser.add_argument("--round", type=str, default="latest", help="Round tag for report")
    parser.add_argument("--questions", type=int, default=0, help="Number of questions (0 = all)")
    args = parser.parse_args()

    dataset = load_dataset()
    if args.questions:
        dataset = dataset[: args.questions]

    logger.info("Running evaluation round %s with %d questions...", args.round, len(dataset))

    results = asyncio.run(run_evaluation(dataset))

    _print_report(results, args.round)
