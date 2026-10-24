import React from 'react';
import type { BenchmarkItem } from '../../../types/api';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { formatMs } from '../adminFormat';

const COLUMNS: DataTableColumn<BenchmarkItem>[] = [
  {
    key: 'stage',
    header: '阶段',
    render: (row) => <span className="font-mono text-xs text-foreground">{row.stageCode || '未命名阶段'}</span>,
  },
  {
    key: 'mode',
    header: '执行模式',
    render: (row) => <span className="text-xs text-muted-foreground">{row.executionMode || '默认'}</span>,
  },
  { key: 'p50', header: 'P50', align: 'right', render: (row) => formatMs(Number(row.p50Ms ?? 0)) },
  { key: 'p90', header: 'P90', align: 'right', render: (row) => formatMs(Number(row.p90Ms ?? 0)) },
  { key: 'p99', header: 'P99', align: 'right', render: (row) => formatMs(Number(row.p99Ms ?? 0)) },
];

/** 各阶段的耗时分位表：P99 与 P50 差距大的阶段就是长尾瓶颈 */
export const BenchmarkTable: React.FC<{ rows: BenchmarkItem[]; loading?: boolean }> = ({ rows, loading }) => (
  <DataTable
    caption="各执行阶段的 P50 / P90 / P99 耗时分布，单位毫秒"
    columns={COLUMNS}
    rows={rows}
    rowKey={(row, index) => `${row.stageCode ?? 'stage'}-${row.executionMode ?? ''}-${index}`}
    loading={loading}
    skeletonRows={5}
    dense
    emptyTitle="还没有性能基准数据"
    emptyDescription="需要至少跑通几轮问答，后端才会按阶段聚合出分位值。"
  />
);
