/**
 * API 领域类型 barrel（与后端 VO 对齐，CamelModel 输出 camelCase）
 * 专项：消除前端 no-explicit-any（体检 A7/B8）
 *
 * 实现已按域拆到同目录：./common ./chat ./manage ./knowledge ./evaluation ./metrics ./trace
 * 本文件只做 re-export，保证原有 import 路径（'../types/api'）不变。
 */

export type { ApiEnvelope } from './common';

export type {
  ChatSession,
  SessionPageResponse,
  ExchangeReference,
  ExchangeItem,
  SessionDetail,
  DocumentOption,
  StreamEvent,
  SessionListQuery,
  StreamRequest,
  ChannelExecution,
  RetrievalResult,
} from './chat';

export type {
  ManageDocument,
  DocumentPageResponse,
  StrategyPlanStep,
  StrategyPipeline,
  StrategyPlan,
  StrategyPlanResponse,
} from './manage';

export type {
  KnowledgeScope,
  KnowledgeTopic,
  TopicDocument,
  DocumentProfile,
  RouteTrace,
  RouteTracePage,
} from './knowledge';

export type { EvaluationDataset } from './evaluation';

export type { MetricsData, MetricsOverview, BenchmarkItem } from './metrics';

export type {
  TraceListItem,
  TracePageResponse,
  TraceSpan,
  TraceScore,
  TraceDetail,
} from './trace';
