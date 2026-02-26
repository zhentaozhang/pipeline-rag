"""
Chat 核心 Schema — Pydantic DTO
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.common.enums import ChatQueryMode, ExecutionMode


class ClarificationQuestion(BaseModel):
    """单个追问问题"""

    question: str
    options: list[str] = Field(default_factory=list)
    user_name: str | None = None


class ClarificationQA(BaseModel):
    """追问 Q&A 对"""

    question: str
    answer: str


class SubQuestion(BaseModel):
    """子问题（Orchestrator 拆分后的最小检索单元）"""

    index: int
    text: str  # 改写/补全后的子问题文本
    original: str = ""  # 原始问题（拆分前）
    tenant_id: str = "default"  # 租户ID隔离
    scope_code: str | None = None  # 关联知识域
    doc_ids: list[str] = Field(default_factory=list)  # 路由锁定的文档
    # 额外节级多维过滤参数
    structure_node_id: int | None = None
    section_path: str | None = None
    canonical_path: str | None = None
    item_index: int | None = None
    # 文档级过滤提示
    document_name_hints: list[str] = Field(default_factory=list)
    business_category_hints: list[str] = Field(default_factory=list)
    document_tag_hints: list[str] = Field(default_factory=list)
    year_hints: list[str] = Field(default_factory=list)
    section_path_hints: list[str] = Field(default_factory=list)
    # 查询增强字段
    retrieval_query: str = ""
    query_context_hints: list[str] = Field(default_factory=list)


class StructureAnchor(BaseModel):
    """大纲/章节导航锚点"""

    root_section_code: str | None = None  # 根章节编码
    root_section_title: str | None = None  # 根章节标题
    target_section_hint: str | None = None  # 目标章节提示
    structure_node_id: str | None = None
    canonical_path: str | None = None
    section_title: str | None = None  # 兼容旧字段
    scope_mode: str | None = None  # 导航范围模式 (NONE/SOFT/GRAPH/GRAPH_UNRESOLVED)

    @property
    def is_empty(self) -> bool:
        return not any(
            [
                self.root_section_code,
                self.root_section_title,
                self.target_section_hint,
                self.structure_node_id,
                self.canonical_path,
            ]
        )


class ItemAnchor(BaseModel):
    """条目导航锚点"""

    item_index: int | None = None


class DocumentNavigationDecision(BaseModel):
    """图谱导航决策"""

    navigation_action: str | None = None  # DocumentNavigationAction 枚举名
    execution_mode: str | None = None  # ExecutionMode 枚举名
    summary_text: str = ""
    structure_anchor: StructureAnchor | None = None
    item_anchor: ItemAnchor | None = None
    action: str | None = None  # 兼容旧字段
    scope_mode: str | None = None  # NavigationScopeMode 枚举名
    query_context_hints: list[str] = Field(default_factory=list)
    soft_section_hints: list[str] = Field(default_factory=list)


class AnswerHistoryContext(BaseModel):
    """回答历史上下文：历史对话中的问答对，用于减少重复检索和保持话题连贯性"""

    rendered_text: str = ""
    structured_context: str = ""
    recent_context: str = ""
    follow_up_question: bool = False
    total_budget: int = 0
    recent_budget: int = 0
    structured_budget: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.rendered_text.strip()


class HistoryPlanningContext(BaseModel):
    """检索历史规划上下文：目标、已确认事实、待跟进问题、检索提示"""

    goals: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)
    retrieval_hints: list[str] = Field(default_factory=list)


class StreamLaunchPlan(BaseModel):
    """启动计划"""

    question: str
    conversation_id: str
    chat_mode: ChatQueryMode
    selected_document_id: int | None = None
    selected_document_name: str | None = None
    selected_task_id: int | None = None
    lease_key: str | None = None
    lease_owner_token: str | None = None
    current_date: str = ""
    current_date_text: str = ""


class AggregationStyle(StrEnum):
    """多源合并策略"""

    SYNTHESIZE = "synthesize"  # LLM 综合多源回答
    CONCATENATE = "concatenate"  # 简单拼接


class SubPlan(BaseModel):
    """子执行计划（多 Agent 场景下的单个 Worker 计划）"""

    id: str
    mode: ExecutionMode
    question: str
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)  # 依赖的 SubPlan id
    doc_ids: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    navigation_decision: DocumentNavigationDecision | None = None

    # ── 审核追踪 ────────────────────────────────────────
    review_status: str | None = None  # "approved"|"rejected"
    review_feedback: str | None = None


class ExecutionPlan(BaseModel):
    """
    Pre-Orchestrator 输出的执行计划
    执行计划
    """

    mode: ExecutionMode
    tenant_id: str = "default"
    original_question: str
    rewritten_question: str  # 意图补全后的完整问题
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    clarification_hint: str | None = None  # 歧义时的追问内容
    is_time_sensitive: bool = False  # 是否包含时间敏感查询
    context_summary: str = ""  # 当前轮记忆上下文摘要
    clarification_reply: str = ""
    refusal_reply: str | None = None
    clarification_options: list[str] = Field(default_factory=list)
    selected_document_id: str | None = None  # 选中的主文档（路由结果）
    navigation_decision: DocumentNavigationDecision | None = None  # 导航决策（对应图谱模式）

    # ── 补齐字段 ──────────────────────────────────────────────────────────
    chat_mode: ChatQueryMode | None = None
    agent_question: str | None = None
    rewrite_sub_questions: list[str] = Field(default_factory=list)
    retrieval_question: str | None = None
    retrieval_sub_questions: list[str] = Field(default_factory=list)
    history_summary: str = ""
    long_term_summary: str = ""
    history_planning_context: HistoryPlanningContext | None = None
    answer_history_context: AnswerHistoryContext | None = None
    current_date: str = ""
    current_date_text: str = ""
    requires_fresh_search: bool = False
    requires_current_date_anchoring: bool = False

    # ── 多 Agent 并行执行 ────────────────────────────────────────────
    supervisor_mode: bool = False
    sub_plans: list[SubPlan] = Field(default_factory=list)
    aggregation_style: str = AggregationStyle.SYNTHESIZE
    selected_document_name: str | None = None
    selected_task_id: str | None = None
    retrieval_document_ids: list[str] = Field(default_factory=list)
    retrieval_task_ids: list[str] = Field(default_factory=list)
    clarification_reason: str | None = None
    no_evidence_reply: str | None = None
    recent_history_transcript: str = ""
    answer_recent_transcript: str = ""

    # ── 回答质量审核 ─────────────────────────────────────────────────
    review_round: int = 0

    # ── 压缩字段 ───────────────────────────────────────────────────
    history_compression_applied: bool = False
    history_covered_exchange_id: int | None = None
    history_covered_exchange_count: int | None = None
    history_compression_count: int | None = None


class Evidence(BaseModel):
    """单条检索证据（chunk 粒度）"""

    chunk_id: str
    doc_id: str
    title: str
    content: str
    source_type: str = "document"  # document | web
    score: float = 0.0  # 融合后最终得分
    reference_id: int | None = None  # [1][2] 引用编号，由 ReferenceMapper 分配
    url: str | None = None  # 网页引用时的 URL
    section_title: str | None = None

    # 溯源与打分 Metadata
    original_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float = 0.0
    channel: str = ""  # vector | keyword | hybrid
    chunk_no: int | None = None

    # Rerank 元数据
    rerank_model: str | None = None
    rerank_query: str | None = None
    rerank_duration_ms: int | None = None
    rerank_original_index: int | None = None

    # Gate & Final Selection 诊断信息
    gate_passed: bool = True
    is_selected: bool = False
    final_rank: int | None = None
    selection_reason: str = ""


class SubQuestionEvidence(BaseModel):
    """单个子问题对应的证据集合"""

    sub_question: SubQuestion
    evidences: list[Evidence] = Field(default_factory=list)
    channel_trace: dict[str, Any] = Field(default_factory=dict)  # 检索通道诊断信息
    fused_candidate_count: int | None = None  # 融合后候选数
    parent_candidate_count: int | None = None  # 父块提升后候选数
    reranked_candidate_count: int | None = None  # 重排后候选数


class SearchReference(BaseModel):
    """引用去重条目"""

    reference_id: str = ""
    source_type: str = "document"
    title: str = ""
    url: str | None = None
    snippet: str = ""
    document_id: int | None = None
    document_name: str = ""
    chunk_id: int | None = None
    parent_block_id: int | None = None
    parent_block_no: int | None = None
    chunk_no: int | None = None
    section_path: str = ""
    structure_node_id: int | None = None
    structure_node_type: int | None = None
    canonical_path: str = ""
    item_index: int | None = None
    score: float = 0.0
    sub_question_index: int | None = None
    sub_question: str = ""
    channel: str = ""
    tool_name: str = ""
    knowledge_scope_code: str = ""
    knowledge_scope_name: str = ""

    def unique_key(self) -> str:
        """去重键：parentBlockId > chunkId > url > sourceType+title+snippet"""
        if self.parent_block_id is not None:
            return f"PARENT:{self.parent_block_id}"
        if self.chunk_id is not None:
            return f"DOCUMENT:{self.chunk_id}"
        if self.url:
            return f"WEB:{self.url}"
        return f"{self.source_type}:{self.title}:{self.snippet}"


class WorkerResult(BaseModel):
    """单个 Worker 执行结果"""

    sub_plan_id: str
    mode: ExecutionMode
    text: str = ""
    references: list[dict[str, Any]] = Field(default_factory=list)
    thinking_steps: list[str] = Field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptAssemblyResult(BaseModel):
    """Prompt 组装结果"""

    system_prompt: str
    user_prompt: str
    total_budget: int = 0  # totalEvidenceMaxChars
    per_sub_question_budget: int = 0  # perSubQuestionEvidenceMaxChars
    rendered_reference_count: int = 0
    omitted_reference_count: int = 0
    rendered_reference_details: list[str] = Field(default_factory=list)
    omitted_reference_details: list[str] = Field(default_factory=list)


class ConversationSessionListVo(BaseModel):
    id: int
    conversation_id: str
    title: str
    updated_at: str | None = None


class ConversationStopVo(BaseModel):
    conversation_id: str
    stopped: bool


class DocumentUploadVo(BaseModel):
    doc_id: str
    task_id: str
    document_name: str
    parse_status: str | None = None
    strategy_status: str | None = None
    index_status: str | None = None
    content: Any = None
