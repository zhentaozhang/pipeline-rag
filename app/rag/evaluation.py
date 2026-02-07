"""
Legacy RAGEvaluationService.

生产评估已迁移到 app.observability.metrics.pipeline.EvaluationPipeline，
在 RagChatExecutor.execute() 中同步执行（Phase 2）。

此文件仅保留用于：
- 离线 Golden Dataset 回归测试 (task_evaluate_dataset_item)
- 旧 DB 表写入 (conversation_rag_evaluation / rag_evaluation_dataset)
"""

from __future__ import annotations

from typing import Any


class RAGEvaluationService:
    """
    Minimal stub — 仅用于离线回归。

    生产 eval 走新路径：
    EvaluationPipeline.standard().run(question, answer, contexts, tracer=tracer)
    """

    async def evaluate(self, conversation_id: str, exchange_id: int, question: str, answer: str) -> dict[str, Any]:
        return {}

    async def evaluate_dataset(self, **kwargs) -> dict[str, Any]:
        return {}

    async def save_results(self, **kwargs) -> None:
        pass

    async def update_status(self, **kwargs) -> None:
        pass
