import type { ChatSession, SessionDetail } from '../types/api';
import { truncate } from './utils';

export function latestExchangeQuestion(session?: SessionDetail | null): string {
  const exchanges = session?.exchanges || [];
  for (let index = exchanges.length - 1; index >= 0; index -= 1) {
    const question = exchanges[index]?.question;
    if (question) {
      return question;
    }
  }
  return '';
}

export function latestExchangeAnswer(session?: SessionDetail | null): string {
  const exchanges = session?.exchanges || [];
  for (let index = exchanges.length - 1; index >= 0; index -= 1) {
    const answer = exchanges[index]?.answer;
    if (answer) {
      return answer;
    }
  }
  return '';
}

export interface SessionTitleOptions {
  /** 拿不到任何文本时的兜底文案（聊天侧“新的对话”，后台侧“未命名会话”） */
  fallback?: string;
  /** 截断长度，聊天侧 22 字、后台列表 28 字 */
  maxLength?: number;
}

/**
 * 会话标题的唯一实现：
 * 后端 AI 标题优先 → 最近一条用户提问 → 最近一条回答 → 兜底文案。
 */
export function sessionTitle(
  session?: ChatSession | SessionDetail | null,
  options: SessionTitleOptions = {},
): string {
  const fallback = options.fallback || '新的对话';
  const maxLength = options.maxLength || 22;
  if (!session) {
    return fallback;
  }
  if (session.title && session.title !== '新的对话') {
    return truncate(session.title, maxLength);
  }
  const latestUserMessage =
    session.latestUserMessage || ('exchanges' in session ? latestExchangeQuestion(session as SessionDetail) : '');
  const latestAssistantMessage =
    session.latestAssistantMessage || ('exchanges' in session ? latestExchangeAnswer(session as SessionDetail) : '');
  return truncate(latestUserMessage || latestAssistantMessage || fallback, maxLength);
}
