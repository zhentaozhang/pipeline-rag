import type { EvaluationDataset, TraceDetail, TracePageResponse } from '../../../types/api';
import { requestApiEnvelope, stringifyManageValue } from '../../http/client';

/** manageApi 的可观测/评估/指标分组（被 api/manage.ts 用 spread 合回 manageApi） */
export const observabilityApi = {
  getTraces(params: {
    pageNo?: number;
    pageSize?: number;
    conversationId?: string;
    status?: string;
    dateFrom?: string;
    dateTo?: string;
  } = {}): Promise<TracePageResponse> {
    const query = new URLSearchParams();
    if (params.pageNo !== undefined) query.set('pageNo', String(params.pageNo));
    if (params.pageSize !== undefined) query.set('pageSize', String(params.pageSize));
    if (params.conversationId) query.set('conversationId', params.conversationId);
    if (params.status) query.set('status', params.status);
    if (params.dateFrom) query.set('from', params.dateFrom);
    if (params.dateTo) query.set('to', params.dateTo);
    const qs = query.toString();
    return requestApiEnvelope<TracePageResponse>(
      `/manage/observe/traces${qs ? `?${qs}` : ''}`,
      { method: 'GET' }
    );
  },

  getTraceDetail(traceId: string): Promise<TraceDetail> {
    return requestApiEnvelope<TraceDetail>(`/manage/observe/traces/${traceId}`, {
      method: 'GET'
    });
  },

  listEvaluationDataset(
    payload: Record<string, unknown> = {}
  ): Promise<{ records: EvaluationDataset[]; total?: number }> {
    return requestApiEnvelope('/manage/evaluation/dataset/page/query', {
      method: 'POST',
      body: stringifyManageValue({
        pageNo: payload.pageNo || 1,
        pageSize: payload.pageSize || 20
      })
    });
  },

  runEvaluation(datasetIds?: number[]): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/evaluation/dataset/run', {
      method: 'POST',
      body: stringifyManageValue({
        datasetIds: datasetIds
      })
    });
  },

  deleteEvaluationDataset(datasetId: number): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/evaluation/dataset/delete', {
      method: 'POST',
      body: stringifyManageValue({ datasetId })
    });
  },

  getMetricsOverview(): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/metrics/overview', {
      method: 'POST',
      body: {}
    });
  },

  getUsageTrend(days: number = 14): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/metrics/usage-trend', {
      method: 'POST',
      body: { days }
    });
  },

  getBenchmarks(): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/metrics/benchmarks', {
      method: 'POST',
      body: {}
    });
  }
};
