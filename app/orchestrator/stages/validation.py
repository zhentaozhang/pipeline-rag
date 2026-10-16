"""Stage 4/9 — 运行前校验

由管道 ``.when()`` 守卫排除 OPEN_CHAT（闲聊不依赖 RAG，也不涉及文档范围）。

包括：
- RAG 是否启用：属服务端配置缺失，返回 TERMINATE 的可读提示而非抛异常，
  使终止一律走管道契约，避免异常穿出 ``prepare()`` 把整轮标记为 FAILED。
- DOCUMENT 模式是否提供了文档 ID：属调用方参数错误，仍以异常暴露。
"""

from __future__ import annotations

import structlog

from app.chat.schema import ExecutionPlan
from app.common.enums import ChatQueryMode
from app.common.pipeline import Stage, StageResult, StageSignal
from app.config import get_settings
from app.orchestrator.context import PrepareContext
from app.orchestrator.plan_builder import PlanBuilder

logger = structlog.get_logger(__name__)

RAG_DISABLED_REPLY = (
    "当前服务未启用文档问答能力（RAG_ENABLED=false），无法基于知识库作答。"
    "请切换到「开放式提问」模式，或联系管理员开启文档问答。"
)


class ValidationStage(Stage[PrepareContext, "ExecutionPlan"]):
    async def process(self, ctx: PrepareContext) -> StageResult[PrepareContext, ExecutionPlan]:
        settings = get_settings()
        if not settings.rag.enabled:
            # 配置缺失是服务端问题，但不该以异常击穿编排器：管道契约要求终止走 TERMINATE。
            # 保留 ERROR 日志与降级指标，运维仍能在监控中发现（而非静默降级）。
            logger.error(
                "rag_disabled_short_circuit",
                chat_mode=ctx.chat_mode.name,
                conversation_id=ctx.conversation_id,
            )
            from app.observability.metrics import DEGRADATION_TOTAL

            DEGRADATION_TOTAL.labels(reason="rag_disabled").inc()
            return StageResult(
                signal=StageSignal.TERMINATE,
                plan=PlanBuilder.build_unavailable_plan(ctx, RAG_DISABLED_REPLY),
            )

        if (
            ctx.chat_mode == ChatQueryMode.DOCUMENT
            and not ctx.original_doc_ids
            and not ctx.original_selected_document_id
        ):
            raise ValueError("当前文档问答模式缺少有效的文档范围")

        return StageResult(signal=StageSignal.CONTINUE, context=ctx)
