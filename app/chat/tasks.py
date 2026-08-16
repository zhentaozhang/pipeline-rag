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
    name="chat.extract_user_facts",
    max_retries=2,
    default_retry_delay=30,
)
def task_extract_user_facts(
    self,
    conversation_id: str,
    question: str,
    answer: str,
    exchange_id: int,
    user_key: str | None = None,
) -> dict:
    """异步抽取用户事实/偏好（P3 · Mem0 式）：LLM 结构化抽取 → 向量化 → 去重落库。

    离线执行（不阻塞 SSE 收尾）；任何失败降级为放弃（记忆是锦上添花）。
    """
    from app.common.llm_client import get_chat_client
    from app.config import get_settings

    settings = get_settings()
    if not settings.fact_memory.enabled:
        return {"conversation_id": conversation_id, "status": "skipped_disabled"}

    logger.info("task extract user facts started", conversation_id=conversation_id)

    async def _do() -> dict:
        from app.chat.fact_memory import FactMemoryStore, parse_extraction_response

        client = get_chat_client()
        prompt = (
            "从下面的问答对话中，抽取值得长期记住的用户事实、偏好、身份或目标信息。\n"
            "规则：\n"
            "1. 只抽取『关于用户的长期信息』（如职业、偏好、身份、长期目标）；"
            "不要抽取一次性的查询内容或系统知识。\n"
            "2. 每条事实用一句话陈述，第三人称（如『用户是后端工程师』）。\n"
            "3. 没有可记忆信息时返回空数组。\n"
            "4. 只输出 JSON 数组，格式：[{\"content\": \"...\", \"category\": \"preference|fact|identity|goal\"}]\n\n"
            f"用户问题：{question[:500]}\n系统回答：{answer[:800]}"
        )
        resp = await client.chat.completions.create(
            model=settings.llm.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=500,
        )
        raw = (resp.choices[0].message.content or "") if resp.choices else ""
        facts = parse_extraction_response(raw)
        if not facts:
            return {"conversation_id": conversation_id, "status": "no_facts"}

        store = FactMemoryStore()
        inserted = await store.insert_many(conversation_id, facts, exchange_id, user_key=user_key)
        logger.info(
            "user facts extracted",
            conversation_id=conversation_id,
            extracted=len(facts),
            inserted=inserted,
        )
        return {"conversation_id": conversation_id, "status": "ok", "inserted": inserted}

    try:
        return run_async(_do())  # type: ignore[no-any-return]
    except Exception as e:
        logger.error(
            "user facts extraction failed",
            error=str(e),
            conversation_id=conversation_id,
            exc_info=True,
        )
        raise


@celery_app.task(
    bind=True,
    name="chat.prune_user_facts",
)
def task_prune_user_facts(self) -> dict:
    """全局事实记忆保留期清理（beat 定时，隐私数据生命周期）"""
    from app.config import get_settings

    settings = get_settings()
    if not settings.fact_memory.enabled:
        return {"status": "skipped_disabled"}

    async def _do() -> dict:
        from app.chat.fact_memory import FactMemoryStore

        removed = await FactMemoryStore().prune_expired(settings.fact_memory.retention_days)
        return {"status": "ok", "removed": removed}

    try:
        return run_async(_do())  # type: ignore[no-any-return]
    except Exception as e:
        logger.error("user facts prune failed", error=str(e), exc_info=True)
        raise


@celery_app.task(
    bind=True,
    name="chat.generate_session_title",
)
def task_generate_session_title(self, conversation_id: str, question: str, answer: str) -> dict:
    """异步生成会话标题（B5：从流式请求收尾中移出，避免 LLM 调用阻塞 SSE 收尾）。

    仅当会话标题仍等于原始问题时才生成（避免覆盖用户手动重命名）；
    标题是锦上添花，任何失败都降级为放弃，不重试、不抛异常。
    """
    from app.common.llm_client import get_chat_client
    from app.config import get_settings
    from app.infra.model_fallback import ModelFallbackManager

    logger.info("task generate session title started", conversation_id=conversation_id)

    async def _do():
        from app.db.session import get_session_factory

        sf = get_session_factory()
        if sf is None:
            raise RuntimeError("Session factory not initialized")
        async with sf() as session:
            from app.chat.store import ConversationArchiveStore

            store = ConversationArchiveStore(session)
            current = await store.get_session(conversation_id)
            if not current or current.title != question:
                return None  # 已被用户重命名或会话不存在，跳过

            settings = get_settings()
            if not settings.llm.model:
                return None
            fallback = ModelFallbackManager(client=get_chat_client())
            title_prompt = (
                "基于以下对话内容，生成一个简短精准的会话标题（不超过 30 个字），"
                "直接输出标题，不要多余内容：\n"
                f"用户：{question[:200]}\n助手：{answer[:300]}"
            )
            title_resp = await fallback.chat_completion(
                model=None,
                messages=[{"role": "user", "content": title_prompt}],
                max_tokens=64,
                temperature=0.3,
            )
            title = (
                title_resp.choices[0].message.content.strip().strip('"').strip("'")
            )[:256]
            if title:
                await store.update_session_title(conversation_id, title)
            return title

    try:
        result = run_async(_do())
        logger.info("task generate session title completed", conversation_id=conversation_id, title=result)
        return {"conversation_id": conversation_id, "title": result}
    except Exception as e:
        logger.warning("session title generation failed", error=str(e), exc_info=True)
        return {"conversation_id": conversation_id, "title": None}


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
