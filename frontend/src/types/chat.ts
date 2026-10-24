/**
 * Chat 域 API 类型：会话 / 流式事件 / 引用 / 文档选项 / RAG 通道展示
 * 与后端 VO 对齐，CamelModel 输出 camelCase
 */

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
  chunk_id?: string;
  content?: string;
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
