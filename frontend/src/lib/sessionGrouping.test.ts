import { describe, expect, it } from 'vitest';
import {
  formatRelativeTime,
  groupSessions,
  matchesSession,
  normalizeQuery,
  sessionTime,
} from './sessionGrouping';
import type { ChatSession } from '../types/api';

/** 用本地时间构造，避免测试结果被运行机器的时区改写 */
function at(year: number, month: number, day: number, hour = 12, minute = 0, second = 0): Date {
  return new Date(year, month - 1, day, hour, minute, second, 0);
}

function session(overrides: Partial<ChatSession> & { updatedAt?: string | null }): ChatSession {
  const base: ChatSession = {
    id: 1,
    conversationId: 'c-1',
    title: '会话',
    createdAt: at(2026, 3, 10, 9).toISOString(),
    chatMode: 'OPEN_CHAT',
    exchangeCount: 1,
    memorySummary: '',
    running: false,
    checkpointCount: 0,
    messageCount: 2,
    latestUserMessage: '',
    latestAssistantMessage: '',
    latestExchangeId: null,
    latestTurnStatus: 'SUCCESS',
    latestTurnErrorMessage: '',
    selectedDocumentId: '',
    selectedDocumentName: '',
    updatedAt: at(2026, 3, 10, 9).toISOString(),
    isPinned: false,
  };
  return { ...base, ...overrides };
}

const NOW = at(2026, 3, 10, 15, 0).getTime();

describe('normalizeQuery', () => {
  it('忽略大小写与全部空白', () => {
    expect(normalizeQuery('  Hello  World ')).toBe('helloworld');
    expect(normalizeQuery('季度\n报告')).toBe('季度报告');
  });
});

describe('sessionTime', () => {
  it('优先 updatedAt，缺失时退化到 createdAt', () => {
    const updated = at(2026, 3, 10, 9).toISOString();
    const created = at(2026, 3, 1, 9).toISOString();
    expect(sessionTime(session({ updatedAt: updated, createdAt: created }))).toBe(
      new Date(updated).getTime()
    );
    expect(sessionTime(session({ updatedAt: null, createdAt: created }))).toBe(
      new Date(created).getTime()
    );
  });

  it('非法时间退化到 createdAt，两者都非法时按未知时间处理（0）', () => {
    const created = at(2026, 3, 1, 9).toISOString();
    expect(sessionTime(session({ updatedAt: 'not-a-date', createdAt: created }))).toBe(
      new Date(created).getTime()
    );
    expect(sessionTime(session({ updatedAt: 'not-a-date', createdAt: 'also-bad' }))).toBe(0);
  });
});

describe('matchesSession', () => {
  it('空查询命中全部', () => {
    expect(matchesSession(session({}), '')).toBe(true);
    expect(matchesSession(session({}), '   ')).toBe(true);
  });

  it('大小写与空格容错', () => {
    const target = session({ title: 'Quarterly Report 2026' });
    expect(matchesSession(target, 'quarterly')).toBe(true);
    expect(matchesSession(target, '  QUARTERLYreport ')).toBe(true);
    expect(matchesSession(target, 'monthly')).toBe(false);
  });

  it('长标题不会被 22 字截断影响命中', () => {
    const target = session({ title: '一季度经营分析报告 —— 华东区域渠道复盘与改进建议' });
    expect(matchesSession(target, '改进建议')).toBe(true);
  });

  it('标题为空时按展示标题（首条提问）匹配', () => {
    const target = session({ title: '', latestUserMessage: '报销流程怎么走' });
    expect(matchesSession(target, '报销流程')).toBe(true);
  });
});

describe('groupSessions 分组', () => {
  it('固定顺序：置顶 → 今天 → 昨天 → 7 天内 → 更早，并带条数', () => {
    const sessions = [
      session({ conversationId: 'earlier', updatedAt: at(2026, 1, 5, 10).toISOString() }),
      session({ conversationId: 'today', updatedAt: at(2026, 3, 10, 14).toISOString() }),
      session({ conversationId: 'yesterday', updatedAt: at(2026, 3, 9, 10).toISOString() }),
      session({ conversationId: 'week', updatedAt: at(2026, 3, 5, 10).toISOString() }),
      session({
        conversationId: 'pinned',
        isPinned: true,
        updatedAt: at(2020, 5, 1, 10).toISOString(),
      }),
    ];

    const groups = groupSessions(sessions, '', NOW);
    expect(groups.map((g) => g.key)).toEqual(['pinned', 'today', 'yesterday', 'week', 'earlier']);
    expect(groups.map((g) => g.title)).toEqual(['置顶', '今天', '昨天', '7 天内', '更早']);
    expect(groups.map((g) => g.sessions.map((s) => s.conversationId))).toEqual([
      ['pinned'],
      ['today'],
      ['yesterday'],
      ['week'],
      ['earlier'],
    ]);
  });

  it('置顶但很旧的会话留在置顶组，不会被「更早」吞掉', () => {
    const groups = groupSessions(
      [session({ conversationId: 'old-pinned', isPinned: true, updatedAt: at(2019, 1, 1).toISOString() })],
      '',
      NOW
    );
    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBe('pinned');
  });

  it('组内按 updatedAt 倒序，与输入顺序无关', () => {
    const groups = groupSessions(
      [
        session({ conversationId: 'a', updatedAt: at(2026, 3, 10, 9).toISOString() }),
        session({ conversationId: 'c', updatedAt: at(2026, 3, 10, 14).toISOString() }),
        session({ conversationId: 'b', updatedAt: at(2026, 3, 10, 11).toISOString() }),
      ],
      '',
      NOW
    );
    expect(groups[0].sessions.map((s) => s.conversationId)).toEqual(['c', 'b', 'a']);
  });

  it('刚好 24 小时前算昨天，而不是今天或更早', () => {
    const exactlyOneDayAgo = at(2026, 3, 9, 15).toISOString();
    const groups = groupSessions([session({ updatedAt: exactlyOneDayAgo })], '', NOW);
    expect(groups.map((g) => g.key)).toEqual(['yesterday']);
  });

  it('跨年：12 月 31 日相对 1 月 1 日是昨天，更早的年份进「更早」', () => {
    const newYearNow = at(2026, 1, 1, 0, 30).getTime();
    const groups = groupSessions(
      [
        session({ conversationId: 'newyear', updatedAt: at(2025, 12, 31, 23, 0).toISOString() }),
        session({ conversationId: 'lastmonth', updatedAt: at(2025, 12, 20, 23, 0).toISOString() }),
        session({ conversationId: 'lastyear', updatedAt: at(2024, 6, 1, 10, 0).toISOString() }),
      ],
      '',
      newYearNow
    );
    const byKey = new Map(groups.map((g) => [g.key, g.sessions.map((s) => s.conversationId)]));
    expect(byKey.get('yesterday')).toEqual(['newyear']);
    expect(byKey.get('earlier')).toEqual(['lastmonth', 'lastyear']);
  });

  it('时间缺失的会话进「更早」，不会被丢掉', () => {
    const groups = groupSessions(
      [session({ conversationId: 'no-time', updatedAt: null, createdAt: null })],
      '',
      NOW
    );
    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBe('earlier');
  });

  it('没有会话时返回空数组（供空态使用）', () => {
    expect(groupSessions([], '', NOW)).toEqual([]);
  });
});

describe('groupSessions 搜索态', () => {
  it('只有一个「搜索结果」组，且置顶排在前面', () => {
    const groups = groupSessions(
      [
        session({ conversationId: 'a', title: '季度报告 A', updatedAt: at(2026, 3, 10, 14).toISOString() }),
        session({
          conversationId: 'pinned-b',
          title: '季度报告 B',
          isPinned: true,
          updatedAt: at(2026, 3, 10, 9).toISOString(),
        }),
        session({ conversationId: 'c', title: '无关内容' }),
      ],
      '季度报告',
      NOW
    );
    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBe('search');
    expect(groups[0].sessions.map((s) => s.conversationId)).toEqual(['pinned-b', 'a']);
  });

  it('没有命中时返回空数组（供「没有匹配的会话」空态使用）', () => {
    expect(groupSessions([session({ title: '季度报告' })], '年度总结', NOW)).toEqual([]);
  });
});

describe('formatRelativeTime', () => {
  it('一分钟内显示「刚刚」，含未来时间戳', () => {
    expect(formatRelativeTime(at(2026, 3, 10, 14, 59, 30).toISOString(), NOW)).toBe('刚刚');
    expect(formatRelativeTime(at(2026, 3, 10, 15, 5).toISOString(), NOW)).toBe('刚刚');
  });

  it('一小时内显示 N 分钟前', () => {
    expect(formatRelativeTime(at(2026, 3, 10, 14, 55).toISOString(), NOW)).toBe('5 分钟前');
    expect(formatRelativeTime(at(2026, 3, 10, 14, 1).toISOString(), NOW)).toBe('59 分钟前');
  });

  it('今天更早的时间显示「今天 HH:mm」，补零', () => {
    expect(formatRelativeTime(at(2026, 3, 10, 9, 5).toISOString(), NOW)).toBe('今天 09:05');
  });

  it('昨天显示「昨天 HH:mm」', () => {
    expect(formatRelativeTime(at(2026, 3, 9, 9, 5).toISOString(), NOW)).toBe('昨天 09:05');
  });

  it('同年更早显示 M月D日，跨年补年份', () => {
    expect(formatRelativeTime(at(2026, 1, 8, 10, 0).toISOString(), NOW)).toBe('1月8日');
    expect(formatRelativeTime(at(2025, 1, 8, 10, 0).toISOString(), NOW)).toBe('2025年1月8日');
  });

  it('缺失或非法时间返回空串，交给调用方决定占位', () => {
    expect(formatRelativeTime(null, NOW)).toBe('');
    expect(formatRelativeTime('oops', NOW)).toBe('');
  });
});
