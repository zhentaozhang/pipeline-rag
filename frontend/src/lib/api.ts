import { getAdminToken, clearAdminAuth } from './adminAuth';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const REQUEST_TIMEOUT = 30000;

export class APIError extends Error {
  status?: number;
  cause?: any;

  constructor(message: string, status?: number, cause?: any) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.cause = cause;
  }
}

function buildApiUrl(path: string): string {
  return API_BASE_URL ? new URL(path, API_BASE_URL).toString() : path;
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

function stringifyManageValue(value: any): any {
  if (Array.isArray(value)) {
    return value.map((item) => stringifyManageValue(item));
  }

  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, stringifyManageValue(item)])
    );
  }

  if (typeof value === 'number' || typeof value === 'bigint') {
    return String(value);
  }

  return value;
}

async function parseJsonResponse(response: Response): Promise<any> {
  const rawText = await response.text();
  if (!rawText) {
    return null;
  }

  try {
    return JSON.parse(rawText);
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
    const payload = JSON.parse(rawText);
    return payload.message || payload.error || rawText;
  } catch {
    return rawText;
  }
}

async function requestJson(path: string, options: RequestInit = {}): Promise<any> {
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
      return null;
    }

    return parseJsonResponse(response);
  } finally {
    clearTimeout(timeoutId);
  }
}

function unwrapApiResponse(payload: any, fallbackMessage = '请求失败') {
  const code = String(payload?.code ?? '');
  if (code !== '0') {
    throw new APIError(payload?.message || fallbackMessage, Number(payload?.code || 500), payload);
  }
  return payload?.data ?? null;
}

async function requestApiEnvelope(path: string, options: RequestInit = {}): Promise<any> {
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
    return unwrapApiResponse(payload);
  } finally {
    clearTimeout(timeoutId);
  }
}

async function requestMultipartApiEnvelope(path: string, formData: FormData, options: RequestInit = {}): Promise<any> {
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
    return unwrapApiResponse(payload);
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
    handlers.onEvent?.(JSON.parse(payload));
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

function normalizePageString(value: any, fallbackValue: string): string {
  const normalized = String(value ?? fallbackValue).trim();
  return normalized || String(fallbackValue);
}

export interface StreamHandlers {
  onEvent?: (event: any) => void;
}

export const chatApi = {
  checkConnection() {
    return requestJson('/api/health', {
      method: 'GET'
    }).catch(() => null);
  },

  listKnowledgeDocumentOptions() {
    return requestApiEnvelope('/api/chat/document/options', {
      method: 'POST',
      body: {} as any
    });
  },

  listSessions(query: any = {}) {
    return chatApi.listSessionsPage({
      keyword: query.keyword || '',
      chatMode: query.chatMode || 'ALL',
      turnStatus: query.turnStatus || 'ALL',
      pageNo: normalizePageString(query.pageNo, '1'),
      pageSize: normalizePageString(query.pageSize, '200')
    }).then((data) => data?.sessions || []);
  },

  listSessionsPage(query: any = {}) {
    return requestApiEnvelope('/api/chat/session/list', {
      method: 'POST',
      body: {
        keyword: String(query.keyword || '').trim(),
        chatMode: String(query.chatMode || 'ALL').trim(),
        turnStatus: String(query.turnStatus || 'ALL').trim(),
        pageNo: normalizePageString(query.pageNo, '1'),
        pageSize: normalizePageString(query.pageSize, '20')
      } as any
    }).then((data) => ({
      pageNo: data?.pageNo || '1',
      pageSize: data?.pageSize || '20',
      totalSize: data?.total ?? '0',
      totalPages: data?.totalPages || '0',
      sessions: data?.sessions || []
    }));
  },

  getSession(conversationId: string) {
    return requestApiEnvelope('/api/chat/session/detail', {
      method: 'POST',
      body: {
        conversationId
      } as any
    });
  },

  getExchangeDetail(conversationId: string, exchangeId: string | number) {
    return requestApiEnvelope('/api/chat/exchange/detail', {
      method: 'POST',
      body: {
        conversationId,
        exchangeId: String(exchangeId)
      } as any
    });
  },

  deleteSession(conversationId: string) {
    return requestApiEnvelope('/api/chat/session/reset', {
      method: 'POST',
      body: {
        conversationId
      } as any
    });
  },

  renameSession(conversationId: string, title: string) {
    return requestApiEnvelope('/api/chat/session/rename', {
      method: 'POST',
      body: {
        conversationId,
        title
      } as any
    });
  },

  pinSession(conversationId: string, pinned: boolean) {
    return requestApiEnvelope('/api/chat/session/pin', {
      method: 'POST',
      body: {
        conversationId,
        pinned
      } as any
    });
  },

  stopSession(conversationId: string) {
    return requestApiEnvelope('/api/chat/session/stop', {
      method: 'POST',
      body: {
        conversationId
      } as any
    });
  },

  rebuildConversationSummary(conversationId: string) {
    return requestApiEnvelope('/api/chat/session/summary/rebuild', {
      method: 'POST',
      body: {
        conversationId
      } as any
    });
  },

  getRetrievalResults(conversationId: string, exchangeId: string | number) {
    return requestApiEnvelope('/api/chat/exchange/retrieval/results', {
      method: 'POST',
      body: {
        conversationId,
        exchangeId: String(exchangeId)
      } as any
    });
  },

  getChannelExecutions(conversationId: string, exchangeId: string | number) {
    return requestApiEnvelope('/api/chat/exchange/channel/executions', {
      method: 'POST',
      body: {
        conversationId,
        exchangeId: String(exchangeId)
      } as any
    });
  },

  getStageBenchmarks() {
    return requestApiEnvelope('/api/chat/stage/benchmarks', {
      method: 'POST',
      body: {} as any
    });
  },

  getRagasEvaluation(conversationId: string, exchangeId: string | number) {
    return requestApiEnvelope('/api/chat/exchange/evaluation', {
      method: 'POST',
      body: {
        conversationId,
        exchangeId: String(exchangeId)
      } as any
    });
  },

  getRagasEvaluationSummary() {
    return requestApiEnvelope('/api/chat/evaluation/summary', {
      method: 'POST',
      body: {} as any
    });
  },

  openStream(payload: any, handlers: StreamHandlers = {}) {
    const controller = new AbortController();

    const done = (async () => {
      const response = await fetch(buildApiUrl('/api/chat/stream'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          ...buildAuthHeaders()
        },
        body: JSON.stringify(payload),
        signal: controller.signal
      });

      if (!response.ok) {
        throw new APIError(await readResponseMessage(response), response.status);
      }

      if (!response.body) {
        throw new APIError('当前浏览器不支持流式响应', 500);
      }

      await consumeEventStream(response.body, handlers);
    })();

    return {
      controller,
      done
    };
  },

  submitFeedback(conversationId: string, exchangeId: string | number, groundTruth: string) {
    return requestApiEnvelope('/api/chat/exchange/feedback', {
      method: 'POST',
      body: {
        conversationId,
        exchangeId: String(exchangeId),
        groundTruth
      } as any
    });
  },

  rateExchange(conversationId: string, exchangeId: string | number, rating: 1 | -1, comment?: string) {
    return requestApiEnvelope('/api/chat/rate', {
      method: 'POST',
      body: {
        conversationId,
        exchangeId: String(exchangeId),
        rating,
        comment
      } as any
    });
  }
};

export const adminAuthApi = {
  login(payload: any) {
    return requestApiEnvelope('/admin/auth/login', {
      method: 'POST',
      body: payload as any
    });
  },

  logout() {
    return requestApiEnvelope('/admin/auth/logout', {
      method: 'POST',
      body: {} as any
    });
  },

  currentUser() {
    return requestJson('/admin/auth/me')
      .then((payload) => unwrapApiResponse(payload));
  }
};

export const manageApi = {
  uploadDocument({ file, documentName, operatorId, knowledgeScopeCode, knowledgeScopeName, businessCategory, documentTags }: any) {
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

  queryDocumentPage(payload: any) {
    return requestApiEnvelope('/manage/document/page/query', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  queryDocumentDetail(documentId: string) {
    return requestApiEnvelope('/manage/document/detail/query', {
      method: 'POST',
      body: stringifyManageValue({
        documentId
      })
    });
  },

  deleteDocument(payload: any) {
    return requestApiEnvelope('/manage/document/delete', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  queryStrategyPlan(documentId: string) {
    return requestApiEnvelope('/manage/document/strategy/plan/query', {
      method: 'POST',
      body: stringifyManageValue({
        documentId
      })
    });
  },

  confirmStrategy(payload: any) {
    return requestApiEnvelope('/manage/document/strategy/confirm', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  buildIndex(payload: any) {
    return requestApiEnvelope('/manage/document/index/build', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  queryDocumentChunks(payload: any) {
    return requestApiEnvelope('/manage/document/chunk/query', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  queryDocumentChunkDetail(payload: any) {
    return requestApiEnvelope('/manage/document/chunk/detail/query', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  queryTaskLogs(payload: any) {
    return requestApiEnvelope('/manage/document/task/log/query', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  saveKnowledgeScope(payload: any) {
    return requestApiEnvelope('/manage/knowledge/scope/save', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  deleteKnowledgeScope(payload: any) {
    return requestApiEnvelope('/manage/knowledge/scope/delete', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  listKnowledgeScopes() {
    return requestApiEnvelope('/manage/knowledge/scope/list', {
      method: 'POST',
      body: {} as any
    });
  },

  saveKnowledgeTopic(payload: any) {
    return requestApiEnvelope('/manage/knowledge/topic/save', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  deleteKnowledgeTopic(payload: any) {
    return requestApiEnvelope('/manage/knowledge/topic/delete', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  listKnowledgeTopics(payload: any = {}) {
    return requestApiEnvelope('/manage/knowledge/topic/list', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  queryDocumentProfile(payload: any) {
    return requestApiEnvelope('/manage/knowledge/document/profile/detail', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  regenerateDocumentProfile(payload: any) {
    return requestApiEnvelope('/manage/knowledge/document/profile/regenerate', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  batchRegenerateDocumentProfiles(payload: any) {
    return requestApiEnvelope('/manage/knowledge/document/profile/batch/regenerate', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  listTopicDocuments(payload: any = {}) {
    return requestApiEnvelope('/manage/knowledge/topic/document/list', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  saveTopicDocumentRelation(payload: any) {
    return requestApiEnvelope('/manage/knowledge/topic/document/save', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  removeTopicDocumentRelation(payload: any) {
    return requestApiEnvelope('/manage/knowledge/topic/document/remove', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  queryKnowledgeRouteTracePage(payload: any = {}) {
    return requestApiEnvelope('/manage/knowledge/route/trace/page/query', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  retryDocument(payload: any) {
    return requestApiEnvelope('/manage/document/retry', {
      method: 'POST',
      body: stringifyManageValue(payload)
    });
  },

  listEvaluationDataset(payload: any = {}) {
    return requestApiEnvelope('/manage/evaluation/dataset/page/query', {
      method: 'POST',
      body: stringifyManageValue({
        pageNo: payload.pageNo || 1,
        pageSize: payload.pageSize || 20
      })
    });
  },

  runEvaluation(datasetIds?: number[]) {
    return requestApiEnvelope('/manage/evaluation/dataset/run', {
      method: 'POST',
      body: stringifyManageValue({
        datasetIds: datasetIds
      })
    });
  },

  deleteEvaluationDataset(datasetId: number) {
    return requestApiEnvelope('/manage/evaluation/dataset/delete', {
      method: 'POST',
      body: stringifyManageValue({ datasetId })
    });
  },

  getMetricsOverview() {
    return requestApiEnvelope('/manage/metrics/overview', {
      method: 'POST',
      body: {} as any
    });
  },

  getUsageTrend(days: number = 14) {
    return requestApiEnvelope('/manage/metrics/usage-trend', {
      method: 'POST',
      body: { days } as any
    });
  },

  getBenchmarks() {
    return requestApiEnvelope('/manage/metrics/benchmarks', {
      method: 'POST',
      body: {} as any
    });
  }
};
