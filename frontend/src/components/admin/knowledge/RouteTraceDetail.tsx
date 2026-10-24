import React from 'react';
import { FileSearch } from 'lucide-react';
import type { RouteTrace } from '../../../types/api';
import { AdminStatusBadge } from '../AdminStatusBadge';
import { AdminPanel } from '../AdminPanel';
import { EmptyState } from '../../../components/ui/EmptyState';
import { formatConfidence, routeStatusMeta } from './routeTraceMeta';

interface Props {
  record: RouteTrace | null;
}

/** 右侧路由详情：一眼看清这条记录为什么被路由到（或没路由到）某个主题 */
export const RouteTraceDetail: React.FC<Props> = ({ record }) => {
  if (!record) {
    return (
      <AdminPanel className="flex min-h-0 flex-1 items-center justify-center">
        <EmptyState
          icon={<FileSearch size={20} aria-hidden="true" />}
          title="从左侧选择一条追踪记录"
          description="选中后可以看到原始问题、改写后的问题以及路由置信度。"
        />
      </AdminPanel>
    );
  }

  const status = routeStatusMeta(record.routeStatus);
  const rows = [
    { label: '路由模式', value: record.mode || '未记录' },
    { label: '路由状态', value: status.label },
    { label: '置信度', value: formatConfidence(record.confidence, 2) },
    { label: '创建时间', value: record.createdAt || '未记录' },
    { label: '会话 ID', value: record.conversationId || '未记录' },
    { label: '轮次 ID', value: record.exchangeId || '未记录' },
  ];

  return (
    <AdminPanel className="flex min-h-0 flex-1 flex-col" title="路由详情" description="这一轮的原始问题、改写问题与判定结果。">
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
        <div className="flex flex-wrap items-center gap-2">
          <AdminStatusBadge label={status.label} tone={status.tone} />
          <span className="rounded-full border border-border bg-secondary px-2 py-0.5 text-2xs text-muted-foreground">
            模式 {record.mode || '未记录'}
          </span>
        </div>

        <div>
          <h4 className="text-xs font-medium text-muted-foreground">原始问题</h4>
          <p className="mt-1 text-sm leading-relaxed text-foreground">{record.question || '未记录问题'}</p>
        </div>

        <div className="rounded-lg border border-border bg-secondary/40 p-3">
          <h4 className="text-xs font-medium text-muted-foreground">改写后的问题</h4>
          <p className="mt-1 text-sm leading-relaxed text-foreground">{record.rewriteQuestion || '未记录改写问题'}</p>
        </div>

        <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {rows.map((row) => (
            <div key={row.label} className="rounded-md border border-border px-2.5 py-2">
              <dt className="text-2xs text-muted-foreground">{row.label}</dt>
              <dd className="mt-0.5 truncate font-mono text-xs text-foreground">{row.value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </AdminPanel>
  );
};
