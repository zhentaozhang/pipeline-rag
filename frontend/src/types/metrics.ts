/**
 * Metrics 域 API 类型：指标面板 / 阶段耗时基准
 * 与后端 VO 对齐，CamelModel 输出 camelCase
 */

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
  cacheHitRatio?: number;
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
