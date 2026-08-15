import type { ChatSession, SessionDetail } from '../types/api';

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

export function truncate(value: string, maxLength: number): string {
  if (!value) {
    return '';
  }
  return value.length > maxLength ? `${value.slice(0, maxLength)}...` : value;
}

export function sessionTitle(session?: ChatSession | SessionDetail | null): string {
  if (!session) {
    return '新的对话';
  }
  // 优先使用后端 AI 生成的标题
  if (session.title && session.title !== '新的对话') {
    return truncate(session.title, 22);
  }
  const latestUserMessage =
    session.latestUserMessage || ('exchanges' in session ? latestExchangeQuestion(session as SessionDetail) : '');
  const latestAssistantMessage =
    session.latestAssistantMessage || ('exchanges' in session ? latestExchangeAnswer(session as SessionDetail) : '');
  return truncate(latestUserMessage || latestAssistantMessage || '新的对话', 22);
}

interface SortableSession {
  updatedAt?: string | null;
  editTime?: string | null;
  createTime?: string | null;
}

function sessionTime(s: SortableSession): number {
  return new Date(s.updatedAt || s.editTime || s.createTime || 0).getTime();
}

export function sortSessions<T extends SortableSession>(sessions: T[]): T[] {
  return [...sessions].sort((left, right) => sessionTime(right) - sessionTime(left));
}
