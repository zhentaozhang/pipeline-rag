import type {
  DocumentPageResponse,
  ManageDocument,
  StrategyPlanResponse,
} from '../../../types/api';
import {
  requestApiEnvelope,
  requestMultipartApiEnvelope,
  stringifyManageValue,
} from '../../http/client';

/** manageApi 的文档/策略/chunk 分组（被 api/manage.ts 用 spread 合回 manageApi） */
export const documentApi = {
  uploadDocument(params: {
    file: File;
    documentName?: string;
    operatorId?: string;
    knowledgeScopeCode?: string;
    knowledgeScopeName?: string;
    businessCategory?: string;
    documentTags?: string;
  }): Promise<Record<string, unknown>> {
    const {
      file,
      documentName,
      operatorId,
      knowledgeScopeCode,
      knowledgeScopeName,
      businessCategory,
      documentTags,
    } = params;
    const formData = new FormData();
    formData.append('file', file);

    const meta = stringifyManageValue({
      documentName: documentName || '',
      operatorId: operatorId ?? '',
      knowledgeScopeCode: knowledgeScopeCode || '',
      knowledgeScopeName: knowledgeScopeName || '',
      businessCategory: businessCategory || '',
      documentTags: documentTags || ''
    });
    formData.append('meta', new Blob([JSON.stringify(meta)], { type: 'application/json' }));

    return requestMultipartApiEnvelope('/manage/document/upload', formData);
  },

  queryDocumentPage(payload: Record<string, unknown>): Promise<DocumentPageResponse> {
    return requestApiEnvelope<DocumentPageResponse>('/manage/document/page/query', {
      method: 'POST',
      body: stringifyManageValue(payload),
    });
  },

  queryDocumentDetail(documentId: string): Promise<ManageDocument> {
    return requestApiEnvelope<ManageDocument>('/manage/document/detail/query', {
      method: 'POST',
      body: stringifyManageValue({
        documentId
      })
    });
  },

  deleteDocument(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/document/delete', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  queryStrategyPlan(documentId: string): Promise<StrategyPlanResponse> {
    return requestApiEnvelope<StrategyPlanResponse>('/manage/document/strategy/plan/query', {
      method: 'POST',
      body: stringifyManageValue({
        documentId,
      }),
    });
  },

  confirmStrategy(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/document/strategy/confirm', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  buildIndex(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/document/index/build', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  queryDocumentChunks(
    payload: Record<string, unknown>
  ): Promise<{ records: unknown[]; total: number; pageNo?: string; pageSize?: string }> {
    return requestApiEnvelope<{
      records: unknown[];
      total: number;
      pageNo?: string;
      pageSize?: string;
    }>('/manage/document/chunk/query', {
      method: 'POST',
      body: stringifyManageValue(payload),
    });
  },

  queryDocumentChunkDetail(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/document/chunk/detail/query', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  queryTaskLogs(payload: Record<string, unknown>): Promise<{ logs: unknown[] }> {
    return requestApiEnvelope<{ logs: unknown[] }>('/manage/document/task/log/query', {
      method: 'POST',
      body: stringifyManageValue(payload),
    });
  },

  retryDocument(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/document/retry', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  }
};
