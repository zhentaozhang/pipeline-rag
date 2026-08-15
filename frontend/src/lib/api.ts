import { getAdminToken, clearAdminAuth } from './adminAuth';
import type {
  ChatSession,
  DocumentOption,
  DocumentPageResponse,
  ManageDocument,
  EvaluationDataset,
  KnowledgeScope,
  KnowledgeTopic,
  RouteTracePage,
  SessionDetail,
  TopicDocument,
  SessionListQuery,
  SessionPageResponse,
  StreamEvent,
  StreamRequest,
  StrategyPlanResponse,
  TraceDetail,
  TracePageResponse,
} from '../types/api';

/** 前端会话列表分页结果（listSessionsPage 映射后的 shape，字段为字符串形态） */
export interface SessionPageResult {
  pageNo: string;
  pageSize: string;
  totalSize: string;
  totalPages: string;
  sessions: SessionPageResponse['sessions'];
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const REQUEST_TIMEOUT = 30000;

export class APIError extends Error {
  status?: number;
  cause?: unknown;

  constructor(message: string, status?: number, cause?: unknown) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.cause = cause;
  }
}

function buildApiUrl(path: string): string {
  return API_BASE_URL ? new URL(path, API_BASE_URL).toString() : path;
}

type ApiRequestBody = Record<string, unknown> | unknown[] | string | null | undefined;

interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  body?: ApiRequestBody;
}

function buildAuthHeaders(headers: Record<string, string> = {}): Record<string, string> {
  const token = getAdminToken();
  if (!token) {
    return headers;
  }
  return {
    Authorization: `Bearer ${token}`,
    ...headers
  };
}

function handleUnauthorized(response: Response) {
  if (response.status !== 401) {
    return;
  }
  clearAdminAuth();
  if (window.location.pathname.startsWith('/admin') && window.location.pathname !== '/admin/login') {
    window.location.href = '/admin/login';
  }
}

function stringifyManageValue<T>(value: T): T {
  return stringifyValue(value as unknown) as T;
}

function stringifyValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => stringifyValue(item));
  }

  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        stringifyValue(item),
      ])
    );
  }

  if (typeof value === 'number' || typeof value === 'bigint') {
    return String(value);
  }

  return value;
}

async function parseJsonResponse(response: Response): Promise<unknown> {
  const rawText = await response.text();
  if (!rawText) {
    return null;
  }

  try {
    return JSON.parse(rawText) as unknown;
  } catch (error) {
    throw new APIError(`无法解析后端响应: ${rawText}`, response.status, error);
  }
}

async function readResponseMessage(response: Response): Promise<string> {
  const rawText = await response.text();
  if (!rawText) {
    return `请求失败，状态码 ${response.status}`;
  }

  try {
    const payload = JSON.parse(rawText) as { message?: string; error?: string };
    return payload.message || payload.error || rawText;
  } catch {
    return rawText;
  }
}

async function requestJson<T = unknown>(
  path: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);

  try {
    const response = await fetch(buildApiUrl(path), {
      method: options.method || 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...buildAuthHeaders(options.headers as Record<string, string> || {})
      },
      body: options.body ? (typeof options.body === 'string' ? options.body : JSON.stringify(options.body)) : undefined,
      signal: controller.signal
    });

    if (!response.ok) {
      handleUnauthorized(response);
      throw new APIError(await readResponseMessage(response), response.status);
    }

    if (response.status === 204) {
      return null as unknown as T;
    }

    return parseJsonResponse(response) as Promise<T>;
  } finally {
    clearTimeout(timeoutId);
  }
}

function unwrapApiResponse<T>(payload: unknown, fallbackMessage = '请求失败'): T {
  const envelope = payload as { code?: unknown; message?: unknown; data?: unknown } | null;
  const code = String(envelope?.code ?? '');
  if (code !== '0') {
    throw new APIError(
      String(envelope?.message || fallbackMessage),
      Number(envelope?.code || 500),
      payload
    );
  }
  return (envelope?.data ?? null) as unknown as T;
}

async function requestApiEnvelope<T = unknown>(
  path: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);

  try {
    const response = await fetch(buildApiUrl(path), {
      method: options.method || 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...buildAuthHeaders(options.headers as Record<string, string> || {})
      },
      body: options.body ? (typeof options.body === 'string' ? options.body : JSON.stringify(options.body)) : undefined,
      signal: controller.signal
    });

    if (!response.ok) {
      handleUnauthorized(response);
      throw new APIError(await readResponseMessage(response), response.status);
    }

    const payload = await parseJsonResponse(response);
    return unwrapApiResponse(payload) as T;
  } finally {
    clearTimeout(timeoutId);
  }
}

async function requestMultipartApiEnvelope<T = unknown>(
  path: string,
  formData: FormData,
  options: RequestInit = {}
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);

  try {
    const response = await fetch(buildApiUrl(path), {
      method: options.method || 'POST',
      headers: {
        ...buildAuthHeaders(options.headers as Record<string, string> || {})
      },
      body: formData,
      signal: controller.signal
    });

    if (!response.ok) {
      handleUnauthorized(response);
      throw new APIError(await readResponseMessage(response), response.status);
    }

    const payload = await parseJsonResponse(response);
    return unwrapApiResponse(payload) as T;
  } finally {
    clearTimeout(timeoutId);
  }
}

function dispatchStreamPayload(rawPayload: string, handlers: StreamHandlers) {
  if (!rawPayload) {
    return;
  }

  const payload = rawPayload.trim();
  if (!payload || payload === '[DONE]') {
    return;
  }

  try {
    handlers.onEvent?.(JSON.parse(payload) as StreamEvent);
  } catch (error) {
    throw new APIError(`无法解析后端流式事件: ${payload}`, 500, error);
  }
}

function consumeEventBlock(block: string, handlers: StreamHandlers) {
  const normalizedBlock = block.trim();
  if (!normalizedBlock) {
    return;
  }

  if (normalizedBlock.startsWith('data:')) {
    const payload = normalizedBlock
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n');
    dispatchStreamPayload(payload, handlers);
    return;
  }

  normalizedBlock
    .split(/\r?\n/)
    .filter(Boolean)
    .forEach((line) => dispatchStreamPayload(line, handlers));
}

async function consumeEventStream(stream: ReadableStream<Uint8Array>, handlers: StreamHandlers) {
  const reader = stream.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let boundaryIndex = buffer.search(/\r?\n\r?\n/);
    while (boundaryIndex !== -1) {
      const block = buffer.slice(0, boundaryIndex);
      const separatorMatch = buffer.slice(boundaryIndex).match(/^\r?\n\r?\n/);
      const separatorLength = separatorMatch ? separatorMatch[0].length : 2;
      buffer = buffer.slice(boundaryIndex + separatorLength);
      consumeEventBlock(block, handlers);
      boundaryIndex = buffer.search(/\r?\n\r?\n/);
    }

    if (done) {
      const tail = decoder.decode();
      if (tail) {
        buffer += tail;
      }
      if (buffer.trim()) {
        consumeEventBlock(buffer, handlers);
      }
      return;
    }
  }
}

export function createConversationId(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizePageString(value: unknown, fallbackValue: string): string {
  const normalized = String(value ?? fallbackValue).trim();
  return normalized || String(fallbackValue);
}

export interface StreamHandlers {
  onEvent?: (event: StreamEvent) => void;
}

export const chatApi = {
  checkConnection() {
    return requestJson('/api/health', {
      method: 'GET'
    }).catch(() => null);
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

  openStream(payload: StreamRequest, handlers: StreamHandlers = {}) {
    const controller = new AbortController();

    // 断线重连（第二轮架构评审·可以优化 4）：
    // - 计数已消费事件，断线重连时通过 ?resume=N 让服务端重放未消费缓冲（避免重复渲染）
    // - 收到 done/error 事件或用户 abort 即停止重试
    // - 服务端已完成（缓冲含 done）→ 正常收尾；原流仍在执行 → 服务端返回「执行中」提示
    const MAX_RETRIES = 3;
    const RETRY_DELAYS_MS = [1000, 2000, 4000];

    const done = (async () => {
      let consumed = 0;
      let sawDone = false;
      let sawError = false;
      let attempt = 0;

      const wrappedHandlers: StreamHandlers = {
        onEvent: (event) => {
          consumed += 1;
          if (event.type === 'done') sawDone = true;
          if (event.type === 'error') sawError = true;
          handlers.onEvent?.(event);
        }
      };

      while (true) {
        if (controller.signal.aborted) {
          return;
        }

        const url = buildApiUrl(
          `/api/chat/stream${consumed > 0 ? `?resume=${consumed}` : ''}`
        );
        let response: Response;
        try {
          response = await fetch(url, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Accept: 'text/event-stream',
              ...buildAuthHeaders()
            },
            body: JSON.stringify(payload),
            signal: controller.signal
          });
        } catch (error) {
          // 网络层失败（连接未建立）：尝试重连
          if (attempt >= MAX_RETRIES || controller.signal.aborted) {
            throw new APIError('网络连接中断，请稍后重试', 0, error);
          }
          await sleep(RETRY_DELAYS_MS[attempt]);
          attempt += 1;
          continue;
        }

        if (!response.ok) {
          throw new APIError(await readResponseMessage(response), response.status);
        }
        if (!response.body) {
          throw new APIError('当前浏览器不支持流式响应', 500);
        }

        await consumeEventStream(response.body, wrappedHandlers);

        // 正常收尾条件：收到 done / error，或用户主动中断
        if (sawDone || sawError || controller.signal.aborted) {
          return;
        }

        // 流被截断（服务端断开但未完成）：退避重连续传
        if (attempt >= MAX_RETRIES) {
          throw new APIError('连接中断，未能恢复完整回答', 0);
        }
        await sleep(RETRY_DELAYS_MS[attempt]);
        attempt += 1;
      }
    })();

    return {
      controller,
      done
    };
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
  }
};

export const adminAuthApi = {
  login(payload: {
    username: string;
    password: string;
  }): Promise<{
    username: string;
    token: string;
    tokenType: string;
    tokenExpireMinutes: number;
  }> {
    return requestApiEnvelope<
      { username: string; token: string; tokenType: string; tokenExpireMinutes: number }
    >('/admin/auth/login', {
      method: 'POST',
      body: payload
    });
  },

  logout() {
    return requestApiEnvelope('/admin/auth/logout', {
      method: 'POST',
      body: {}
    });
  },

  currentUser(): Promise<{ username: string }> {
    return requestJson<{ code: number; data: { username: string }; message: string | null }>(
      '/admin/auth/me'
    ).then((payload) => unwrapApiResponse<{ username: string }>(payload));
  }
};

export const manageApi = {
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

  saveKnowledgeScope(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/scope/save', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  deleteKnowledgeScope(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/scope/delete', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  listKnowledgeScopes(): Promise<KnowledgeScope[]> {
    return requestApiEnvelope('/manage/knowledge/scope/list', {
      method: 'POST',
      body: {}
    });
  },

  saveKnowledgeTopic(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/topic/save', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  deleteKnowledgeTopic(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/topic/delete', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  listKnowledgeTopics(payload: Record<string, unknown> = {}): Promise<KnowledgeTopic[]> {
    return requestApiEnvelope('/manage/knowledge/topic/list', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  queryDocumentProfile(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/document/profile/detail', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  regenerateDocumentProfile(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/document/profile/regenerate', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  batchRegenerateDocumentProfiles(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/document/profile/batch/regenerate', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  listTopicDocuments(payload: Record<string, unknown> = {}): Promise<TopicDocument[]> {
    return requestApiEnvelope('/manage/knowledge/topic/document/list', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  saveTopicDocumentRelation(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/topic/document/save', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  removeTopicDocumentRelation(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/knowledge/topic/document/remove', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  queryKnowledgeRouteTracePage(payload: Record<string, unknown> = {}): Promise<RouteTracePage> {
    return requestApiEnvelope<RouteTracePage>('/manage/knowledge/route/trace/page/query', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  retryDocument(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return requestApiEnvelope('/manage/document/retry', {
      method: 'POST',
      body: stringifyManageValue(payload)
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
