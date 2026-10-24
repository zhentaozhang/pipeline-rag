import type {
  ChatSession,
  DocumentOption,
  SessionDetail,
  SessionListQuery,
  SessionPageResponse,
} from '../../types/api';
import type { SessionPageResult } from '../http/client';
import { normalizePageString, requestApiEnvelope, requestJson } from '../http/client';
import { chatStreamApi } from './chat-stream';

export function createConversationId(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

export const chatApi = {
  checkConnection(): Promise<boolean> {
    // 只有真正拿到 2xx 才算连通。之前是 .catch(() => null)，调用方又用
    // "res !== undefined" 判断，永远为真 —— 后端挂掉也会显示绿灯。
    return requestJson<unknown>('/api/health', {
      method: 'GET'
    }).then(
      (payload) => {
        // /health 直接返回 {"status":"ok"}，不是 {code,data} 信封；
        // 但只要响应里明确带了非 '0' 的 code，就说明后端自报不健康。
        const code = (payload as { code?: unknown } | null)?.code;
        return code === undefined || code === null || String(code) === '0';
      },
      () => false
    );
  },

  listKnowledgeDocumentOptions(): Promise<DocumentOption[]> {
    return requestApiEnvelope<DocumentOption[]>('/api/chat/document/options', {
      method: 'POST',
      body: {},
    });
  },

  listSessions(query: SessionListQuery = {}): Promise<ChatSession[]> {
    return chatApi.listSessionsPage({
      keyword: query.keyword || '',
      chatMode: query.chatMode || 'ALL',
      turnStatus: query.turnStatus || 'ALL',
      pageNo: normalizePageString(query.pageNo, '1'),
      pageSize: normalizePageString(query.pageSize, '200')
    }).then((data) => data?.sessions || []);
  },

  listSessionsPage(query: SessionListQuery = {}): Promise<SessionPageResult> {
    return requestApiEnvelope<SessionPageResponse>('/api/chat/session/list', {
      method: 'POST',
      body: {
        keyword: String(query.keyword || '').trim(),
        chatMode: String(query.chatMode || 'ALL').trim(),
        turnStatus: String(query.turnStatus || 'ALL').trim(),
        pageNo: normalizePageString(query.pageNo, '1'),
        pageSize: normalizePageString(query.pageSize, '20'),
      },
    }).then((data) => ({
      pageNo: String(data.pageNo || 1),
      pageSize: String(data.pageSize || 20),
      totalSize: String(data.total ?? 0),
      totalPages: String(data.totalPages || 0),
      sessions: data.sessions || [],
    }));
  },

  getSession(conversationId: string): Promise<SessionDetail> {
    return requestApiEnvelope<SessionDetail>('/api/chat/session/detail', {
      method: 'POST',
      body: {
        conversationId
      }
    });
  },

  getExchangeDetail(conversationId: string, exchangeId: string | number) {
    return requestApiEnvelope('/api/chat/exchange/detail', {
      method: 'POST',
      body: {
        conversationId,
        exchangeId: String(exchangeId)
      }
    });
  },

  deleteSession(conversationId: string) {
    return requestApiEnvelope('/api/chat/session/reset', {
      method: 'POST',
      body: {
        conversationId
      }
    });
  },

  renameSession(conversationId: string, title: string) {
    return requestApiEnvelope('/api/chat/session/rename', {
      method: 'POST',
      body: {
        conversationId,
        title
      }
    });
  },

  pinSession(conversationId: string, pinned: boolean) {
    return requestApiEnvelope('/api/chat/session/pin', {
      method: 'POST',
      body: {
        conversationId,
        pinned
      }
    });
  },

  stopSession(conversationId: string): Promise<Record<string, unknown>> {
    return requestApiEnvelope<Record<string, unknown>>('/api/chat/session/stop', {
      method: 'POST',
      body: {
        conversationId
      }
    });
  },

  rebuildConversationSummary(conversationId: string) {
    return requestApiEnvelope('/api/chat/session/summary/rebuild', {
      method: 'POST',
      body: {
        conversationId
      }
    });
  },

  getRetrievalResults(conversationId: string, exchangeId: string | number) {
    return requestApiEnvelope('/api/chat/exchange/retrieval/results', {
      method: 'POST',
      body: {
        conversationId,
        exchangeId: String(exchangeId)
      }
    });
  },

  getChannelExecutions(conversationId: string, exchangeId: string | number) {
    return requestApiEnvelope('/api/chat/exchange/channel/executions', {
      method: 'POST',
      body: {
        conversationId,
        exchangeId: String(exchangeId)
      }
    });
  },

  getStageBenchmarks() {
    return requestApiEnvelope('/api/chat/stage/benchmarks', {
      method: 'POST',
      body: {}
    });
  },

  getRagasEvaluation(conversationId: string, exchangeId: string | number) {
    return requestApiEnvelope('/api/chat/exchange/evaluation', {
      method: 'POST',
      body: {
        conversationId,
        exchangeId: String(exchangeId)
      }
    });
  },

  getRagasEvaluationSummary() {
    return requestApiEnvelope('/api/chat/evaluation/summary', {
      method: 'POST',
      body: {}
    });
  },

  submitFeedback(
    conversationId: string,
    exchangeId: string | number,
    groundTruth: string
  ): Promise<Record<string, unknown>> {
    return requestApiEnvelope<Record<string, unknown>>('/api/chat/exchange/feedback', {
      method: 'POST',
      body: {
        conversationId,
        exchangeId: String(exchangeId),
        groundTruth
      }
    });
  },

  rateExchange(
    conversationId: string,
    exchangeId: string | number,
    rating: 1 | -1,
    comment?: string
  ): Promise<Record<string, unknown>> {
    return requestApiEnvelope<Record<string, unknown>>('/api/chat/rate', {
      method: 'POST',
      body: {
        conversationId,
        exchangeId: String(exchangeId),
        rating,
        comment
      }
    });
  },

  ...chatStreamApi
};
