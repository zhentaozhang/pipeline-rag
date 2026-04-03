from pydantic import Field

from app.api.schemas.response import CamelModel

# ── 文档管理 VOs ──────────────────────────────────────────────────────────


class DocumentVO(CamelModel):
    """文档视图对象"""

    document_id: str = Field(..., alias="documentId")
    document_name: str = ""
    original_file_name: str = ""
    file_type: int | None = None
    file_type_name: str | None = None
    file_size: int | None = None
    char_count: int | None = None
    token_count: int | None = None
    parse_status: int | None = None
    parse_status_name: str | None = None
    strategy_status: int | None = None
    strategy_status_name: str | None = None
    index_status: int | None = None
    index_status_name: str | None = None
    parse_error_msg: str | None = None
    knowledge_scope_code: str | None = None
    knowledge_scope_name: str | None = None
    business_category: str | None = None
    document_tags: str | None = None
    current_plan_id: int | None = None
    last_index_task_id: str | None = None
    latest_task_id: str | None = None
    latest_task_type: int | None = None
    latest_task_type_name: str | None = None
    latest_task_status: int | None = None
    latest_task_status_name: str | None = None
    edit_time: str | None = None
    status: int | None = None

    @property
    def title(self) -> str:
        return self.document_name

    @property
    def file_name(self) -> str:
        return self.original_file_name

    @property
    def created_at(self) -> str | None:
        return self.edit_time


class DocumentPageResponse(CamelModel):
    records: list[DocumentVO] = Field(default_factory=list)
    total: int = 0
    page_no: int = 1
    page_size: int = 20


class DocumentPageRequest(CamelModel):
    """文档分页查询请求体"""

    page_no: int = 1
    page_size: int = 20
    scope_code: str | None = None
    keyword: str | None = None


# ── 知识域/主题 VOs ──────────────────────────────────────────────────────


class KnowledgeScopeVO(CamelModel):
    """知识域视图对象"""

    scope_code: str
    scope_name: str
    description: str | None = None
    parent_scope_code: str | None = None
    sort_order: int | None = None
    aliases: str | None = None
    examples: str | None = None


class KnowledgeScopeSaveRequest(CamelModel):
    """知识域保存请求（完整字段对齐）"""

    scope_code: str
    scope_name: str
    description: str = ""
    parent_scope_code: str | None = None
    aliases: str | None = None
    examples: str | None = None
    sort_order: str | None = None


class KnowledgeTopicVO(CamelModel):
    """知识主题视图对象"""

    topic_code: str
    topic_name: str
    scope_code: str | None = None
    description: str | None = None
    aliases: str | None = None
    examples: str | None = None
    answer_shape: str | None = None
    execution_preference: str | None = None
    sort_order: int | None = None


class KnowledgeTopicSaveRequest(CamelModel):
    """知识主题保存请求（完整字段对齐）"""

    scope_code: str
    topic_code: str
    topic_name: str
    description: str | None = None
    aliases: str | None = None
    examples: str | None = None
    answer_shape: str | None = None
    execution_preference: str | None = None
    sort_order: str | None = None


# ── 主题文档关联 VOs ─────────────────────────────────────────────────────


class TopicDocumentVO(CamelModel):
    """知识主题文档关联视图对象"""

    topic_code: str | None = None
    document_id: str | None = None
    doc_id: str | None = None
    title: str | None = None
    document_name: str | None = None
    relation_score: float | None = None
    relation_source: str | None = None
    reason: str | None = None
    knowledge_scope_code: str | None = None
    knowledge_scope_name: str | None = None
    business_category: str | None = None
    document_tags: str | None = None


class TopicDocumentSaveRequest(CamelModel):
    """主题-文档关系保存"""

    topic_code: str = Field(..., alias="topicCode")
    document_id: str = Field(..., alias="documentId")
    relation_score: float = Field(default=1.0, alias="relationScore")
    relation_source: str = Field(default="manual", alias="relationSource")
    reason: str = Field(default="", alias="reason")
    operator_id: str | None = Field(default=None, alias="operatorId")


# ── 策略管理 VOs ─────────────────────────────────────────────────────────


class StrategyConfirmRequest(CamelModel):
    """文档策略确认"""

    document_id: str = Field(..., alias="documentId")
    base_plan_id: str = Field(..., alias="basePlanId")
    adjust_note: str | None = Field(default=None, alias="adjustNote")
    operator_id: str | None = Field(default=None, alias="operatorId")
    parent_steps: list[dict] = Field(default_factory=list, alias="parentSteps")
    child_steps: list[dict] = Field(default_factory=list, alias="childSteps")


class ProfileBatchRegenerateRequest(CamelModel):
    document_ids: list[str]


class StrategyPlanStepVO(CamelModel):
    plan_step_id: str
    step_no: int
    strategy_type: int
    strategy_role: int
    strategy_name: str | None = None
    strategy_role_name: str | None = None
    recommend_reason: str | None = None


class StrategyPipelineVO(CamelModel):
    """流水线视图对象"""

    steps: list[StrategyPlanStepVO] = Field(default_factory=list)


class StrategyPlanVO(CamelModel):
    plan_id: str
    plan_status: int
    recommend_reason: str | None = None
    parent_pipeline: StrategyPipelineVO | None = None
    child_pipeline: StrategyPipelineVO | None = None


class StrategyPlanResponse(CamelModel):
    plan_ready: bool = True
    document_id: str | None = None
    parse_status: str | None = None
    plan: StrategyPlanVO | None = None


# ── 文档画像 VOs ─────────────────────────────────────────────────────────


class DocumentProfileVO(CamelModel):
    """文档画像视图对象"""

    document_summary: str | None = None
    core_topics: str | None = None
    example_questions: str | None = None
    profile_status: int | None = None
    document_type: str | None = None
    profile_source: str | None = None
    supports_graph_outline: str | None = None
    supports_item_lookup: str | None = None
    supports_graph_assist: str | None = None


# ── 文档切片 VOs ─────────────────────────────────────────────────────────


class DocumentChunkVO(CamelModel):
    """切片视图对象"""

    chunk_id: str
    doc_id: str | None = None
    chunk_no: int | None = None
    source_type: int | None = None
    source_type_name: str | None = None
    section_path: str | None = None
    chunk_text: str | None = None
    char_count: int | None = None
    token_count: int | None = None
    vector_status: int | None = None
    vector_status_name: str | None = None
    parent_block_id: int | None = None
    parent_block_no: int | None = None
    parent_child_count: int | None = None
    parent_start_chunk_no: int | None = None
    parent_end_chunk_no: int | None = None


class DocumentChunkPageResponse(CamelModel):
    records: list[DocumentChunkVO] = Field(default_factory=list)
    total: int = 0
    page_no: int = 1
    page_size: int = 20
    task_id: str | None = None


class ParentBlockVO(CamelModel):
    """父块视图对象"""

    parent_block_id: int | None = None
    parent_block_no: int | None = None
    start_chunk_no: int | None = None
    end_chunk_no: int | None = None
    section_path: str | None = None
    char_count: int | None = None
    token_count: int | None = None
    parent_text: str | None = None
    child_count: int | None = None


class DocumentChunkDetailVO(CamelModel):
    """切片详情视图对象（含 chunk / parentBlock / siblingChunks 三层结构）"""

    chunk: DocumentChunkVO | None = None
    parent_block: ParentBlockVO | None = None
    sibling_chunks: list[DocumentChunkVO] = Field(default_factory=list)


# ── 任务日志 VOs ─────────────────────────────────────────────────────────


class TaskLogVO(CamelModel):
    """任务日志视图对象"""

    id: str
    task_id: str
    stage_type: int | None = None
    stage_type_name: str | None = None
    event_type: int | None = None
    event_type_name: str | None = None
    content: str | None = None
    detail_json: str | None = None
    create_time: str | None = None


# ── 可观测性 VOs ─────────────────────────────────────────────────────────


class ChannelExecutionVO(CamelModel):
    sub_question: str = ""
    channel: str = ""
    recalled_count: int = 0
    accepted_count: int = 0


class RetrievalResultVO(CamelModel):
    sub_question: str = ""
    phase: str = ""
    chunk_id: str = ""
    score: float = 0.0
    rank: int = 0


class ExchangeTraceVO(CamelModel):
    conversation_id: str = ""
    exchange_id: int = 0
    channel_executions: list[ChannelExecutionVO] = Field(default_factory=list)
    retrieval_results: list[RetrievalResultVO] = Field(default_factory=list)


class RouteTraceItemVO(CamelModel):
    conversation_id: str = ""
    exchange_id: int | None = None
    question: str = ""
    rewrite_question: str = ""
    mode: str = ""
    confidence: float = 0.0
    route_status: str = ""
    created_at: str | None = None


class RouteTracePageResponse(CamelModel):
    records: list[RouteTraceItemVO] = Field(default_factory=list)
    total: int = 0
    page_no: int = 1
    page_size: int = 20
    total_pages: int = 0
