"""
Pre-Orchestrator 主编排器

处理流程（Pipeline 声明式）：
1. HistoryBuildingStage      — 历史上下文构建
2. TimeSensitivityStage      — 时间感知查询检测
3. GuardrailStage            — 企业意图护栏拦截（可短路 → REFUSAL）
4. ValidationStage           — RAG 启停 + DOCUMENT 模式校验
5. OpenChatShortcutStage     — OPEN_CHAT 早期短路（可短路 → REACT_AGENT）
6. IntentClassifyStage       — AUTO_DOCUMENT 意图分类（可短路 → REACT_AGENT）
7. QueryRewriteStage         — LLM 查询改写
8. KnowledgeRoutingStage     — 知识路由（可短路 → CLARIFICATION）
9. NavigationAnalysisStage   — 图谱导航分析
10. FinalPlanBuildingStage   — 构建 ExecutionPlan（终止管道）

Post-pipeline：
- SupervisorService.decompose() — 可选的多 Agent 任务分解
"""

from dataclasses import dataclass, field

import structlog

from app.chat.memory import MemoryContext
from app.chat.schema import ExecutionPlan
from app.common.enums import ChatQueryMode
from app.common.pipeline import Pipeline, PipelineStage
from app.orchestrator.context import PrepareContext
from app.orchestrator.intent_detector import normalize_chat_mode
from app.orchestrator.stages import (
    FinalPlanBuildingStage,
    GuardrailStage,
    HistoryBuildingStage,
    IntentClassifyStage,
    KnowledgeRoutingStage,
    NavigationAnalysisStage,
    OpenChatShortcutStage,
    QueryRewriteStage,
    TimeSensitivityStage,
    ValidationStage,
)
from app.orchestrator.supervisor import SupervisorService

logger = structlog.get_logger(__name__)


@dataclass
class PrepareRequest:
    """编排器输入 DTO（保持向后兼容）"""

    question: str
    conversation_id: str
    memory_ctx: MemoryContext
    doc_ids: list[str] = field(default_factory=list)
    chat_mode: str = "auto"
    selected_task_id: str | None = None
    selected_document_id: str | None = None
    selected_document_name: str | None = None
    exchange_id: int = 0
    tenant_id: str = "default"


async def prepare(
    question: str,
    conversation_id: str,
    memory_ctx: MemoryContext,
    doc_ids: list[str] | None = None,
    chat_mode: str = "auto",
    selected_task_id: str | None = None,
    selected_document_id: str | None = None,
    selected_document_name: str | None = None,
    exchange_id: int = 0,
    tenant_id: str = "default",
) -> ExecutionPlan:
    """编排器入口：将输入参数打包为 PrepareRequest 并执行管道"""
    req = PrepareRequest(
        question=question,
        conversation_id=conversation_id,
        memory_ctx=memory_ctx,
        doc_ids=doc_ids or [],
        chat_mode=chat_mode,
        selected_task_id=selected_task_id,
        selected_document_id=selected_document_id,
        selected_document_name=selected_document_name,
        exchange_id=exchange_id,
        tenant_id=tenant_id,
    )
    return await _prepare_impl(req)


async def _prepare_impl(req: PrepareRequest) -> ExecutionPlan:
    """编排器实现：构建 PrepareContext → 执行 Pipeline → Supervisor 后处理"""
    # ── chatMode 规范化 ────────────────────────────────────────────
    chat_mode: ChatQueryMode
    if req.chat_mode is None:
        raise ValueError("chatMode 不能为空")
    if isinstance(req.chat_mode, str):
        chat_mode = normalize_chat_mode(req.chat_mode)
    else:
        chat_mode = req.chat_mode

    # ── 构建统一上下文 ──────────────────────────────────────────────
    ctx = PrepareContext(
        question=req.question,
        conversation_id=req.conversation_id,
        memory_ctx=req.memory_ctx,
        chat_mode=chat_mode,
        tenant_id=req.tenant_id,
        exchange_id=req.exchange_id,
        original_doc_ids=req.doc_ids,
        original_selected_document_id=req.selected_document_id,
        original_selected_document_name=req.selected_document_name,
        original_selected_task_id=req.selected_task_id,
    )

    # ── 执行管道 ───────────────────────────────────────────────────
    pipeline = _build_orchestrator_pipeline()
    plan = await pipeline.run(ctx)

    # ── Post-pipeline: Supervisor 任务分解（可选）───────────────────
    supervisor = SupervisorService()
    plan = await supervisor.decompose(plan)
    return plan


def _build_orchestrator_pipeline() -> Pipeline[PrepareContext, ExecutionPlan]:
    """编排器管道声明：stage 按序执行，条件跳转由 .when() 声明式控制"""
    return Pipeline(
        stages=[
            PipelineStage(HistoryBuildingStage()),
            PipelineStage(TimeSensitivityStage()),
            PipelineStage(GuardrailStage()),
            PipelineStage(ValidationStage()),
            PipelineStage(OpenChatShortcutStage()).when(
                lambda ctx: ctx.chat_mode == ChatQueryMode.OPEN_CHAT
            ),
            PipelineStage(IntentClassifyStage()).when(
                lambda ctx: ctx.chat_mode == ChatQueryMode.AUTO_DOCUMENT
            ),
            PipelineStage(QueryRewriteStage()),
            PipelineStage(KnowledgeRoutingStage()).when(
                lambda ctx: ctx.chat_mode
                in (ChatQueryMode.AUTO_DOCUMENT, ChatQueryMode.DOCUMENT)
            ),
            PipelineStage(NavigationAnalysisStage()),
            PipelineStage(FinalPlanBuildingStage()),
        ]
    )
