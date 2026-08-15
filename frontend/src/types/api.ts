/**
 * API 领域类型定义（与后端 VO 对齐，CamelModel 输出 camelCase）
 * 专项：消除前端 no-explicit-any（体检 A7/B8）
 */

/** 后端统一响应包裹：{ code, data, message } */
export interface ApiEnvelope<T = unknown> {
  code: number | string;
  message: string | null;
  data: T;
}

// ── Chat 域 ─────────────────────────────────────────────────────────────

/** 会话列表项（ConversationSessionVO） */
export interface ChatSession {
  id: number;
  conversationId: string;
  title: string;
  createdAt: string | null;
  chatMode: string;
  exchangeCount: number;
  memorySummary: string;
  running: boolean;
  checkpointCount: number;
  messageCount: number;
  latestUserMessage: string;
  latestAssistantMessage: string;
  latestExchangeId: string | null;
  latestTurnStatus: string;
  latestTurnErrorMessage: string;
  selectedDocumentId: string;
  selectedDocumentName: string;
  updatedAt: string | null;
  isPinned?: boolean;
}

/** 会话列表分页响应（SessionPageResponse，后端别名 sessions → records） */
export interface SessionPageResponse {
  sessions: ChatSession[];
  total: number;
  pageNo: number | string;
  pageSize: number | string;
  totalPages: number | string;
}

/** 引用条目（reference 事件 / exchange.references 元素） */
export interface ExchangeReference {
  id?: string | number;
  title?: string;
  url?: string;
  name?: string;
  section_title?: string;
  source_type?: string;
  doc_id?: string;
  [key: string]: unknown;
}

/** 会话内单轮消息（ExchangeVO + 前端展示字段） */
export interface ExchangeItem {
  exchangeId: string;
  question: string;
  answer: string;
  thinkingSteps: string[];
  references: ExchangeReference[];
  recommendations: string[];
  status: string;
  errorMessage: string;
  createdAt: string | null;
  updatedAt: string | null;
  createTime?: string | null;
  editTime?: string | null;
  tokensUsed?: number | null;
  totalResponseTimeMs?: number | null;
  executionMode?: string;
  debugTrace?: Record<string, unknown> | null;
}

/** 会话详情（SessionDetailVO） */
export interface SessionDetail extends ChatSession {
  exchanges: ExchangeItem[];
}

/** 可选文档（/api/chat/document/options） */
export interface DocumentOption {
  documentId: string;
  documentName: string;
  [key: string]: unknown;
}

/** SSE 流事件 */
export interface StreamEvent {
  type: string;
  content: unknown;
  timestamp?: string;
  conversationId?: string;
  exchangeId?: number;
  count?: number;
}

/** 会话列表查询参数 */
export interface SessionListQuery {
  keyword?: string;
  chatMode?: string;
  turnStatus?: string;
  pageNo?: string | number;
  pageSize?: string | number;
}

/** 流式对话请求体 */
export interface StreamRequest {
  question: string;
  conversationId?: string | null;
  chatMode?: string;
  docIds?: string[];
  selectedDocumentId?: string | null;
}

// ── Manage 域 ───────────────────────────────────────────────────────────

/** 文档视图（DocumentVO） */
export interface ManageDocument {
  documentId: string;
  documentName: string;
  originalFileName: string;
  fileType: number | null;
  fileTypeName: string | null;
  fileSize: number | null;
  charCount: number | null;
  tokenCount: number | null;
  parseStatus: number | null;
  parseStatusName: string | null;
  strategyStatus: number | null;
  strategyStatusName: string | null;
  indexStatus: number | null;
  indexStatusName: string | null;
  parseErrorMsg: string | null;
  knowledgeScopeCode: string | null;
  knowledgeScopeName: string | null;
  businessCategory: string | null;
  documentTags: string | null;
  currentPlanId: number | null;
  lastIndexTaskId: string | null;
  latestTaskId: string | null;
  latestTaskType: number | null;
  latestTaskTypeName: string | null;
  latestTaskStatus: number | null;
  latestTaskStatusName: string | null;
  editTime: string | null;
  status: number | null;
}

/** 文档分页响应（DocumentPageResponse） */
export interface DocumentPageResponse {
  records: ManageDocument[];
  total: number;
  pageNo: number;
  pageSize: number;
}

/** 知识域（KnowledgeScopeVO） */
export interface KnowledgeScope {
  scopeCode: string;
  scopeName: string;
  description?: string | null;
  parentScopeCode?: string | null;
  sortOrder?: number | null;
  aliases?: string | null;
  examples?: string | null;
}

/** 知识主题（KnowledgeTopicVO） */
export interface KnowledgeTopic {
  topicCode: string;
  topicName: string;
  scopeCode?: string | null;
  description?: string | null;
  aliases?: string | null;
  examples?: string | null;
  answerShape?: string | null;
  executionPreference?: string | null;
  sortOrder?: number | null;
}

/** 主题-文档关系（TopicDocumentVO） */
export interface TopicDocument {
  topicCode?: string | null;
  documentId?: string | null;
  docId?: string | null;
  title?: string | null;
  documentName?: string | null;
  relationScore?: number | null;
  relationSource?: string | null;
  reason?: string | null;
  knowledgeScopeCode?: string | null;
  knowledgeScopeName?: string | null;
  businessCategory?: string | null;
  documentTags?: string | null;
  createTime?: string | null;
}

/** 策略步骤（StrategyPlanStepVO） */
export interface StrategyPlanStep {
  planStepId: string;
  stepNo: number;
  strategyType: number;
  strategyRole: number;
  strategyName?: string | null;
  strategyRoleName?: string | null;
  recommendReason?: string | null;
}

/** 策略流水线（StrategyPipelineVO） */
export interface StrategyPipeline {
  steps: StrategyPlanStep[];
}

/** 策略方案（StrategyPlanVO） */
export interface StrategyPlan {
  planId: string;
  planStatus: number;
  recommendReason?: string | null;
  parentPipeline?: StrategyPipeline | null;
  childPipeline?: StrategyPipeline | null;
}

/** 策略方案响应（StrategyPlanResponse） */
export interface StrategyPlanResponse {
  planReady: boolean;
  documentId?: string | null;
  parseStatus?: string | null;
  plan?: StrategyPlan | null;
}

/** 知识路由轨迹 */
export interface RouteTrace {
  conversationId?: string;
  exchangeId?: number | string;
  traceId?: string;
  question?: string;
  routeResult?: string;
  confidence?: number | string;
  createdAt?: string;
  mode?: string;
  routeStatus?: string;
  rewriteQuestion?: string;
  [key: string]: unknown;
}

/** 路由轨迹分页响应 */
export interface RouteTracePage {
  records: RouteTrace[];
  total: number;
  pageNo?: string;
  pageSize?: string;
  totalPages?: string;
}

/** 评估数据集项 */
export interface EvaluationDataset {
  id: number;
  question?: string;
  groundTruth?: string;
  status?: number;
  evalMessage?: string | null;
  faithfulnessScore?: number | null;
  answerRelevancyScore?: number | null;
  contextPrecisionScore?: number | null;
  contextRecallScore?: number | null;
  answerCorrectnessScore?: number | null;
  createdAt?: string | null;
  description?: string;
  [key: string]: unknown;
}

/** 文档画像（queryDocumentProfile） */
export interface DocumentProfile {
  documentId?: string;
  documentName?: string;
  contentQualityLevel?: string | number;
  structureLevel?: string | number;
  graphFriendly?: boolean;
  supportsItemLookup?: boolean;
  summary?: string;
  coreTopics?: string;
  [key: string]: unknown;
}

/** RAG 通道执行记录（RAGSankey 展示） */
export interface ChannelExecution {
  channel?: string;
  recalled_count?: number;
  [key: string]: unknown;
}

/** RAG 检索阶段结果（RAGSankey 展示） */
export interface RetrievalResult {
  phase?: string;
  score?: number;
  gate_passed?: boolean;
  [key: string]: unknown;
}

/** 指标面板数据（宽松：后端 metrics 接口字段随版本演进） */
export interface MetricsData {
  [key: string]: unknown;
}

/** 指标面板概览（getMetricsOverview，字段随后端演进） */
export interface MetricsOverview {
  totalExchanges?: number;
  activeConversations?: number;
  avgResponseTimeMs?: number;
  errorRate?: number;
  todayCost?: number;
  totalCost?: number;
  [key: string]: unknown;
}

/** 阶段耗时基准（getBenchmarks 列表项） */
export interface BenchmarkItem {
  stageCode?: string;
  executionMode?: string;
  p50Ms?: number;
  p90Ms?: number;
  p99Ms?: number;
  [key: string]: unknown;
}
