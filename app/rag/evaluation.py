"""
Legacy RAGEvaluationService Adapter.

生产评估已迁移到 app.observability.metrics.pipeline.EvaluationPipeline。
本类保留作为向后兼容代理，透明委托给 EvaluationPipeline，彻底杜绝返回空字典的静默失效。
"""

from __future__ import annotations

from typing import Any

import structlog

from app.observability.metrics.pipeline import EvaluationPipeline

logger = structlog.get_logger(__name__)


class RAGEvaluationService:
    """向后兼容适配器：透明委托给 EvaluationPipeline（延迟构造，避免实例化时急切创建 client）。"""

    def __init__(self) -> None:
        self._standard_pipeline: EvaluationPipeline | None = None
        self._gt_pipeline: EvaluationPipeline | None = None

    def _get_standard_pipeline(self) -> EvaluationPipeline:
        if self._standard_pipeline is None:
            self._standard_pipeline = EvaluationPipeline.standard()
        return self._standard_pipeline

    def _get_gt_pipeline(self) -> EvaluationPipeline:
        if self._gt_pipeline is None:
            self._gt_pipeline = EvaluationPipeline.with_ground_truth()
        return self._gt_pipeline

    async def evaluate(
        self,
        conversation_id: str = "",
        exchange_id: int = 0,
        question: str = "",
        answer: str = "",
        contexts: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        results = await self._get_standard_pipeline().run(
            question=question,
            answer=answer,
            contexts=contexts or [],
        )
        # 失败指标返回 None（而非 0.0），使上层聚合可将其排除
        return {r.metric_name: (None if r.failed else r.value) for r in results}

    async def evaluate_dataset(
        self,
        question: str = "",
        answer: str = "",
        contexts: list[str] | None = None,
        ground_truth: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        results = await self._get_gt_pipeline().run(
            question=question,
            answer=answer,
            contexts=contexts or [],
            ground_truth=ground_truth,
        )
        # 失败指标返回 None（而非 0.0），使上层聚合可将其排除
        return {r.metric_name: (None if r.failed else r.value) for r in results}

    async def save_results(self, **kwargs: Any) -> None:
        pass

    async def update_status(self, **kwargs: Any) -> None:
        pass
