import type { ReactNode } from 'react';
import { MessageSquare, SearchX } from 'lucide-react';
import { clsx } from 'clsx';
import { Button } from '../ui/Button';
import { EmptyState } from '../ui/EmptyState';
import { Skeleton } from '../ui/Skeleton';
import { SessionItem } from './SessionItem';
import type { SessionGroup } from '../../lib/sessionGrouping';
import type { ChatSession } from '../../types/api';

interface SessionListProps {
  groups: SessionGroup[];
  /** 首次加载且没有缓存数据时显示骨架 */
  loading: boolean;
  hasSessions: boolean;
  query: string;
  now: number;
  currentConversationId: string;
  streaming: boolean;
  onSelect: (conversationId: string) => void;
  onRename: (conversationId: string, title: string) => void;
  onTogglePin: (conversationId: string, pinned: boolean) => void;
  onDelete: (conversationId: string) => void;
  onClearSearch: () => void;
  onStartNew: () => void;
}

/**
 * 会话列表：三种状态（加载骨架 / 空 / 分组列表）+ 搜索无结果的独立空态。
 * 分组标题 sticky 吸顶，滚动时不会跟着条目一起抖。
 */
export function SessionList({
  groups,
  loading,
  hasSessions,
  query,
  now,
  currentConversationId,
  streaming,
  onSelect,
  onRename,
  onTogglePin,
  onDelete,
  onClearSearch,
  onStartNew,
}: SessionListProps) {
  const renderItem = (session: ChatSession) => (
    <SessionItem
      key={session.conversationId}
      session={session}
      active={session.conversationId === currentConversationId}
      disabled={streaming}
      now={now}
      onSelect={onSelect}
      onRename={onRename}
      onTogglePin={onTogglePin}
      onDelete={onDelete}
    />
  );

  let body: ReactNode;
  if (loading && !hasSessions) {
    body = (
      <div className="space-y-2 px-1 pt-2" aria-hidden="true">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-5/6" />
      </div>
    );
  } else if (!hasSessions) {
    body = (
      <EmptyState
        compact
        icon={<MessageSquare size={24} aria-hidden="true" />}
        title="还没有会话"
        description="提一个问题，就会在这里留下记录。"
        action={
          <Button variant="outline" size="sm" onClick={onStartNew}>
            开始第一个对话
          </Button>
        }
      />
    );
  } else if (groups.length === 0) {
    body = (
      <EmptyState
        compact
        icon={<SearchX size={24} aria-hidden="true" />}
        title="没有匹配的会话"
        description={`没有找到标题包含「${query.trim()}」的会话。`}
        action={
          <Button variant="outline" size="sm" onClick={onClearSearch}>
            清空搜索
          </Button>
        }
      />
    );
  } else {
    body = (
      <div aria-busy={loading || undefined}>
        {groups.map((group, index) => (
          <section
            key={group.key}
            aria-labelledby={`session-group-${group.key}`}
            className={clsx(index > 0 && 'mt-3 border-t border-border pt-2')}
          >
            <h3
              id={`session-group-${group.key}`}
              className="sticky top-0 z-10 flex items-center justify-between gap-2 bg-card px-2 py-1 text-2xs font-semibold text-muted-foreground"
            >
              <span>{group.title}</span>
              <span className="tabular-nums">{group.sessions.length}</span>
            </h3>
            <ul className="space-y-0.5">{group.sessions.map(renderItem)}</ul>
          </section>
        ))}
      </div>
    );
  }

  const resultCount = groups.reduce((total, group) => total + group.sessions.length, 0);

  return (
    <nav aria-label="会话列表" className="flex-1 overflow-y-auto overflow-x-hidden px-2 pb-3">
      {/* 搜索是异步生效的列表：只播报条数，别让读屏把整份列表念一遍 */}
      <p role="status" className="sr-only">
        {query.trim() ? (resultCount > 0 ? `找到 ${resultCount} 个会话` : '没有匹配的会话') : ''}
      </p>
      {body}
    </nav>
  );
}
