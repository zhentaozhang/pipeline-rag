import { describe, it, expect, vi, beforeEach } from 'vitest';

// 流式接口是同步返回 { controller, done }，测试里要能手动决定"本轮什么时候结束"
interface StreamCall {
  payload: { question: string; conversationId: string; chatMode: string; selectedDocumentId: string | null };
  emit: (event: Record<string, unknown>) => void;
  finish: (error?: Error) => void;
}

const mocks = vi.hoisted(() => ({
  openStream: vi.fn(),
  listSessions: vi.fn(),
  listKnowledgeDocumentOptions: vi.fn(),
  getSession: vi.fn(),
  deleteSession: vi.fn(),
  renameSession: vi.fn(),
  pinSession: vi.fn(),
  stopSession: vi.fn(),
  submitFeedback: vi.fn(),
  queryKnowledgeRouteTracePage: vi.fn(),
  toast: vi.fn()
}));

vi.mock('../lib/api', () => ({
  chatApi: {
    openStream: mocks.openStream,
    listSessions: mocks.listSessions,
    listKnowledgeDocumentOptions: mocks.listKnowledgeDocumentOptions,
    getSession: mocks.getSession,
    deleteSession: mocks.deleteSession,
    renameSession: mocks.renameSession,
    pinSession: mocks.pinSession,
    stopSession: mocks.stopSession,
    submitFeedback: mocks.submitFeedback
  },
  manageApi: { queryKnowledgeRouteTracePage: mocks.queryKnowledgeRouteTracePage },
  createConversationId: () => 'conv-new'
}));

vi.mock('../lib/toast', () => ({ toast: mocks.toast }));

import { CHAT_MODES, useChatStore } from './chatStore';
import type { Message } from '../components/chat/MessageList';

let streamCalls: StreamCall[] = [];

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const state = () => useChatStore.getState();

function userMessage(id: string, content: string): Message {
  return { id, role: 'user', content };
}
function assistantMessage(id: string, content: string, status = 'COMPLETED'): Message {
  return { id, role: 'assistant', content, status };
}

beforeEach(() => {
  streamCalls = [];
  vi.clearAllMocks();
  mocks.listSessions.mockResolvedValue([]);
  mocks.listKnowledgeDocumentOptions.mockResolvedValue([]);
  mocks.openStream.mockImplementation((payload: StreamCall['payload'], handlers: { onEvent?: (e: Record<string, unknown>) => void }) => {
    const controller = new AbortController();
    let resolveDone: () => void = () => {};
    let rejectDone: (error: Error) => void = () => {};
    const done = new Promise<void>((resolve, reject) => {
      resolveDone = resolve;
      rejectDone = reject;
    });
    streamCalls.push({
      payload,
      emit: (event) => handlers.onEvent?.(event),
      finish: (error) => (error ? rejectDone(error) : resolveDone())
    });
    return { controller, done };
  });
  useChatStore.setState({
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
    pageErrorScope: ''
  });
});

describe('排队发送（P1-1）', () => {
  it('流式期间提交的问题排到队列，并在本轮 done 后自动发出', async () => {
    const first = state().sendMessage('第一个问题');
    await flush();
    expect(state().isStreaming).toBe(true);
    expect(state().messages.map((item) => item.content)).toEqual(['第一个问题']);

    streamCalls[0].emit({ type: 'text', content: '第一段答案' });
    expect(state().streamingDraft?.content).toBe('第一段答案');

    // 流式中再次提交：只进队列，不覆盖正在流的那条
    await state().sendMessage('第二个问题');
    expect(state().pendingQuestion).toBe('第二个问题');
    expect(state().streamingDraft?.content).toBe('第一段答案');
    expect(streamCalls).toHaveLength(1);

    streamCalls[0].finish();
    await first;
    await flush();

    expect(streamCalls).toHaveLength(2);
    expect(streamCalls[1].payload.question).toBe('第二个问题');
    expect(state().pendingQuestion).toBe('');
    expect(state().messages.map((item) => item.content)).toEqual(['第一个问题', '第一段答案', '第二个问题']);
  });

  it('取消排队后本轮结束不再自动发送', async () => {
    const first = state().sendMessage('问题一');
    await flush();
    await state().sendMessage('问题二');
    expect(state().pendingQuestion).toBe('问题二');

    state().clearPendingQuestion();
    streamCalls[0].finish();
    await first;
    await flush();

    expect(streamCalls).toHaveLength(1);
    expect(state().isStreaming).toBe(false);
  });
});

describe('regenerate / retryLast / editAndResend（P1-2）', () => {
  it('regenerate 丢弃该回答及其后内容并用原来的问题重发', async () => {
    useChatStore.setState({
      messages: [
        userMessage('exchange-1-user', '问题一'),
        assistantMessage('exchange-1-assistant', '答案一'),
        userMessage('exchange-2-user', '问题二'),
        assistantMessage('exchange-2-assistant', '答案二')
      ]
    });

    const pending = state().regenerate('exchange-1-assistant');
    await flush();

    // 目标回答之后的对话全部作废，只留下那一轮的问题
    expect(state().messages.map((item) => item.content)).toEqual(['问题一']);
    expect(streamCalls[0].payload.question).toBe('问题一');

    streamCalls[0].finish();
    await pending;
    expect(state().messages.map((item) => item.content)).toEqual(['问题一', '']);
  });

  it('editAndResend 用新问题替换原问题并丢弃其后的旧回答', async () => {
    useChatStore.setState({
      messages: [
        userMessage('exchange-1-user', '旧问题'),
        assistantMessage('exchange-1-assistant', '旧答案'),
        userMessage('exchange-2-user', '保留的问题')
      ]
    });

    const pending = state().editAndResend('exchange-1-user', '改写后的问题');
    await flush();

    expect(state().messages.map((item) => item.content)).toEqual(['改写后的问题']);
    expect(streamCalls[0].payload.question).toBe('改写后的问题');
    streamCalls[0].finish();
    await pending;
  });

  it('retryLast 重试最后一条助手消息', async () => {
    useChatStore.setState({
      messages: [
        userMessage('exchange-1-user', '问题一'),
        assistantMessage('exchange-1-assistant', '答案一', 'FAILED'),
        userMessage('exchange-2-user', '问题二'),
        assistantMessage('exchange-2-assistant', '答案二', 'FAILED')
      ]
    });

    const pending = state().retryLast();
    await flush();
    expect(streamCalls[0].payload.question).toBe('问题二');
    streamCalls[0].finish();
    await pending;
  });
});

describe('错误分级互不污染（P1-3）', () => {
  it('消息级失败只标记这条回答，不写页面级错误也不弹 toast', async () => {
    const pending = state().sendMessage('会失败的问题');
    await flush();
    streamCalls[0].finish(new Error('模型崩了'));
    await pending;

    const last = state().messages[state().messages.length - 1];
    expect(last.role).toBe('assistant');
    expect(last.status).toBe('FAILED');
    expect(last.errorMessage).toContain('模型崩了');
    expect(state().pageError).toBe('');
    expect(mocks.toast).not.toHaveBeenCalled();
  });

  it('页面级失败写 pageError + scope，并且不降级成 toast', async () => {
    mocks.listSessions.mockRejectedValue(new Error('列表接口 500'));
    await state().refreshSessions();

    expect(state().pageError).toContain('列表接口 500');
    expect(state().pageErrorScope).toBe('sessions');
    expect(mocks.toast).not.toHaveBeenCalled();
  });

  it('操作级失败走 toast 并回滚，不写 pageError', async () => {
    useChatStore.setState({
      sessions: [{ conversationId: 'c1', title: '旧标题', isPinned: false } as never]
    });
    mocks.renameSession.mockRejectedValue(new Error('重命名接口 403'));

    await state().renameSession('c1', '新标题');

    expect(state().sessions[0].title).toBe('旧标题');
    expect(state().pageError).toBe('');
    expect(mocks.toast).toHaveBeenCalledWith(
      expect.objectContaining({ variant: 'error', title: '重命名失败' })
    );
  });

  it('置顶失败回滚 isPinned', async () => {
    useChatStore.setState({
      sessions: [{ conversationId: 'c1', title: '标题', isPinned: false } as never]
    });
    mocks.pinSession.mockRejectedValue(new Error('置顶接口 500'));

    await state().pinSession('c1', true);

    expect(state().sessions[0].isPinned).toBe(false);
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({ title: '置顶失败' }));
  });
});

describe('会话切换（P1-4）', () => {
  it('新对话清空文档选择并释放会话 id', () => {
    useChatStore.setState({
      currentConversationId: 'c1',
      selectedDocumentId: 'doc-1',
      selectedDocumentName: '部署手册',
      messages: [userMessage('u1', '问题')]
    });

    state().startNewConversation();

    expect(state().currentConversationId).toBe('');
    expect(state().selectedDocumentId).toBe('');
    expect(state().selectedDocumentName).toBe('');
    expect(state().messages).toEqual([]);
  });

  it('renameSession / pinSession 先改本地再请求', async () => {
    useChatStore.setState({
      sessions: [{ conversationId: 'c1', title: '旧标题', isPinned: false } as never]
    });
    let release: () => void = () => {};
    mocks.renameSession.mockImplementation(() => new Promise<void>((resolve) => { release = resolve; }));
    mocks.pinSession.mockResolvedValue({});

    const renaming = state().renameSession('c1', '新标题');
    // 请求还没回来，列表里已经是新标题
    expect(state().sessions[0].title).toBe('新标题');

    await state().pinSession('c1', true);
    expect(state().sessions[0].isPinned).toBe(true);

    release();
    await renaming;
  });
});
