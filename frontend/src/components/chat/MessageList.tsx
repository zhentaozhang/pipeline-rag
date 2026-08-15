import React from 'react';
import { ChatMessageItem } from './ChatMessageItem';
import type { ExchangeReference } from '../../types/api';

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
  createdAt?: string;
  updatedAt?: string;
}

interface MessageListProps {
  messages: Message[];
}

export const MessageList: React.FC<MessageListProps> = ({ messages }) => {
  return (
    <>
      {messages.map((message) => (
        <ChatMessageItem key={message.id} message={message} />
      ))}
    </>
  );
};
