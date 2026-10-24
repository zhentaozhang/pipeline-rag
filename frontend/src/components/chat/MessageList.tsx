import React from 'react';
import type { ExchangeReference } from '../../types/api';
import { useChatStore } from '../../store/chatStore';
import { ChatMessageItem } from './ChatMessageItem';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  thinkingSteps?: string[];
  references?: ExchangeReference[];
  recommendations?: string[];
  status?: string;
  statusText?: string;
  errorMessage?: string;
  routeExplain?: Record<string, unknown> | null;
  exchangeId?: number;
  createdAt?: string;
  updatedAt?: string;
}

/**
 * 正在流式生成的那一条单独订阅 streamingDraft。
 * 这样每来一个 token 只重渲染这一个组件，历史消息的 props 引用不变、React.memo 全部命中。
 */
const StreamingDraftItem: React.FC = () => {
  const draft = useChatStore((state) => state.streamingDraft);
  if (!draft) return null;
  return <ChatMessageItem key={draft.id} message={draft} />;
};

const MessageListImpl: React.FC<{ messages: Message[] }> = ({ messages }) => (
  <div
    role="log"
    aria-live="polite"
    aria-relevant="additions text"
    aria-label="对话消息"
    className="flex flex-col gap-6"
  >
    {messages.map((message) => (
      <ChatMessageItem key={message.id} message={message} />
    ))}
    <StreamingDraftItem />
  </div>
);

export const MessageList = React.memo(MessageListImpl);
