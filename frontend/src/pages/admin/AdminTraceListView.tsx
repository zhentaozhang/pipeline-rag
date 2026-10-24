import React from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { manageApi } from '../../lib/api';
import { useAsyncData } from '../../lib/useAsyncData';
import { useUrlFilters } from '../../lib/useUrlFilters';
import { useDebouncedValue } from '../../components/admin/useDebouncedValue';
import type { TraceListItem, TracePageResponse } from '../../types/api';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { DataTable, TablePagination, type DataTableColumn } from '../../components/ui/DataTable';
import { FilterBar, FilterSelect, FilterSearch } from '../../components/ui/FilterBar';
import { Skeleton } from '../../components/ui/Skeleton';
import { AdminPageHeader } from '../../components/admin/AdminPageHeader';
import { AdminPanel } from '../../components/admin/AdminPanel';
import { AdminStatGrid } from '../../components/admin/AdminStatGrid';
import { AdminStatusBadge } from '../../components/admin/AdminStatusBadge';
import { formatMs, formatNumber, loadFailure } from '../../components/admin/adminFormat';
import { formatDateTime } from '../../lib/observabilityHelpers';

const DEFAULT_FILTERS = { q: '', status: 'ALL', page: '1' };
const PAGE_SIZE = 15;

const STATUS_OPTIONS = [
  { value: 'ALL', label: '全部状态' },
  { value: 'ok', label: '成功' },
  { value: 'error', label: '失败' },
];

/** Trace 链路列表：按会话 ID 与状态筛，点进任意一条看 span 瀑布 */
export const AdminTraceListView: React.FC = () => {
  const [filters, patchFilters] = useUrlFilters(DEFAULT_FILTERS);
  const conversationId = useDebouncedValue(filters.q, 350).trim();
  const page = Math.max(1, Number(filters.page) || 1);

  const { data, loading, error, refetch } = useAsyncData<TracePageResponse>(
    () =>
      manageApi.getTraces({
        pageNo: page,
        pageSize: PAGE_SIZE,
        conversationId,
        status: filters.status === 'ALL' ? '' : filters.status,
      }),
    [page, conversationId, filters.status]
  );

  const stats = data?.stats;
  const rows = data?.records ?? [];

  const columns: DataTableColumn<TraceListItem>[] = [
    {
      key: 'traceId',
      header: 'Trace',
      render: (row) => (
        <Link
          to={`/admin/traces/${row.traceId}`}
          className="font-mono text-xs text-primary underline-offset-2 hover:underline"
        >
          {row.traceId}
        </Link>
      ),
    },
    {
      key: 'conversation',
      header: '会话',
      render: (row) => (
        <Link
          to={`/admin/observability/${row.conversationId}`}
          className="font-mono text-2xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          {row.conversationId}
        </Link>
      ),
    },
    { key: 'spans', header: 'Span', align: 'right', render: (row) => formatNumber(row.spanCount) },
    { key: 'duration', header: '耗时', align: 'right', render: (row) => formatMs(row.durationMs) },
    {
      key: 'status',
      header: '状态',
      align: 'center',
      render: (row) => (
        <AdminStatusBadge
          label={row.status === 'error' ? '失败' : '成功'}
          tone={row.status === 'error' ? 'destructive' : 'success'}
        />
      ),
    },
    {
      key: 'preview',
      header: '输出预览',
      render: (row) => (
        <span className="line-clamp-2 max-w-[24rem] text-2xs leading-relaxed text-muted-foreground">
          {row.outputPreview || '（无输出）'}
        </span>
      ),
    },
    { key: 'createdAt', header: '时间', align: 'right', render: (row) => formatDateTime(row.createdAt) },
  ];

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        eyebrow="Trace 链路"
        title="链路列表"
        description="每条链路是一次问答的完整调用树。耗时长的链路先看 span 瀑布，定位是检索慢还是生成慢。"
        actions={
          <Button size="sm" variant="outline" onClick={() => refetch()} loading={loading}>
            <RefreshCw size={13} aria-hidden="true" />
            刷新
          </Button>
        }
      />

      {loading && !data ? (
        <div className="flex flex-col gap-4">
          <Skeleton lines={3} />
          <Skeleton lines={8} />
        </div>
      ) : error ? (
        <Alert variant="destructive" title="加载链路列表失败" action={<Button size="sm" variant="outline" onClick={() => refetch()}>重试</Button>}>
          {loadFailure(error, '链路列表')}
        </Alert>
      ) : (
        <>
          <AdminStatGrid
            stats={[
              { label: '链路总数', value: formatNumber(stats?.totalTraces) },
              { label: '今日链路', value: formatNumber(stats?.todayTraces) },
              { label: '异常链路', value: formatNumber(stats?.errorTraces), tone: Number(stats?.errorTraces ?? 0) > 0 ? 'destructive' : 'default' },
              { label: '平均根耗时', value: formatMs(stats?.avgRootDurationMs) },
            ]}
          />

          <AdminPanel bodyClassName="flex flex-col gap-3">
            <FilterBar>
              <FilterSearch
                label="会话 ID"
                value={filters.q}
                onChange={(value) => patchFilters({ q: value, page: '1' })}
                placeholder="输入完整或部分会话 ID"
              />
              <FilterSelect
                label="链路状态"
                value={filters.status}
                onChange={(value) => patchFilters({ status: value, page: '1' })}
                options={STATUS_OPTIONS}
              />
            </FilterBar>

            <DataTable
              caption="链路列表，含每条链路的 span 数量、耗时与状态"
              columns={columns}
              rows={rows}
              rowKey={(row) => row.traceId}
              loading={loading}
              error=""
              skeletonRows={6}
              dense
              emptyTitle={conversationId || filters.status !== 'ALL' ? '没有符合条件的链路' : '还没有链路数据'}
              emptyDescription={
                conversationId || filters.status !== 'ALL'
                  ? '放宽筛选条件试试，或清空会话 ID 后再看。'
                  : '链路来自真实问答请求。去聊天页问一个问题，再回来刷新即可看到。'
              }
              emptyAction={
                conversationId || filters.status !== 'ALL' ? (
                  <Button size="sm" variant="outline" onClick={() => patchFilters({ q: '', status: 'ALL', page: '1' })}>
                    清空筛选
                  </Button>
                ) : undefined
              }
              footer={
                <TablePagination
                  page={page}
                  pageSize={PAGE_SIZE}
                  total={Number(data?.total ?? 0)}
                  onPageChange={(next) => patchFilters({ page: String(next) })}
                />
              }
            />
          </AdminPanel>
        </>
      )}
    </div>
  );
};
