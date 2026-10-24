import type { Message } from '../components/chat/MessageList';
import type { ExchangeItem, ExchangeReference, RouteTrace, SessionDetail, StreamEvent } from '../types/api';
import { chatApi, manageApi } from '../lib/api';
import { buildChatRouteExplain, buildRouteTraceLookup } from '../lib/knowledgeRoute';
import { errorMessage } from '../lib/utils';

/**
 * 流式运行时：把"一轮问答"从 store 里拆出来的原因有两个 ——
 * 一是 chatStore 已经接近 600 行（单文件上限 300），二是这一坨逻辑
 * 与 session 管理无关，只有 store 的 set/get 需要注入。
 */

export interface StreamHandle {
  controller: AbortController;
  done: Promise<void>;
}

export interface TurnInput {
  conversationId: string;
  chatMode: string;
  selectedDocumentId: string;
}

/** store 侧需要提供给流式运行时的最小能力面 */
export interface TurnHooks {
  /** 把正在流的那条（或 null）写进 store */
  setDraft: (draft: Message | null) => void;
  /** token 级高频更新：只改草稿本身，不动 messages */
  patchDraft: (updater: (draft: Message) => Message) => void;
  setStreamHandle: (handle: StreamHandle | null) => void;
  /** 流结束（成功/失败/停止）后由 store 收尾：落盘草稿、刷新列表、发出排队问题 */
  onFinish: () => void;
}

const uid = (prefix: string) => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;

export function createUserMessage(question: string): Message {
  return { id: uid('user'), role: 'user', content: question, createdAt: new Date().toISOString() };
}

export function createAssistantDraft(): Message {
  const now = new Date().toISOString();
  return {
    id: uid('assistant'),
    role: 'assistant',
    content: '',
    thinkingSteps: [],
    references: [],
    recommendations: [],
    status: 'RUNNING',
    statusText: '',
    errorMessage: '',
    routeExplain: null,
    createdAt: now,
    updatedAt: now
  };
}

/** 历史会话 → 消息列表（一轮问答拆成 user + assistant 两条） */
export function mapExchangesToMessages(
  exchanges: ExchangeItem[] = [],
  routeTraceLookup: Record<string, RouteTrace> = {}
): Message[] {
  return exchanges.flatMap((exchange) => {
    const createdAt = exchange.createdAt || exchange.createTime || null;
    const updatedAt = exchange.updatedAt || exchange.editTime || createdAt;
    return [
      {
        id: `exchange-${exchange.exchangeId}-user`,
        role: 'user' as const,
        content: exchange.question || '',
        createdAt: createdAt ?? undefined
      },
      {
        id: `exchange-${exchange.exchangeId}-assistant`,
        role: 'assistant' as const,
        exchangeId: exchange.exchangeId ? Number(exchange.exchangeId) : undefined,
        content: exchange.answer || '',
        thinkingSteps: exchange.thinkingSteps || [],
        references: exchange.references || [],
        recommendations: exchange.recommendations || [],
        status: exchange.status || '',
        statusText: '',
        errorMessage: exchange.errorMessage || '',
        routeExplain: buildChatRouteExplain(routeTraceLookup[String(exchange.exchangeId)]),
        createdAt: createdAt ?? undefined,
        updatedAt: updatedAt ?? undefined
      }
    ];
  });
}

/**
 * 直接把一个 SSE 事件作用到"正在流的那条"上。
 * 关键点：返回的是新的草稿对象，messages 数组和其中历史消息的引用全都不变，
 * 所以 memo 过的消息项不会重渲染。
 */
export function applyStreamEvent(draft: Message, event: StreamEvent): Message {
  const next: Message = { ...draft, updatedAt: event.timestamp || new Date().toISOString() };
  const content = event.content;
  const pushStep = (step: string) => {
    if (next.thinkingSteps?.includes(step)) return;
    next.thinkingSteps = [...(next.thinkingSteps || []), step];
  };

  switch (event.type) {
    case 'clear_answer':
      next.content = '';
      break;
    case 'text':
      if (typeof content === 'string') next.content += content;
      break;
    case 'thinking':
      if (typeof content === 'string') pushStep(content);
      break;
    case 'reference':
      if (Array.isArray(content)) next.references = content as ExchangeReference[];
      break;
    case 'recommend':
      if (Array.isArray(content)) next.recommendations = content as string[];
      break;
    case 'status':
      if (typeof content === 'string') next.statusText = content;
      break;
    case 'review': {
      const info = (content || {}) as { round?: number; maxRounds?: number; score?: number; message?: string };
      next.content = '';
      next.statusText = `回答质量审核中（第 ${info.round}/${info.maxRounds} 轮，得分 ${info.score}）`;
      if (info.message) pushStep(info.message);
      break;
    }
    case 'review_result': {
      const info = (content || {}) as { passed?: boolean; message?: string | null };
      next.statusText = info.message || (info.passed ? '' : '系统提示：回答质量置信度较低，建议核实关键信息');
      break;
    }
    case 'error':
      next.errorMessage = typeof content === 'string' ? content : '对话执行失败';
      next.status = 'FAILED';
      break;
    case 'done':
      if (event.exchangeId) {
        next.exchangeId = Number(event.exchangeId);
        next.id = `exchange-${event.exchangeId}-assistant`;
      }
      if (next.status !== 'FAILED') next.status = 'COMPLETED';
      next.statusText = '';
      break;
    default:
      // statusText 之外的新事件类型：保留现状，避免旧后端未知事件把回答清空
      break;
  }
  return next;
}

/** 拉会话详情 + 路由溯源，合并成可直接展示的消息列表。视图层/Store 都不该关心这两次请求怎么拼。 */
export async function loadConversationPayload(
  conversationId: string
): Promise<{ session: SessionDetail; messages: Message[] }> {
  const [sessionResult, routeTraceResult] = await Promise.allSettled([
    chatApi.getSession(conversationId),
    manageApi.queryKnowledgeRouteTracePage({ conversationId, pageNo: '1', pageSize: '200' })
  ]);
  // route trace 只是增强信息，拿不到也不该让整页失败
  if (sessionResult.status !== 'fulfilled') throw sessionResult.reason;
  const session = sessionResult.value;
  const lookup =
    routeTraceResult.status === 'fulfilled' ? buildRouteTraceLookup(routeTraceResult.value?.records || []) : {};
  return { session, messages: mapExchangesToMessages(session.exchanges || [], lookup) };
}

/** 跑一轮流式问答。调用方负责先把用户问题放进 messages，并在 finally 前保持 isStreaming 语义。 */
export async function runTurn(input: TurnInput, question: string, hooks: TurnHooks): Promise<void> {
  const draft = createAssistantDraft();
  hooks.setDraft(draft);

  const handle = chatApi.openStream(
    {
      question,
      conversationId: input.conversationId,
      chatMode: input.chatMode,
      selectedDocumentId: input.chatMode === 'DOCUMENT' ? input.selectedDocumentId || null : null
    },
    {
      onEvent: (event) => hooks.patchDraft((current) => applyStreamEvent(current, event)),
      onReconnect: (attempt, maxRetries) =>
        hooks.patchDraft((current) => ({
          ...current,
          statusText: `网络连接不稳定，正在自动重连 (${attempt}/${maxRetries})…`
        }))
    }
  );

  hooks.setStreamHandle(handle);

  try {
    await handle.done;
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      hooks.patchDraft((current) => ({
        ...current,
        status: 'STOPPED',
        statusText: current.statusText || '用户已停止生成'
      }));
    } else {
      // 消息级错误只落在气泡上；pageError 留给"整页不可用"的场景
      const message = errorMessage(error, '流式对话失败');
      hooks.patchDraft((current) => ({ ...current, status: 'FAILED', errorMessage: message }));
    }
  } finally {
    hooks.onFinish();
  }
}
