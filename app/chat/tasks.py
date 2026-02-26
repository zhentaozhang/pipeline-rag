"""
Celery 异步任务 — 对话多轮记忆提炼 + RAG 质量评估
"""

import structlog

from app.celery_app import celery_app, run_async

logger = structlog.get_logger(__name__)


@celery_app.task(
    bind=True,
    name="chat.compress_memory",
    max_retries=3,
    default_retry_delay=10,
)
def task_compress_conversation_memory(
    self, conversation_id: str, latest_exchange_id: int | None = None
) -> dict:
    """异步提炼历史会话记录"""
    from app.chat.memory_compressor import ConversationMemoryCompressor

    logger.info(
        "task compress memory started", conversation_id=conversation_id, task_id=self.request.id
    )

    async def _do_compress():
        from app.db.session import get_session_factory

        sf = get_session_factory()
        if sf is None:
            raise RuntimeError("Session factory not initialized")
        async with sf() as session:
            compressor = ConversationMemoryCompressor()
            await compressor.compress_history(
                conversation_id, session, known_exchange_id=latest_exchange_id
            )

    try:
        run_async(_do_compress())
        return {"conversation_id": conversation_id, "status": "success"}
    except Exception as e:
        logger.error(
            "memory compression task failed",
            error=str(e),
            conversation_id=conversation_id,
            exc_info=True,
        )
        raise





@celery_app.task(
    bind=True,
    name="chat.evaluate_dataset_item",
    max_retries=2,
    default_retry_delay=5,
)
def task_evaluate_dataset_item(self, dataset_id: int) -> dict:
    """
    异步评估 Golden Dataset 数据项（回归测试环节）。
    这是一个 Mock 实现，模拟重放问题并对生成答案与 Ground Truth 进行相似度/正确性评分。
    真实场景下将调用 LLM 重新生成 answer 和 contexts，并调用 ragas 计算包含 Answer Correctness 在内的指标。
    """
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.db.models.rag_observability import RagEvaluationDataset

    logger.info(
        "task evaluate dataset item started", dataset_id=dataset_id, task_id=self.request.id
    )

    async def _do_eval():
        from app.db.session import get_session_factory

        sf = get_session_factory()
        if sf is None:
            raise RuntimeError("Session factory not initialized")

        async with sf() as session:
            stmt = select(RagEvaluationDataset).where(RagEvaluationDataset.id == dataset_id)
            dataset = (await session.execute(stmt)).scalar_one_or_none()
            if not dataset:
                raise ValueError(f"Dataset {dataset_id} not found")

            # 1. 获取评估所需的参数
            import json
            from decimal import Decimal

            from app.rag.evaluation import RAGEvaluationService

            contexts = json.loads(dataset.contexts) if dataset.contexts else []
            eval_svc = RAGEvaluationService()

            # 2. 如果之前没有生成的答案，利用 LLM 根据上下文生成一个临时答案
            generated_answer = dataset.generated_answer
            if not generated_answer:
                context_text = eval_svc._join_contexts(contexts)
                generated_answer = await eval_svc._llm_complete(
                    system="请根据提供的上下文回答用户的问题。如果上下文中没有包含足够的信息，请声明无法完全解答。请保持回答清晰且直接。",
                    user=f"问题：{dataset.question}\n\n上下文：\n{context_text}",
                )
                dataset.generated_answer = generated_answer

            # 3. 调用真实的 RAGEvaluationService
            logger.info("开始执行真实的 Ragas 评估", dataset_id=dataset_id)
            scores = await eval_svc.evaluate_dataset(
                question=dataset.question,
                answer=generated_answer,
                ground_truth=dataset.ground_truth,
                contexts=contexts,
            )

            # 4. 写入真实分数
            dataset.faithfulness_score = (
                Decimal(str(scores.get("faithfulness_score")))
                if scores.get("faithfulness_score") is not None
                else None
            )
            dataset.answer_relevancy_score = (
                Decimal(str(scores.get("answer_relevancy_score")))
                if scores.get("answer_relevancy_score") is not None
                else None
            )
            dataset.context_precision_score = (
                Decimal(str(scores.get("context_precision_score")))
                if scores.get("context_precision_score") is not None
                else None
            )
            dataset.context_recall_score = (
                Decimal(str(scores.get("context_recall_score")))
                if scores.get("context_recall_score") is not None
                else None
            )
            dataset.answer_correctness_score = (
                Decimal(str(scores.get("answer_correctness_score")))
                if scores.get("answer_correctness_score") is not None
                else None
            )

            dataset.status = 2  # 已评估
            dataset.eval_message = "Eval completed successfully via LLM Judge."
            dataset.evaluated_at = datetime.now(UTC)
            await session.commit()

            return {"dataset_id": dataset_id, "scores": scores, "status": "completed"}

    try:
        result = run_async(_do_eval())
        logger.info("task evaluate dataset item completed", result=result)
        return result
    except Exception as e:
        logger.error(
            "evaluate dataset item failed", dataset_id=dataset_id, error=str(e), exc_info=True
        )
        raise
