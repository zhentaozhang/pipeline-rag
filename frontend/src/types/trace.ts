/**
 * Trace 域 API 类型：链路列表 / span / 评估分数 / 详情
 * 与后端 VO 对齐，CamelModel 输出 camelCase
 */

/** Trace 链路列表项（/manage/observe/traces） */
export interface TraceListItem {
  traceId: string;
  conversationId: string;
  exchangeId: number;
  spanCount: number;
  durationMs: number | null;
  status: string;
  outputPreview: string;
  createdAt: string | null;
}

/** Trace 列表分页响应 */
export interface TracePageResponse {
  records: TraceListItem[];
  total: number;
  pageNo: number;
  pageSize: number;
  stats: {
    totalTraces: number;
    todayTraces: number;
    errorTraces: number;
    avgRootDurationMs: number;
  };
}

/** Trace span（详情） */
export interface TraceSpan {
  spanId: string;
  parentSpanId: string | null;
  kind: string;
  name: string;
  status: string;
  startedAt: string | null;
  endedAt: string | null;
  durationMs: number | null;
  input: unknown;
  output: unknown;
}

/** Trace 评估分数（详情） */
export interface TraceScore {
  scoreId: string;
  spanId: string;
  metricName: string;
  value: number | null;
  reason: string | null;
  createdAt: string | null;
}

/** Trace 详情（/manage/observe/traces/:traceId） */
export interface TraceDetail {
  traceId: string;
  conversationId: string;
  exchangeId: number;
  sessionId: string | null;
  rootSpanId: string | null;
  input: unknown;
  output: unknown;
  metadata: unknown;
  tags: unknown;
  createdAt: string | null;
  flushedAt: string | null;
  spans: TraceSpan[];
  scores: TraceScore[];
  langfuseUrl: string | null;
}
