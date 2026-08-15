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


def _print_report(results: list[EvalResult], run_tag: str) -> dict[str, float]:
    """打印报告并返回各指标平均分（P1-3：供门禁判断）"""
    def _avg(vals: list[float]) -> float:
        if not vals:
            return 0.0
        return sum(vals) / len(vals)

    completed = [r for r in results if r.status == "completed"]
    partial = [r for r in results if r.status == "partial"]
    failed = [r for r in results if r.status == "failed"]

    faithfulness = [r.faithfulness_score or 0.0 for r in completed]
    relevancy = [r.answer_relevancy_score or 0.0 for r in completed]
    precision = [r.context_precision_score or 0.0 for r in completed]
    correctness = [r.answer_correctness_score or 0.0 for r in completed]
    recall = [r.context_recall_score or 0.0 for r in completed]

    avg = {
        "faithfulness": _avg(faithfulness),
        "answer_relevancy": _avg(relevancy),
        "context_precision": _avg(precision),
        "answer_correctness": _avg(correctness),
        "context_recall": _avg(recall),
    }

    logger.info("=" * 60)
    logger.info("  Offline RAG Evaluation Report — round %s", run_tag)
    logger.info("  Completed: %d / %d (partial=%d, failed=%d)", len(completed), len(results), len(partial), len(failed))
    logger.info("  ├──────────────────────┬──────────┤")
    logger.info("  │ Faithfulness         │ %.3f    │", avg["faithfulness"])
    logger.info("  │ Answer Relevancy     │ %.3f    │", avg["answer_relevancy"])
    logger.info("  │ Context Precision    │ %.3f    │", avg["context_precision"])
    logger.info("  │ Answer Correctness   │ %.3f    │", avg["answer_correctness"])
    logger.info("  │ Context Recall       │ %.3f    │", avg["context_recall"])
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
    return avg


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
    args = parser.parse_args()

    dataset = load_dataset()
    if args.questions:
        dataset = dataset[: args.questions]

    logger.info("Running evaluation round %s with %d questions...", args.round, len(dataset))

    results = asyncio.run(run_evaluation(dataset))

    avg = _print_report(results, args.round)

    if args.json_report:
        with open(args.json_report, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "round": args.round,
                    "total": len(results),
                    "averages": avg,
                    "failed": [r.error for r in results if r.status == "failed"],
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )
        logger.info("JSON report written to %s", args.json_report)

    # 门禁判定：阈值 0 表示跳过该指标
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
