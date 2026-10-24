/**
 * Knowledge 域 API 类型：知识域 / 主题 / 主题-文档关系 / 文档画像 / 路由轨迹
 * 与后端 VO 对齐，CamelModel 输出 camelCase
 */

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
