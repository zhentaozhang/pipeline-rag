import { create } from 'zustand';

import type { Message } from '../components/chat/MessageList';
import type { ChatSession, DocumentOption } from '../types/api';
import { chatApi, createConversationId } from '../lib/api';
import { toast } from '../lib/toast';
import { errorMessage } from '../lib/utils';
import { createUserMessage, loadConversationPayload, runTurn, type StreamHandle } from './chatStream';

export const CHAT_MODES = {
  DOCUMENT: 'DOCUMENT',
  AUTO_DOCUMENT: 'AUTO_DOCUMENT',
  OPEN_CHAT: 'OPEN_CHAT'
} as const;

export type ChatMode = typeof CHAT_MODES[keyof typeof CHAT_MODES];

/** 页面级错误的来源：决定「重试」按钮重新拉什么，避免一错就全屏提示 */
export type PageErrorScope = 'sessions' | 'conversation' | '';

interface ChatState {
  sessions: ChatSession[];
  currentConversationId: string;
  messages: Message[];
  /** 正在流式生成的那一条。与 messages 分开存：以前每来一个 token 都要复制整个
   *  messages 数组（长对话下等于每 token 一次 O(n) 拷贝 + 全列表重渲染）。 */
  streamingDraft: Message | null;
  isStreaming: boolean;
  isStopping: boolean;
  chatMode: ChatMode;
  documentOptions: DocumentOption[];
  selectedDocumentId: string;
  selectedDocumentName: string;
  /** 流式中用户提交的问题，本轮结束后自动发出 */
  pendingQuestion: string;
  currentStreamHandle: StreamHandle | null;
  loadingSessions: boolean;
  loadingConversation: boolean;
  pageError: string;
  pageErrorScope: PageErrorScope;

  refreshSessions: () => Promise<void>;
  refreshDocumentOptions: () => Promise<void>;
  loadConversation: (conversationId: string) => Promise<void>;
  deleteSession: (conversationId: string) => Promise<void>;
  renameSession: (conversationId: string, title: string) => Promise<void>;
  pinSession: (conversationId: string, pinned: boolean) => Promise<void>;
  startNewConversation: () => void;
  setChatMode: (mode: ChatMode) => void;
  setSelectedDocumentId: (id: string) => void;
  sendMessage: (question: string) => Promise<void>;
  enqueueQuestion: (question: string) => void;
  clearPendingQuestion: () => void;
  regenerate: (assistantMessageId: string) => Promise<void>;
  retryLast: () => Promise<void>;
  editAndResend: (userMessageId: string, newText: string) => Promise<void>;
  stopStreaming: () => Promise<void>;
  setPageError: (err: string) => void;
  clearPageError: () => void;
  retryPageError: () => Promise<void>;
}

export const useChatStore = create<ChatState>((set, get) => {
  const patchSession = (conversationId: string, patch: (item: ChatSession) => ChatSession) =>
    set((state) => ({
      sessions: state.sessions.map((item) => (item.conversationId === conversationId ? patch(item) : item))
    }));
  const patchDraft = (updater: (draft: Message) => Message) =>
    set((state) => (state.streamingDraft ? { streamingDraft: updater(state.streamingDraft) } : state));

  /** 结束流式：草稿落成正式消息，再决定是否发出排队的问题 */
  const finishTurn = () => {
    set({ currentStreamHandle: null, isStreaming: false, isStopping: false });
    const draft = get().streamingDraft;
    if (draft) set((state) => ({ messages: [...state.messages, draft], streamingDraft: null }));
    void get().refreshSessions();
    const queued = get().pendingQuestion;
    if (queued) {
      set({ pendingQuestion: '' });
      // 只有本轮真正结束（成功/失败/停止）才轮到这里，所以排队问题不会打断正在流的那条
      void get().sendMessage(queued);
    }
  };

  /** 跑一轮流式；调用方负责先把用户问题放进 messages */
  const runStream = async (question: string) => {
    const conversationId = get().currentConversationId || createConversationId();
    const { chatMode, selectedDocumentId } = get();
    set({ currentConversationId: conversationId, isStreaming: true, isStopping: false, pageError: '', pageErrorScope: '' });
    await runTurn({ conversationId, chatMode, selectedDocumentId }, question, {
      setDraft: (draft) => set({ streamingDraft: draft }),
      patchDraft,
      setStreamHandle: (handle) => set({ currentStreamHandle: handle }),
      onFinish: finishTurn
    });
  };

  return {
    sessions: [],
    currentConversationId: '',
    messages: [],
    streamingDraft: null,
    isStreaming: false,
    isStopping: false,
    chatMode: CHAT_MODES.AUTO_DOCUMENT,
    documentOptions: [],
    selectedDocumentId: '',
    selectedDocumentName: '',
    pendingQuestion: '',
    currentStreamHandle: null,
    loadingSessions: false,
    loadingConversation: false,
    pageError: '',
    pageErrorScope: '',

    setPageError: (err) => set({ pageError: err, pageErrorScope: 'sessions' }),
    clearPageError: () => set({ pageError: '', pageErrorScope: '' }),
    retryPageError: async () => {
      const { pageErrorScope, currentConversationId } = get();
      set({ pageError: '', pageErrorScope: '' });
      if (pageErrorScope === 'conversation' && currentConversationId) await get().loadConversation(currentConversationId);
      else await get().refreshSessions();
    },
    refreshSessions: async () => {
      set({ loadingSessions: true });
      try {
        const data = await chatApi.listSessions();
        set({ sessions: Array.isArray(data) ? data : [] });
      } catch (error) {
        // 页面级：会话列表拿不到，侧边栏整块不可用
        set({ pageError: errorMessage(error, '加载会话列表失败，请检查网络后重试'), pageErrorScope: 'sessions' });
      } finally {
        set({ loadingSessions: false });
      }
    },

    refreshDocumentOptions: async () => {
      try {
        const data = await chatApi.listKnowledgeDocumentOptions();
        set({ documentOptions: Array.isArray(data) ? data : [] });
      } catch (error) {
        // 操作级：文档下拉失败不影响主流程，一条 toast 足够
        toast({ title: '加载可选文档失败', description: errorMessage(error, '请稍后重试'), variant: 'error' });
      }
    },

    startNewConversation: () => {
      if (get().isStreaming) return;
      // 新会话 id 推迟到第一条消息时生成，否则一进 /chat 就多出一个空会话地址；
      // 新对话也不该继承上一篇文档的选择（旧实现漏了这两件事）
      set({ currentConversationId: '', messages: [], streamingDraft: null, pendingQuestion: '', selectedDocumentId: '', selectedDocumentName: '', pageError: '', pageErrorScope: '' });
    },

    setChatMode: (mode) => {
      if (get().isStreaming || get().chatMode === mode) return;
      // 不再静默清空对话：要不要开新对话由视图层确认后显式调 startNewConversation
      set({ chatMode: mode, pageError: '', pageErrorScope: '' });
    },

    setSelectedDocumentId: (id) => {
      const option = get().documentOptions.find((item) => item.documentId === id);
      set({ selectedDocumentId: id, selectedDocumentName: option ? option.documentName : '' });
    },

    loadConversation: async (conversationId) => {
      if (!conversationId || get().isStreaming) return;
      set({ loadingConversation: true, pageError: '', pageErrorScope: '' });
      try {
        const { session, messages } = await loadConversationPayload(conversationId);
        const sessions = [...get().sessions];
        const index = sessions.findIndex((item) => item.conversationId === conversationId);
        if (index === -1) sessions.unshift(session);
        else sessions[index] = session;
        set({ currentConversationId: conversationId, messages, sessions, chatMode: (session.chatMode as ChatMode) || CHAT_MODES.OPEN_CHAT, selectedDocumentId: session.selectedDocumentId || '', selectedDocumentName: session.selectedDocumentName || '' });
      } catch (error) {
        // 页面级：详情拿不到整页就真的没内容（例如 URL 里的会话已被删除）
        set({ pageError: errorMessage(error, '加载会话失败，可能已被删除'), pageErrorScope: 'conversation' });
      } finally {
        set({ loadingConversation: false });
      }
    },
    deleteSession: async (conversationId) => {
      if (!conversationId || get().isStreaming) return;
      const snapshot = get().sessions;
      const wasCurrent = get().currentConversationId === conversationId;
      // 乐观更新：先摘掉，失败时连列表顺序一起回滚（Sidebar 的排序依赖顺序）
      set({ sessions: snapshot.filter((item) => item.conversationId !== conversationId) });
      if (wasCurrent) {
        const next = get().sessions[0];
        if (next) void get().loadConversation(next.conversationId);
        else get().startNewConversation();
      }
      try {
        await chatApi.deleteSession(conversationId);
        toast({ title: '会话已删除', variant: 'success' });
      } catch (error) {
        set({ sessions: snapshot });
        if (wasCurrent) void get().loadConversation(conversationId);
        toast({ title: '删除会话失败', description: errorMessage(error, '已恢复该会话，请稍后重试'), variant: 'error' });
      }
    },

    renameSession: async (conversationId, title) => {
      const nextTitle = title.trim();
      if (!conversationId || !nextTitle) return;
      const previous = get().sessions.find((item) => item.conversationId === conversationId)?.title ?? '';
      patchSession(conversationId, (item) => ({ ...item, title: nextTitle }));
      try {
        await chatApi.renameSession(conversationId, nextTitle);
      } catch (error) {
        patchSession(conversationId, (item) => ({ ...item, title: previous }));
        toast({ title: '重命名失败', description: errorMessage(error, '已恢复原名，请稍后重试'), variant: 'error' });
      }
    },

    pinSession: async (conversationId, pinned) => {
      if (!conversationId) return;
      const previous = Boolean(get().sessions.find((item) => item.conversationId === conversationId)?.isPinned);
      patchSession(conversationId, (item) => ({ ...item, isPinned: pinned }));
      try {
        await chatApi.pinSession(conversationId, pinned);
      } catch (error) {
        patchSession(conversationId, (item) => ({ ...item, isPinned: previous }));
        const title = pinned ? '置顶失败' : '取消置顶失败';
        toast({ title, description: errorMessage(error, '已恢复原状态，请稍后重试'), variant: 'error' });
      }
    },

    sendMessage: async (question) => {
      const text = question.trim();
      if (!text) return;
      if (get().isStreaming) {
        // 流式中提交：排队等本轮结束，绝不覆盖正在流的那条
        set({ pendingQuestion: text });
        return;
      }
      if (get().chatMode === CHAT_MODES.DOCUMENT && !get().selectedDocumentId) {
        toast({ title: '请先选择文档', description: '文档问答模式需要先指定一篇文档再提问', variant: 'error' });
        return;
      }
      set({ messages: [...get().messages, createUserMessage(text)], pageError: '', pageErrorScope: '' });
      await runStream(text);
    },

    enqueueQuestion: (question) => {
      const text = question.trim();
      if (text) set({ pendingQuestion: text });
    },
    clearPendingQuestion: () => set({ pendingQuestion: '' }),

    regenerate: async (assistantMessageId) => {
      const state = get();
      if (state.isStreaming) return;
      const target = state.messages.findIndex((item) => item.id === assistantMessageId);
      if (target < 0) return;
      let userIndex = -1;
      for (let index = target - 1; index >= 0; index -= 1) {
        if (state.messages[index].role === 'user') {
          userIndex = index;
          break;
        }
      }
      if (userIndex < 0) return;
      // 丢掉这条回答及其后所有内容，问题本身保留，然后用原问题重发
      set({ messages: state.messages.slice(0, target) });
      await runStream(state.messages[userIndex].content);
    },

    retryLast: async () => {
      const last = [...get().messages].reverse().find((item) => item.role === 'assistant');
      if (last) await get().regenerate(last.id);
    },

    editAndResend: async (userMessageId, newText) => {
      const state = get();
      const text = newText.trim();
      const index = state.messages.findIndex((item) => item.id === userMessageId);
      if (state.isStreaming || index < 0 || !text) return;
      // 改问题等于重开这一轮：该消息之后的旧回答全部作废
      set({ messages: [...state.messages.slice(0, index), createUserMessage(text)] });
      await runStream(text);
    },
    stopStreaming: async () => {
      const state = get();
      if (!state.isStreaming || !state.currentStreamHandle) return;
      set({ isStopping: true });
      const markStopped = (text?: string) =>
        patchDraft((current) => ({ ...current, status: 'STOPPED', statusText: text || current.statusText || '用户已停止生成' }));
      try {
        const result = await chatApi.stopSession(state.currentConversationId);
        markStopped(String(result?.message || ''));
      } catch (error) {
        set({ isStopping: false });
        toast({ title: '停止生成失败', description: errorMessage(error, '请稍后重试'), variant: 'error' });
        return;
      }
      state.currentStreamHandle.controller.abort();
    }
  };
});
