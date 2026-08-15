"""
EvaluationPipeline — orchestrates all metrics for a single exchange.

Runs metrics in parallel and writes results via Tracer.attach_score().
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.observability.metrics.base import Metric, MetricResult


class EvaluationPipeline:
    def __init__(self, metrics: list[Metric]) -> None:
        self._metrics = metrics

    async def run(
        self,
        *,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None = None,
        tracer: Any = None,
        timeout: int | None = None,
    ) -> list[MetricResult]:
        async def _run_one(metric: Metric) -> MetricResult:
            result = await metric.ascore(
                question=question,
                answer=answer,
                contexts=contexts,
                ground_truth=ground_truth,
            )
            if tracer is not None:
                tracer.attach_score(result.metric_name, result.value, reason=result.reason)
            return result

        coro = asyncio.gather(
            *[_run_one(m) for m in self._metrics],
            return_exceptions=True,
        )
        results = await asyncio.wait_for(coro, timeout=timeout) if timeout else await coro

        final: list[MetricResult] = []
        for r in results:
            if isinstance(r, BaseException):
                final.append(MetricResult(metric_name="error", value=0.0, reason=str(r)))
            else:
                final.append(r)
        return final

    @classmethod
    def standard(cls) -> EvaluationPipeline:
        from app.common.llm_client import get_eval_client
        from app.config import get_settings
        from app.observability.metrics.answer_relevancy import AnswerRelevancyMetric
        from app.observability.metrics.context_precision import ContextPrecisionMetric
        from app.observability.metrics.faithfulness import FaithfulnessMetric

        settings = get_settings()
        model = settings.rag.evaluation_model or settings.llm.model
        eval_llm = get_eval_client()

        return cls(
            [
                FaithfulnessMetric(eval_llm=eval_llm, model=model),
                AnswerRelevancyMetric(eval_llm=eval_llm, model=model),
                ContextPrecisionMetric(eval_llm=eval_llm, model=model),
            ]
        )

    @classmethod
    def with_ground_truth(cls) -> EvaluationPipeline:
        from app.common.llm_client import get_eval_client
        from app.config import get_settings
        from app.observability.metrics.answer_correctness import AnswerCorrectnessMetric
        from app.observability.metrics.answer_relevancy import AnswerRelevancyMetric
        from app.observability.metrics.context_precision import ContextPrecisionMetric
        from app.observability.metrics.context_recall import ContextRecallMetric
        from app.observability.metrics.faithfulness import FaithfulnessMetric

        settings = get_settings()
        model = settings.rag.evaluation_model or settings.llm.model
        eval_llm = get_eval_client()

        return cls(
            [
                FaithfulnessMetric(eval_llm=eval_llm, model=model),
                AnswerRelevancyMetric(eval_llm=eval_llm, model=model),
                ContextPrecisionMetric(eval_llm=eval_llm, model=model),
                ContextRecallMetric(eval_llm=eval_llm, model=model),
                AnswerCorrectnessMetric(eval_llm=eval_llm, model=model),
            ]
        )
