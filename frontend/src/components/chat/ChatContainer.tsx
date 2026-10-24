import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowDown, FileText, Layers, MessageCircle, PanelLeft } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import { Alert } from '../ui/Alert';
import { Button } from '../ui/Button';
import { EmptyState } from '../ui/EmptyState';
import { IconButton } from '../ui/IconButton';
import { Skeleton } from '../ui/Skeleton';
import { ChatInput } from './ChatInput';
import { MessageList } from './MessageList';
import { chatApi } from '../../lib/api';
import { CHAT_MODES, useChatStore, type ChatMode } from '../../store/chatStore';

interface ChatContainerProps {
  sidebarOpen: boolean;
  toggleSidebar: () => void;
}

const STICK_THRESHOLD_PX = 80;

type ConnectionStatus = 'checking' | 'connected' | 'disconnected';

const CONNECTION_LABEL: Record<ConnectionStatus, string> = {
  checking: '连接中',
  connected: '已连接',
  disconnected: '未连接'
};

const CONNECTION_DOT: Record<ConnectionStatus, string> = {
  checking: 'bg-warning',
  connected: 'bg-success shadow-[0_0_6px_var(--color-success)]',
  disconnected: 'bg-destructive'
};

interface EmptyCopy {
  icon: React.ReactNode;
  title: string;
  description: string;
  prompts: string[];
}

/** 三种模式问的是不同问题，引导语不能共用一套（原来的三个硬编码 chip 对哪种模式都只说半句话） */
function getEmptyCopy(chatMode: ChatMode, documentName: string): EmptyCopy {
  if (chatMode === CHAT_MODES.DOCUMENT) {
    return {
      icon: <FileText size={28} aria-hidden="true" />,
      title: documentName ? `正在就《${documentName}》提问` : '文档问答：先选一篇文档',
      description: documentName
        ? '回答只依据这篇文档的原文片段，并给出可以展开原文的引用。'
        : '在输入框左侧选择文档，再针对它的内容提问，答案会附上原文出处。',
      prompts: ['这篇文档的核心结论是什么？', '把文档里的关键指标整理成表格', '文档里有哪些限制条件和风险？']
    };
  }
  if (chatMode === CHAT_MODES.OPEN_CHAT) {
    return {
      icon: <MessageCircle size={28} aria-hidden="true" />,
      title: '开放对话',
      description: '不检索知识库，直接由模型回答，适合推理、改写、写代码这类问题。',
      prompts: ['帮我把这段会议记录改写成要点清单', '解释一下 RAG 里的重排（rerank）在做什么', '给我一个可以复现问题的排查顺序']
    };
  }
  return {
    icon: <Layers size={28} aria-hidden="true" />,
    title: '自动检索知识库后回答',
    description: '我会先在知识库里检索相关片段，再结合片段作答，并标出每条结论的引用来源。',
    prompts: ['我们对外发布的部署流程分为哪几步？', '整理一下最近变更的制度与生效时间', '这两个版本的差异对我有什么影响？']
  };
}

export const ChatContainer: React.FC<ChatContainerProps> = ({ sidebarOpen, toggleSidebar }) => {
  const {
    messages,
    isStreaming,
    loadingConversation,
    pageError,
    pageErrorScope,
    retryPageError,
    chatMode,
    selectedDocumentName,
    sendMessage,
    startNewConversation
  } = useChatStore(
    useShallow((state) => ({
      messages: state.messages,
      isStreaming: state.isStreaming,
      loadingConversation: state.loadingConversation,
      pageError: state.pageError,
      pageErrorScope: state.pageErrorScope,
      retryPageError: state.retryPageError,
      chatMode: state.chatMode,
      selectedDocumentName: state.selectedDocumentName,
      sendMessage: state.sendMessage,
      startNewConversation: state.startNewConversation
    }))
  );

  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);
  const [showJump, setShowJump] = useState(false);
  const [connection, setConnection] = useState<ConnectionStatus>('checking');

  const scrollToBottom = useCallback(() => {
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, []);

  const handleScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    const pinned = element.scrollHeight - element.scrollTop - element.clientHeight < STICK_THRESHOLD_PX;
    pinnedRef.current = pinned;
    setShowJump(!pinned);
  };

  // 流式 token 只改 store 里的 streamingDraft，用 subscribe 而不是选择器订阅：
  // 需要的是"动一下滚动条"，不应该为了滚动让整个消息列表每来一个 token 重渲染一次
  useEffect(() => {
    return useChatStore.subscribe(() => {
      if (pinnedRef.current) scrollToBottom();
    });
  }, [scrollToBottom]);

  // 新消息到达后回到最新位置。showJump 不在这里复位——滚动本身会触发 handleScroll，
  // 由事件回调更新状态，避免 effect 里同步 setState 造成的级联渲染。
  useEffect(() => {
    pinnedRef.current = true;
    scrollToBottom();
  }, [messages.length, scrollToBottom]);

  useEffect(() => {
    let alive = true;
    const check = async () => {
      if (document.visibilityState !== 'visible') return;
      try {
        const ok = await chatApi.checkConnection();
        if (alive) setConnection(ok ? 'connected' : 'disconnected');
      } catch {
        if (alive) setConnection('disconnected');
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), 30000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  const emptyCopy = getEmptyCopy(chatMode, selectedDocumentName);
  const isEmpty = messages.length === 0 && !loadingConversation && !pageError;

  return (
    <div className="relative flex h-full flex-1 flex-col overflow-hidden">
      <header className="pointer-events-none absolute inset-x-0 top-0 z-10 flex h-14 items-center justify-between bg-gradient-to-b from-background via-background/80 to-transparent px-4">
        <div className="pointer-events-auto flex items-center gap-2">
          {!sidebarOpen ? (
            <IconButton label="展开侧边栏" icon={<PanelLeft size={18} />} size="md" onClick={toggleSidebar} />
          ) : null}
          <span className="font-heading text-sm font-medium text-foreground">Pipeline RAG</span>
        </div>
        <div className="pointer-events-auto flex items-center gap-1.5 text-2xs text-muted-foreground" role="status">
          <span className={`h-1.5 w-1.5 rounded-full ${CONNECTION_DOT[connection]}`} aria-hidden="true" />
          {CONNECTION_LABEL[connection]}
        </div>
      </header>

      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-20 pb-40">
          {pageError ? (
            <Alert
              variant="destructive"
              title={pageErrorScope === 'conversation' ? '会话加载失败' : '会话列表加载失败'}
              action={
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => void retryPageError()}>
                    重试
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      startNewConversation();
                      void retryPageError();
                    }}
                  >
                    新建对话
                  </Button>
                </div>
              }
            >
              {pageErrorScope === 'conversation'
                ? `${pageError} 链接里的会话可能已被删除，可以新建一个对话继续。`
                : pageError}
            </Alert>
          ) : null}

          {loadingConversation ? (
            <div aria-busy="true" className="space-y-3">
              <p className="text-sm text-muted-foreground">正在加载会话内容…</p>
              <Skeleton className="h-4 w-2/3" />
              <Skeleton lines={4} />
            </div>
          ) : null}

          {isEmpty ? (
            <EmptyState
              icon={emptyCopy.icon}
              title={emptyCopy.title}
              description={emptyCopy.description}
              action={
                <div className="flex flex-wrap justify-center gap-2">
                  {emptyCopy.prompts.map((prompt) => (
                    <Button
                      key={prompt}
                      size="sm"
                      variant="outline"
                      className="rounded-full font-normal"
                      disabled={isStreaming}
                      onClick={() => void sendMessage(prompt)}
                    >
                      {prompt}
                    </Button>
                  ))}
                </div>
              }
            />
          ) : null}

          {messages.length > 0 ? <MessageList messages={messages} /> : null}
        </div>
      </div>

      {showJump ? (
        <button
          type="button"
          onClick={() => {
            pinnedRef.current = true;
            setShowJump(false);
            scrollToBottom();
          }}
          aria-label="回到最新消息"
          className="absolute bottom-32 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-border/50 bg-background/90 px-3 py-1.5 text-xs text-foreground shadow-md backdrop-blur transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowDown size={14} aria-hidden="true" />
          回到最新
        </button>
      ) : null}

      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-background via-background/95 to-transparent p-4">
        <div className="mx-auto w-full max-w-3xl">
          <ChatInput />
          <p className="mt-2 hidden text-center text-2xs text-muted-foreground md:block">
            回答由模型生成，可能不准确；请点开引用核对原文。
          </p>
        </div>
      </div>
    </div>
  );
};
