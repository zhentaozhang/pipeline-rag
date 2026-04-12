export function latestExchangeQuestion(session: any): string {
  const exchanges = session?.exchanges || [];
  for (let index = exchanges.length - 1; index >= 0; index -= 1) {
    const question = exchanges[index]?.question;
    if (question) {
      return question;
    }
  }
  return '';
}

export function latestExchangeAnswer(session: any): string {
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

export function sessionTitle(session: any): string {
  // 优先使用后端 AI 生成的标题
  if (session.title && session.title !== '新的对话') {
    return truncate(session.title, 22);
  }
  const latestUserMessage = session.latestUserMessage || latestExchangeQuestion(session);
  const latestAssistantMessage = session.latestAssistantMessage || latestExchangeAnswer(session);
  return truncate(latestUserMessage || latestAssistantMessage || '新的对话', 22);
}

export function sortSessions(sessions: any[]): any[] {
  return [...sessions].sort((left, right) => {
    const leftTime = new Date(left.updatedAt || left.editTime || left.createTime || 0).getTime();
    const rightTime = new Date(right.updatedAt || right.editTime || right.createTime || 0).getTime();
    return rightTime - leftTime;
  });
}
