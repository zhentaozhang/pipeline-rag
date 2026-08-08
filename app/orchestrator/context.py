"""
编排器管道上下文 — PrepareContext

统一存储编排器管道中各阶段产生的中间数据，替代：
- 原 _prepare_impl 中的 10+ 分散局部变量
- PrepareRequest 上的 _routed_*/_top_* 下划线隐式副作用
- PlanBuilder 方法间的 17 参数传递
"""

from dataclasses import dataclass, field
from datetime import date

from app.chat.memory import MemoryContext
from app.chat.schema import AnswerHistoryContext, DocumentNavigationDecision, HistoryPlanningContext
from app.common.enums import ChatQueryMode, ExecutionMode


@dataclass
class PrepareContext:
    """编排器管道的统一上下文"""

    # ── 原始输入 ────────────────────────────────────────────────────
    question: str
    conversation_id: str
    memory_ctx: MemoryContext
    chat_mode: ChatQueryMode
    tenant_id: str = "default"
    exchange_id: int = 0

    # ── 原始文档指定（PrepareRequest 直传）──────────────────────────
    original_doc_ids: list[str] | None = None
    original_selected_document_id: str | None = None
    original_selected_document_name: str | None = None
    original_selected_task_id: str | None = None

    # ── 时间感知（TimeSensitivityStage 填充）────────────────────────
    current_date: date = field(default_factory=date.today)
    current_date_text: str = ""
    requires_current_date_anchoring: bool = False
    requires_fresh_search: bool = False
    is_time_sensitive: bool = False

    # ── 历史上下文（HistoryBuildingStage 填充）──────────────────────
    history_planning_ctx: HistoryPlanningContext = field(default_factory=HistoryPlanningContext)
    history_summary: str = ""
    answer_history_ctx: AnswerHistoryContext = field(default_factory=AnswerHistoryContext)

    # ── 改写结果（QueryRewriteStage 填充）───────────────────────────
    rewritten_question: str = ""
    rewrite_sub_questions: list[str] = field(default_factory=list)

    # ── 路由结果（KnowledgeRoutingStage 填充）───────────────────────
    routed_document_id: str | None = None
    routed_document_name: str = ""
    routed_task_id: str | None = None
    top_doc_ids: list[str] = field(default_factory=list)
    top_task_ids: list[str] = field(default_factory=list)

    # ── 导航结果（NavigationAnalysisStage 填充）─────────────────────
    navigation_decision: DocumentNavigationDecision | None = None
    execution_mode: ExecutionMode = ExecutionMode.RETRIEVAL
    retrieval_question: str = ""
    retrieval_sub_questions: list[str] = field(default_factory=list)
