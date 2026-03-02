"""Stage 4/11 — 运行前校验

包括：RAG 是否启用、DOCUMENT 模式是否提供了文档 ID。
"""

from __future__ import annotations

from app.chat.schema import ExecutionPlan
from app.common.enums import ChatQueryMode
from app.common.pipeline import Stage, StageResult, StageSignal
from app.config import get_settings
from app.orchestrator.context import PrepareContext


class ValidationStage(Stage[PrepareContext, "ExecutionPlan"]):

    async def process(self, ctx: PrepareContext) -> StageResult[PrepareContext, ExecutionPlan]:
        settings = get_settings()
        if not settings.rag.enabled:
            raise RuntimeError("当前文档问答模式未启用，请先开启聊天侧 RAG 编排")

        if (
            ctx.chat_mode == ChatQueryMode.DOCUMENT
            and not ctx.original_doc_ids
            and not ctx.original_selected_document_id
        ):
            raise ValueError("当前文档问答模式缺少有效的文档范围")

        return StageResult(signal=StageSignal.CONTINUE, context=ctx)
