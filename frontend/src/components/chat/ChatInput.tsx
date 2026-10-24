import React, { useEffect, useState } from 'react';
import { ArrowUp, Square } from 'lucide-react';
import TextareaAutosize from 'react-textarea-autosize';
import { useShallow } from 'zustand/react/shallow';
import { Button } from '../ui/Button';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { IconButton } from '../ui/IconButton';
import { CHAT_MODES, useChatStore, type ChatMode } from '../../store/chatStore';

const MODE_ORDER: ChatMode[] = [CHAT_MODES.DOCUMENT, CHAT_MODES.AUTO_DOCUMENT, CHAT_MODES.OPEN_CHAT];

const MODE_LABEL: Record<ChatMode, string> = {
  DOCUMENT: '文档问答',
  AUTO_DOCUMENT: '自动选文档',
  OPEN_CHAT: '开放对话'
};

const PLACEHOLDER: Record<ChatMode, string> = {
  DOCUMENT: '就这篇文档提问，回答会附上原文出处',
  AUTO_DOCUMENT: '问点什么，我会先检索知识库再回答',
  OPEN_CHAT: '直接对话，不检索知识库'
};

export const ChatInput: React.FC = () => {
  const {
    sendMessage,
    isStreaming,
    isStopping,
    stopStreaming,
    chatMode,
    setChatMode,
    documentOptions,
    selectedDocumentId,
    setSelectedDocumentId,
    refreshDocumentOptions,
    startNewConversation,
    pendingQuestion,
    clearPendingQuestion,
    messageCount
  } = useChatStore(
    useShallow((state) => ({
      sendMessage: state.sendMessage,
      isStreaming: state.isStreaming,
      isStopping: state.isStopping,
      stopStreaming: state.stopStreaming,
      chatMode: state.chatMode,
      setChatMode: state.setChatMode,
      documentOptions: state.documentOptions,
      selectedDocumentId: state.selectedDocumentId,
      setSelectedDocumentId: state.setSelectedDocumentId,
      refreshDocumentOptions: state.refreshDocumentOptions,
      startNewConversation: state.startNewConversation,
      pendingQuestion: state.pendingQuestion,
      clearPendingQuestion: state.clearPendingQuestion,
      messageCount: state.messages.length
    }))
  );

  const [input, setInput] = useState('');
  // 切换模式/文档会清空对话，先落进这两个 state 等用户确认
  const [pendingMode, setPendingMode] = useState<ChatMode | null>(null);
  const [pendingDocumentId, setPendingDocumentId] = useState<string | null>(null);

  useEffect(() => {
    void refreshDocumentOptions();
  }, [refreshDocumentOptions]);

  const hasConversation = messageCount > 0;

  const handleSubmit = () => {
    const text = input.trim();
    if (!text) return;
    setInput('');
    // 流式中提交不会打断当前回答：store 会把它排进 pendingQuestion，本轮结束后自动发出
    void sendMessage(text);
  };

  const requestMode = (mode: ChatMode) => {
    if (mode === chatMode) return;
    if (hasConversation) {
      setPendingMode(mode);
      return;
    }
    setChatMode(mode);
  };

  const requestDocument = (documentId: string) => {
    if (documentId === selectedDocumentId) return;
    if (documentId && hasConversation) {
      setPendingDocumentId(documentId);
      return;
    }
    setSelectedDocumentId(documentId);
  };

  return (
    <div className="flex w-full flex-col items-center gap-2">
      {pendingQuestion ? (
        <div
          role="status"
          className="flex w-full items-center gap-2 rounded-lg border border-border/60 bg-secondary/50 px-3 py-1.5 text-xs text-foreground"
        >
          <span className="min-w-0 flex-1 truncate">
            已排队：{pendingQuestion}
            <span className="text-muted-foreground"> · 本轮结束后自动发送</span>
          </span>
          <Button size="sm" variant="ghost" onClick={clearPendingQuestion}>
            取消排队
          </Button>
        </div>
      ) : null}

      <div className="hidden w-full flex-wrap items-center gap-1 xl:flex">
        {MODE_ORDER.map((mode) => (
          <button
            key={mode}
            type="button"
            aria-pressed={chatMode === mode}
            disabled={isStreaming}
            onClick={() => requestMode(mode)}
            className={`rounded-full px-4 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:opacity-50 ${
              chatMode === mode
                ? 'bg-primary/10 text-primary'
                : 'text-muted-foreground hover:bg-secondary/80'
            }`}
          >
            {MODE_LABEL[mode]}
          </button>
        ))}
      </div>

      {chatMode === CHAT_MODES.DOCUMENT ? (
        <div className="flex w-full items-center gap-2">
          <label htmlFor="chat-document-select" className="sr-only">
            选择要提问的文档
          </label>
          <select
            id="chat-document-select"
            value={selectedDocumentId}
            onChange={(event) => requestDocument(event.target.value)}
            className="max-w-full rounded-md border border-border/60 bg-background px-2 py-1 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="">-- 选择文档 --</option>
            {documentOptions.map((option) => (
              <option key={option.documentId} value={option.documentId}>
                {option.documentName}
              </option>
            ))}
          </select>
          {!selectedDocumentId ? (
            <span className="text-2xs text-warning">文档问答需要先选一篇文档</span>
          ) : null}
        </div>
      ) : null}

      <form
        className="relative w-full rounded-2xl border border-border/50 bg-secondary/30 backdrop-blur-xl transition-colors focus-within:border-border"
        onSubmit={(event) => {
          event.preventDefault();
          handleSubmit();
        }}
      >
        <label htmlFor="chat-input" className="sr-only">
          输入你的问题
        </label>
        <TextareaAutosize
          id="chat-input"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              handleSubmit();
            }
          }}
          minRows={1}
          maxRows={8}
          placeholder={isStreaming ? '正在生成回答…可以直接输入，发送后排在本轮之后' : PLACEHOLDER[chatMode]}
          className="min-h-[52px] w-full resize-none bg-transparent px-4 py-3 pr-32 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
        />
        <div className="absolute bottom-3 right-3 flex items-center gap-1">
          {isStreaming ? (
            <Button size="sm" variant="outline" loading={isStopping} onClick={() => void stopStreaming()}>
              {!isStopping ? <Square size={12} aria-hidden="true" /> : null}
              停止生成
            </Button>
          ) : null}
          <IconButton
            label="发送消息"
            hint="发送"
            icon={<ArrowUp size={16} />}
            size="md"
            variant="solid"
            disabled={!input.trim()}
            onClick={handleSubmit}
          />
        </div>
      </form>

      <ConfirmDialog
        open={pendingMode !== null}
        title="切换对话模式？"
        description={`切换后当前对话将清空，历史消息仍可在左侧会话列表里找回。新问题会以「${
          pendingMode ? MODE_LABEL[pendingMode] : ''
        }」模式发起。`}
        confirmLabel="切换并新建对话"
        onConfirm={() => {
          if (pendingMode) {
            startNewConversation();
            setChatMode(pendingMode);
          }
          setPendingMode(null);
        }}
        onCancel={() => setPendingMode(null)}
      />

      <ConfirmDialog
        open={pendingDocumentId !== null}
        title="更换提问文档？"
        description="切换后当前对话将清空，避免把两篇文档的答案混在同一条会话里。"
        confirmLabel="切换并新建对话"
        onConfirm={() => {
          if (pendingDocumentId) {
            startNewConversation();
            setSelectedDocumentId(pendingDocumentId);
          }
          setPendingDocumentId(null);
        }}
        onCancel={() => setPendingDocumentId(null)}
      />
    </div>
  );
};
