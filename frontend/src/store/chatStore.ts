import { create } from 'zustand';
import type { Message } from '../components/chat/MessageList';
import type { ExchangeReference } from '../types/api';
import type {
  ChatSession,
  DocumentOption,
  ExchangeItem,
  RouteTrace,
} from '../types/api';

interface StreamHandle {
  controller: AbortController;
  done: Promise<void>;
}
import { errorMessage } from '../lib/utils';
import { chatApi, createConversationId } from '../lib/api';
import { buildRouteTraceLookup, buildChatRouteExplain } from '../lib/knowledgeRoute';
import { manageApi } from '../lib/api';

export const CHAT_MODES = {
  DOCUMENT: 'DOCUMENT',
  AUTO_DOCUMENT: 'AUTO_DOCUMENT',
  OPEN_CHAT: 'OPEN_CHAT'
} as const;

export type ChatMode = typeof CHAT_MODES[keyof typeof CHAT_MODES];

interface ChatState {
  sessions: ChatSession[];
  currentConversationId: string;
  messages: Message[];
  isStreaming: boolean;
  isStopping: boolean;
  chatMode: ChatMode;
  documentOptions: DocumentOption[];
  selectedDocumentId: string;
  selectedDocumentName: string;
  currentAssistantMessageId: string;
  currentStreamHandle: StreamHandle | null;
  loadingSessions: boolean;
  loadingConversation: boolean;
  pageError: string;

  // Actions
  refreshSessions: () => Promise<void>;
  refreshDocumentOptions: () => Promise<void>;
  loadConversation: (conversationId: string) => Promise<void>;
  deleteConversation: (conversationId: string) => Promise<void>;
  renameConversation: (conversationId: string, title: string) => Promise<void>;
  pinConversation: (conversationId: string, pinned: boolean) => Promise<void>;
  startNewConversation: () => void;
  setChatMode: (mode: ChatMode) => void;
  setSelectedDocumentId: (id: string) => void;
  sendMessage: (question: string) => Promise<void>;
  stopStreaming: () => Promise<void>;
  updateCurrentAssistant: (mutator: (msg: Message) => void) => void;
  setPageError: (err: string) => void;
}

function createUserMessage(question: string): Message {
  return {
    id: `user-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    role: 'user',
    content: question,
    createdAt: new Date().toISOString()
  };
}

function createAssistantMessage(): Message {
  return {
    id: `assistant-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    role: 'assistant',
    content: '',
    thinkingSteps: [],
    references: [],
    recommendations: [],
    status: 'RUNNING',
    statusText: '',
    errorMessage: '',
    routeExplain: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString()
  };
}

function mapExchangesToMessages(
  exchanges: ExchangeItem[] = [],
  routeTraceLookup: Record<string, RouteTrace> = {}
): Message[] {
  return exchanges.flatMap((exchange) => {
    const createdAt = exchange.createdAt || exchange.createTime || null;
    const updatedAt = exchange.updatedAt || exchange.editTime || createdAt;
    
    const userMessage: Message = {
      id: `exchange-${exchange.exchangeId}-user`,
      role: 'user',
      content: exchange.question || '',
      createdAt: createdAt ?? undefined
    };

    const assistantMessage: Message = {
      id: `exchange-${exchange.exchangeId}-assistant`,
      role: 'assistant',
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
    };

    return [userMessage, assistantMessage];
  });
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  currentConversationId: '',
  messages: [],
  isStreaming: false,
  isStopping: false,
  chatMode: CHAT_MODES.AUTO_DOCUMENT,
  documentOptions: [],
  selectedDocumentId: '',
  selectedDocumentName: '',
  currentAssistantMessageId: '',
  currentStreamHandle: null,
  loadingSessions: false,
  loadingConversation: false,
  pageError: '',

  setPageError: (err) => set({ pageError: err }),

  refreshSessions: async () => {
    set({ loadingSessions: true });
    try {
      const data = await chatApi.listSessions();
      set({ sessions: Array.isArray(data) ? data : [] });
    } catch (error) {
      set({ pageError: errorMessage(error, '加载会话列表失败') });
    } finally {
      set({ loadingSessions: false });
    }
  },

  refreshDocumentOptions: async () => {
    try {
      const data = await chatApi.listKnowledgeDocumentOptions();
      const options = Array.isArray(data) ? data : [];
      set({ documentOptions: options });
    } catch (error) {
      set({ pageError: errorMessage(error, '加载可选知识文档失败') });
    }
  },

  startNewConversation: () => {
    if (get().isStreaming) return;
    
    set({
      currentConversationId: createConversationId(),
      messages: [],
      pageError: ''
    });
  },

  setChatMode: (mode) => {
    if (get().isStreaming || get().chatMode === mode) return;
    set({ chatMode: mode, pageError: '' });
    if (get().messages.length > 0) {
      get().startNewConversation();
    }
  },

  setSelectedDocumentId: (id) => {
    const options = get().documentOptions;
    const opt = options.find((o) => o.documentId === id);
    set({ 
      selectedDocumentId: id,
      selectedDocumentName: opt ? opt.documentName : ''
    });
    if (get().chatMode === CHAT_MODES.DOCUMENT && get().messages.length > 0 && !get().isStreaming) {
      get().startNewConversation();
    }
  },

  loadConversation: async (conversationId) => {
    if (!conversationId || get().isStreaming) return;

    set({ loadingConversation: true, pageError: '' });
    try {
      const [sessionResult, routeTraceResult] = await Promise.allSettled([
        chatApi.getSession(conversationId),
        manageApi.queryKnowledgeRouteTracePage({
          conversationId,
          pageNo: '1',
          pageSize: '200'
        })
      ]);

      if (sessionResult.status !== 'fulfilled') throw sessionResult.reason;

      const session = sessionResult.value;
      const routeTraceLookup = routeTraceResult.status === 'fulfilled'
        ? buildRouteTraceLookup(routeTraceResult.value?.records || [])
        : {};

      set({
        currentConversationId: conversationId,
        messages: mapExchangesToMessages(session.exchanges || [], routeTraceLookup),
        chatMode: (session.chatMode as ChatMode) || CHAT_MODES.OPEN_CHAT,
        selectedDocumentId: session.selectedDocumentId || '',
        selectedDocumentName: session.selectedDocumentName || ''
      });
      
      // Upsert session
      const sessions = [...get().sessions];
      const idx = sessions.findIndex(s => s.conversationId === conversationId);
      if (idx === -1) {
        sessions.unshift(session);
      } else {
        sessions[idx] = session;
      }
      set({ sessions });

    } catch (error) {
      set({ pageError: errorMessage(error, '加载会话详情失败') });
    } finally {
      set({ loadingConversation: false });
    }
  },

  deleteConversation: async (conversationId) => {
    if (!conversationId || get().isStreaming) return;

    try {
      await chatApi.deleteSession(conversationId);
      const nextSessions = get().sessions.filter((item) => item.conversationId !== conversationId);
      set({ sessions: nextSessions });

      if (get().currentConversationId === conversationId) {
        if (nextSessions.length > 0) {
          await get().loadConversation(nextSessions[0].conversationId);
        } else {
          get().startNewConversation();
        }
      }
    } catch (error) {
      set({ pageError: errorMessage(error, '删除会话失败') });
    }
  },

  renameConversation: async (conversationId, title) => {
    if (!conversationId || !title.trim()) return;
    try {
      await chatApi.renameSession(conversationId, title.trim());
      set((state) => ({
        sessions: state.sessions.map((s) =>
          s.conversationId === conversationId ? { ...s, title: title.trim() } : s
        )
      }));
    } catch (error) {
      set({ pageError: errorMessage(error, '重命名失败') });
    }
  },

  pinConversation: async (conversationId, pinned) => {
    if (!conversationId) return;
    try {
      await chatApi.pinSession(conversationId, pinned);
      set((state) => ({
        sessions: state.sessions.map((s) =>
          s.conversationId === conversationId
            ? { ...s, isPinned: pinned, pinnedAt: pinned ? new Date().toISOString() : null }
            : s
        )
      }));
    } catch (error) {
      set({ pageError: errorMessage(error, pinned ? '置顶失败' : '取消置顶失败') });
    }
  },

  updateCurrentAssistant: (mutator) => {
    set((state) => {
      const idx = state.messages.findIndex((m) => m.id === state.currentAssistantMessageId);
      if (idx === -1) return state;

      const newMessages = [...state.messages];
      const updatedMessage = { ...newMessages[idx] };
      mutator(updatedMessage);
      newMessages[idx] = updatedMessage;
      return { messages: newMessages };
    });
  },

  stopStreaming: async () => {
    const state = get();
    if (!state.isStreaming || !state.currentConversationId || !state.currentStreamHandle) return;

    set({ isStopping: true });
    try {
      const result = await chatApi.stopSession(state.currentConversationId);
      get().updateCurrentAssistant((msg) => {
        msg.statusText = String(result?.message || '用户已停止生成');
      });
    } catch (error) {
      set({ pageError: errorMessage(error, '停止会话失败'), isStopping: false });
      return;
    }
    
    if (state.currentStreamHandle.controller) {
      state.currentStreamHandle.controller.abort();
    }
  },

  sendMessage: async (question) => {
    if (!question || get().isStreaming) return;
    if (get().chatMode === CHAT_MODES.DOCUMENT && !get().selectedDocumentId) {
      set({ pageError: '当前文档问答模式下请先选择一个文档' });
      return;
    }

    const conversationId = get().currentConversationId || createConversationId();
    const assistantMessage = createAssistantMessage();

    set({
      currentConversationId: conversationId,
      pageError: '',
      messages: [...get().messages, createUserMessage(question), assistantMessage],
      currentAssistantMessageId: assistantMessage.id,
      isStreaming: true,
      isStopping: false
    });

    const streamHandle = chatApi.openStream(
      {
        question,
        conversationId,
        chatMode: get().chatMode,
        selectedDocumentId: get().chatMode === CHAT_MODES.DOCUMENT ? get().selectedDocumentId || null : null
      },
      {
        onEvent: (event) => {
          get().updateCurrentAssistant((msg) => {
            if (event.type === 'text' && typeof event.content === 'string') {
              msg.content += event.content;
            }
            if (
              event.type === 'thinking' &&
              typeof event.content === 'string' &&
              !msg.thinkingSteps?.includes(event.content)
            ) {
              msg.thinkingSteps = [...(msg.thinkingSteps || []), event.content];
            }
            if (event.type === 'reference' && Array.isArray(event.content)) {
              msg.references = event.content as ExchangeReference[];
            }
            if (event.type === 'recommend' && Array.isArray(event.content)) {
              msg.recommendations = event.content as string[];
            }
            if (event.type === 'status' && typeof event.content === 'string') {
              msg.statusText = event.content;
            }
            if (event.type === 'review' && event.content) {
              const info = event.content as {
                round?: number;
                maxRounds?: number;
                score?: number;
                message?: string;
              };
              msg.statusText = `回答质量审核中（第 ${info.round}/${info.maxRounds} 轮，得分 ${info.score}）`;
              if (info.message && !msg.thinkingSteps?.includes(info.message)) {
                msg.thinkingSteps = [...(msg.thinkingSteps || []), info.message];
              }
            }
            if (event.type === 'review_result' && event.content) {
              const info = event.content as { passed?: boolean; message?: string | null };
              msg.statusText =
                info.message ||
                (info.passed ? '' : '系统提示：回答质量置信度较低，建议核实关键信息');
            }
            if (event.type === 'error') {
              msg.errorMessage =
                typeof event.content === 'string' ? event.content : '对话执行失败';
              msg.status = 'FAILED';
            }
            msg.updatedAt = event.timestamp || new Date().toISOString();
          });
        }
      }
    );

    set({ currentStreamHandle: streamHandle });

    try {
      await streamHandle.done;
    } catch (error) {
      if (!(error instanceof Error) || error.name !== 'AbortError') {
        get().updateCurrentAssistant((msg) => {
          msg.errorMessage = errorMessage(error, '流式对话失败');
          msg.status = 'FAILED';
        });
        set({ pageError: errorMessage(error, '流式对话失败') });
      }
    } finally {
      set({
        currentStreamHandle: null,
        currentAssistantMessageId: '',
        isStreaming: false,
        isStopping: false
      });
      
      // B7 优化：仅刷新会话列表（轻量）；不再重拉会话详情——
      // SSE 流已包含本轮全部内容（含引用/推荐/路由轨迹），全量重拉是冗余网络与渲染开销。
      try {
        await get().refreshSessions();
      } catch {
        // Handle silently
      }
    }
  }
}));
