import React from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw, Search } from 'lucide-react';
import { chatApi } from '../../lib/api';
import { formatChatMode, formatDateTime, formatStatusLabel, statusTone } from '../../lib/observabilityHelpers';
import { useAsyncData } from '../../lib/useAsyncData';
import { useUrlFilters } from '../../lib/useUrlFilters';
import type { SessionPageResult } from '../../lib/api';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { EmptyState } from '../../components/ui/EmptyState';
import { FilterBar, FilterSearch, FilterSelect } from '../../components/ui/FilterBar';
import { Skeleton } from '../../components/ui/Skeleton';
import { TablePagination } from '../../components/ui/DataTable';
import { AdminPageHeader } from '../../components/admin/AdminPageHeader';
import { AdminStatGrid } from '../../components/admin/AdminStatGrid';
import { AdminStatusBadge } from '../../components/admin/AdminStatusBadge';
import { useDebouncedValue } from '../../components/admin/useDebouncedValue';
import { loadFailure } from '../../components/admin/adminFormat';

const DEFAULT_FILTERS = { q: '', mode: 'ALL', status: 'ALL', page: '1', size: '12' };
const MODE_OPTIONS = [
  { value: 'ALL', label: '全部模式' },
  { value: 'DOCUMENT', label: '文档问答' },
  { value: 'AUTO_DOCUMENT', label: '自动文档' },
  { value: 'OPEN_CHAT', label: '开放对话' },
];
const STATUS_OPTIONS = [
  { value: 'ALL', label: '全部状态' },
  { value: 'RUNNING', label: '运行中' },
  { value: 'COMPLETED', label: '已完成' },
  { value: 'FAILED', label: '失败' },
  { value: 'STOPPED', label: '已停止' },
];
const SIZE_OPTIONS = [
  { value: '12', label: '每页 12 条' },
  { value: '24', label: '每页 24 条' },
  { value: '36', label: '每页 36 条' },
];

/** 对话观测列表：按模式/状态筛会话，点进去看单会话的轮次时间线 */
export const AdminObservabilityListView: React.FC = () => {
  const [filters, patchFilters] = useUrlFilters(DEFAULT_FILTERS);
  const keyword = useDebouncedValue(filters.q, 350);
  const page = Math.max(1, Number(filters.page) || 1);
  const pageSize = Number(filters.size) || 12;

  const { data, loading, error, refetch } = useAsyncData<SessionPageResult>(
    () =>
      chatApi.listSessionsPage({
        keyword: keyword.trim(),
        chatMode: filters.mode === 'ALL' ? '' : filters.mode,
        turnStatus: filters.status === 'ALL' ? '' : filters.status,
        pageNo: String(page),
        pageSize: String(pageSize),
      }),
    [keyword, filters.mode, filters.status, page, pageSize]
  );

  const sessions = data?.sessions ?? [];
  const total = Number(data?.totalSize ?? 0);
  const running = sessions.filter((item) => item.running).length;
  const documentSessions = sessions.filter((item) => String(item.chatMode ?? '').toUpperCase().includes('DOCUMENT')).length;
  const failed = sessions.filter((item) => String(item.latestTurnStatus ?? '').toUpperCase() === 'FAILED').length;

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        eyebrow="对话观测"
        title="会话列表"
        description="按关键词、问答模式和最近一轮状态筛会话。点开任意会话可以查看每一轮的阶段耗时、引用来源与 token 成本。"
        actions={
          <Button size="sm" variant="outline" onClick={() => refetch()} loading={loading}>
            <RefreshCw size={13} aria-hidden="true" />
            刷新
          </Button>
        }
      />

      <AdminStatGrid
        stats={[
          { label: '会话总数', value: total, hint: '符合当前筛选条件的全部会话' },
          { label: '本页运行中', value: running, tone: running ? 'primary' : 'default' },
          { label: '本页文档问答', value: documentSessions },
          { label: '本页最近失败', value: failed, tone: failed ? 'destructive' : 'default' },
        ]}
      />

      <FilterBar
        actions={
          <Button
            size="sm"
            variant="ghost"
            onClick={() => patchFilters({ q: '', mode: 'ALL', status: 'ALL', page: '1' })}
            disabled={!filters.q && filters.mode === 'ALL' && filters.status === 'ALL' && page === 1}
          >
            清空筛选
          </Button>
        }
      >
        <FilterSearch
          label="搜索会话"
          value={filters.q}
          onChange={(value) => patchFilters({ q: value, page: '1' })}
          placeholder="按标题或最近一条消息搜索"
        />
        <FilterSelect
          label="问答模式"
          value={filters.mode}
          onChange={(value) => patchFilters({ mode: value, page: '1' })}
          options={MODE_OPTIONS}
        />
        <FilterSelect
          label="最近状态"
          value={filters.status}
          onChange={(value) => patchFilters({ status: value, page: '1' })}
          options={STATUS_OPTIONS}
        />
        <FilterSelect
          label="每页条数"
          value={filters.size}
          onChange={(value) => patchFilters({ size: value, page: '1' })}
          options={SIZE_OPTIONS}
        />
      </FilterBar>

      {loading && sessions.length === 0 ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="rounded-xl border border-border bg-card p-4">
              <Skeleton lines={3} />
            </div>
          ))}
        </div>
      ) : error ? (
        <Alert
          variant="destructive"
          title="加载会话列表失败"
          action={<Button size="sm" variant="outline" onClick={() => refetch()}>重试</Button>}
        >
          {loadFailure(error, '会话列表')}
        </Alert>
      ) : sessions.length === 0 ? (
        <EmptyState
          icon={<Search size={22} aria-hidden="true" />}
          title="没有匹配的会话"
          description="换个关键词，或把模式和状态都切回「全部」。也可以先去聊天页发一条问题，再回来观察链路。"
          action={
            <Button size="sm" variant="outline" onClick={() => patchFilters({ q: '', mode: 'ALL', status: 'ALL', page: '1' })}>
              清空筛选
            </Button>
          }
        />
      ) : (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {sessions.map((session) => {
            const tone = statusTone(session.latestTurnStatus);
            return (
              <li key={session.conversationId}>
                <Link
                  to={`/admin/observability/${session.conversationId}`}
                  className={`flex h-full flex-col gap-2 rounded-xl border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-secondary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                    tone === 'failed' || tone === 'error' ? 'border-destructive/30' : 'border-border'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                      {session.title || '未命名会话'}
                    </span>
                    <AdminStatusBadge label={formatStatusLabel(session.latestTurnStatus)} tone={tone === 'error' ? 'destructive' : tone === 'failed' ? 'destructive' : tone === 'running' ? 'primary' : tone === 'completed' ? 'success' : 'default'} />
                  </div>
                  <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                    {session.latestUserMessage || session.latestAssistantMessage || '这轮还没有消息内容。'}
                  </p>
                  {session.latestTurnErrorMessage ? (
                    <p className="rounded-md bg-destructive/10 px-2 py-1 text-2xs leading-relaxed text-destructive">
                      最近一轮失败：{session.latestTurnErrorMessage}
                    </p>
                  ) : null}
                  <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-muted-foreground">
                    <span>{formatChatMode(session.chatMode)}</span>
                    <span>{Number(session.exchangeCount ?? 0)} 轮</span>
                    <span>{formatDateTime(session.updatedAt)}</span>
                    <span className="font-mono">{session.conversationId}</span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      {sessions.length > 0 ? (
        <TablePagination page={page} pageSize={pageSize} total={total} onPageChange={(next) => patchFilters({ page: String(next) })} />
      ) : null}
    </div>
  );
};
