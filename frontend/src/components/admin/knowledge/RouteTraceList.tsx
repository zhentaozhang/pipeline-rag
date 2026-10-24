import React from 'react';
import type { RouteTrace } from '../../../types/api';
import { AdminStatusBadge } from '../AdminStatusBadge';
import { Button } from '../../../components/ui/Button';
import { Skeleton } from '../../../components/ui/Skeleton';
import { TablePagination } from '../../../components/ui/DataTable';
import { formatConfidence, routeStatusMeta, routeTraceKey } from './routeTraceMeta';

interface Props {
  rows: RouteTrace[];
  loading: boolean;
  error: string;
  onRetry: () => void;
  selectedKey: string | null;
  onSelect: (key: string) => void;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}

/** 左侧路由追踪列表：一条记录 = 一轮问答的路由决策 */
export const RouteTraceList: React.FC<Props> = ({ rows, loading, error, onRetry, selectedKey, onSelect, page, pageSize, total, onPageChange }) => (
  <div className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-card">
    <div className="flex-1 overflow-y-auto p-2">
      {loading ? (
        <div className="flex flex-col gap-2 p-2">
          <Skeleton lines={3} />
          <Skeleton lines={3} />
        </div>
      ) : error ? (
        <div className="flex flex-col items-center gap-2 p-6 text-center">
          <p className="text-xs text-destructive">{error}</p>
          <Button size="sm" variant="outline" onClick={onRetry}>
            重试
          </Button>
        </div>
      ) : rows.length === 0 ? (
        <div className="p-6 text-center">
          <p className="text-sm font-medium text-foreground">没有符合条件的路由记录</p>
          <p className="mt-1 text-xs text-muted-foreground">清空筛选条件，或先在对话里问几个问题产生路由决策。</p>
        </div>
      ) : (
        <ul className="flex flex-col gap-1">
          {rows.map((row) => {
            const key = routeTraceKey(row);
            const status = routeStatusMeta(row.routeStatus);
            const active = key === selectedKey;
            return (
              <li key={key}>
                <button
                  type="button"
                  onClick={() => onSelect(key)}
                  aria-current={active ? 'true' : undefined}
                  className={`w-full rounded-lg border px-3 py-2.5 text-left text-sm transition-colors ${
                    active
                      ? 'border-primary/30 bg-primary/5'
                      : 'border-transparent hover:border-border hover:bg-secondary/60'
                  }`}
                >
                  <span className="mb-1.5 flex flex-wrap items-center gap-1.5">
                    <span className="rounded-full border border-border bg-secondary px-2 py-0.5 text-2xs font-medium text-muted-foreground">
                      {row.mode || '未知模式'}
                    </span>
                    <AdminStatusBadge label={status.label} tone={status.tone} />
                    <span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-2xs font-medium text-primary">
                      {formatConfidence(row.confidence)}
                    </span>
                  </span>
                  <span className="mb-1.5 line-clamp-2 block text-xs leading-relaxed text-foreground">
                    {row.question || '未记录问题'}
                  </span>
                  <span className="flex items-center justify-between gap-2 text-2xs text-muted-foreground">
                    <span className="truncate">{row.conversationId ? `会话 ${row.conversationId.slice(0, 8)}…` : '未知会话'}</span>
                    <span className="shrink-0">{row.createdAt || '未记录时间'}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
    <div className="border-t border-border p-2">
      <TablePagination page={page} pageSize={pageSize} total={total} onPageChange={onPageChange} />
    </div>
  </div>
);