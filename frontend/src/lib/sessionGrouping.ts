import type { ChatSession, SessionDetail } from '../types/api';
import { sessionTitle } from './sessionUtils';

/**
 * 会话侧栏的分组与时间展示。
 *
 * 这里全部是纯函数：给定「会话列表 + 搜索词 + 当前时间」就能算出要渲染什么，
 * 因此边界（跨年、刚好 24 小时、置顶但很旧、空标题）都能用单测钉住，
 * 不必渲染整个侧栏去验证。
 */

export type SessionGroupKey = 'search' | 'pinned' | 'today' | 'yesterday' | 'week' | 'earlier';

export interface SessionGroup {
  key: SessionGroupKey;
  title: string;
  sessions: ChatSession[];
}

/** 组的顺序写死在这里：置顶永远在最前，其后按时间从近到远。 */
export const SESSION_GROUP_ORDER: readonly SessionGroupKey[] = [
  'pinned',
  'today',
  'yesterday',
  'week',
  'earlier',
];

export const SESSION_GROUP_LABEL: Record<SessionGroupKey, string> = {
  search: '搜索结果',
  pinned: '置顶',
  today: '今天',
  yesterday: '昨天',
  week: '7 天内',
  earlier: '更早',
};

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;

/** 后端时间可能缺失或格式异常，统一退化到 0（= 未知时间，归入「更早」）。 */
export function parseSessionTime(value?: string | null): number {
  if (!value) return 0;
  const ts = new Date(value).getTime();
  return Number.isNaN(ts) ? 0 : ts;
}

/**
 * 排序与分组用的时间戳：优先 updatedAt（最近一次问答），
 * 新建的空会话只有 createdAt，此时两者等价。
 */
export function sessionTime(session: ChatSession | SessionDetail): number {
  return parseSessionTime(session.updatedAt) || parseSessionTime(session.createdAt);
}

function startOfDay(timestamp: number): number {
  const date = new Date(timestamp);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

/**
 * 自然日之差，而不是「毫秒差 / 24 小时」：
 * 23:59 与次日 00:01 只差 2 分钟，但用户心里那是「昨天」和「今天」。
 * round 而不是 floor，是为了让夏令时切换日（23h / 25h）仍然算 1 天。
 */
function dayOffset(timestamp: number, now: number): number {
  return Math.round((startOfDay(now) - startOfDay(timestamp)) / 86_400_000);
}

function bucketOf(session: ChatSession, now: number): SessionGroupKey {
  if (session.isPinned) return 'pinned';
  const ts = sessionTime(session);
  if (ts <= 0) return 'earlier';
  const offset = dayOffset(ts, now);
  if (offset <= 0) return 'today'; // 含未来时间戳：时钟漂移的会话仍然看得见
  if (offset === 1) return 'yesterday';
  if (offset < 7) return 'week';
  return 'earlier';
}

/** 去掉全部空白并转小写：标题里的换行、多余空格、大小写都不该影响命中。 */
export function normalizeQuery(text: string): string {
  return text.toLowerCase().replace(/\s+/g, '');
}

/**
 * 可搜索文本取「原始标题 + 展示标题」。
 * 列表里展示的是截断到 22 字的标题，只拿它匹配会让长标题的后半截搜不到；
 * 而原始标题为空时，展示标题会退化成首条提问，这也正是用户看到的文字。
 */
function searchableText(session: ChatSession | SessionDetail): string {
  const display = sessionTitle(session);
  return [session.title, display].filter(Boolean).join(' ');
}

export function matchesSession(session: ChatSession | SessionDetail, query: string): boolean {
  const needle = normalizeQuery(query);
  if (!needle) return true;
  return normalizeQuery(searchableText(session)).includes(needle);
}

function compareSessions(left: ChatSession, right: ChatSession): number {
  const pinnedDiff = Number(Boolean(right.isPinned)) - Number(Boolean(left.isPinned));
  if (pinnedDiff !== 0) return pinnedDiff;
  return sessionTime(right) - sessionTime(left);
}

/**
 * 生成侧栏要渲染的分组。
 * 有搜索词时只返回一个「搜索结果」组（命中项里置顶仍然排前面），
 * 这样搜索态和分组态共用一套渲染逻辑，不需要两套列表。
 */
export function groupSessions(
  sessions: ChatSession[],
  query = '',
  now: number = Date.now()
): SessionGroup[] {
  const sorted = [...sessions].sort(compareSessions);
  const needle = normalizeQuery(query);

  if (needle) {
    const hits = sorted.filter((session) => matchesSession(session, needle));
    return hits.length > 0
      ? [{ key: 'search', title: SESSION_GROUP_LABEL.search, sessions: hits }]
      : [];
  }

  const buckets = new Map<SessionGroupKey, ChatSession[]>();
  for (const session of sorted) {
    const key = bucketOf(session, now);
    const bucket = buckets.get(key);
    if (bucket) bucket.push(session);
    else buckets.set(key, [session]);
  }

  const groups: SessionGroup[] = [];
  for (const key of SESSION_GROUP_ORDER) {
    const items = buckets.get(key);
    if (items && items.length > 0) {
      groups.push({ key, title: SESSION_GROUP_LABEL[key], sessions: items });
    }
  }
  return groups;
}

function pad2(value: number): string {
  return value < 10 ? `0${value}` : String(value);
}

function clockOf(timestamp: number): string {
  const date = new Date(timestamp);
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

/**
 * 列表里的时间：一小时以内给相对时间（刚发生的更关心「多久之前」），
 * 更久用自然日，跨年补年份——否则往年的「3月5日」会被误读成今年。
 */
export function formatRelativeTime(value?: string | null, now: number = Date.now()): string {
  const ts = parseSessionTime(value);
  if (ts <= 0) return '';

  const diff = now - ts;
  if (diff < MINUTE_MS) return '刚刚'; // 也覆盖未来时间戳（时钟漂移）
  if (diff < HOUR_MS) return `${Math.floor(diff / MINUTE_MS)} 分钟前`;

  const offset = dayOffset(ts, now);
  if (offset === 0) return `今天 ${clockOf(ts)}`;
  if (offset === 1) return `昨天 ${clockOf(ts)}`;

  const date = new Date(ts);
  const monthDay = `${date.getMonth() + 1}月${date.getDate()}日`;
  return date.getFullYear() === new Date(now).getFullYear()
    ? monthDay
    : `${date.getFullYear()}年${monthDay}`;
}
