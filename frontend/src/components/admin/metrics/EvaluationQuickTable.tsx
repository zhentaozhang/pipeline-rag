import React from 'react';
import { Play } from 'lucide-react';
import type { EvaluationDataset } from '../../../types/api';
import { Button } from '../../ui/Button';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';

interface Props {
  rows: EvaluationDataset[];
  loading?: boolean;
  runningId: number | null;
  onRun: (item: EvaluationDataset) => void;
}

/** 指标页里的评估集摘要表：只为「随手挑一条样本重跑」服务，完整看板在评估页 */
export const EvaluationQuickTable: React.FC<Props> = ({ rows, loading, runningId, onRun }) => {
  const columns: DataTableColumn<EvaluationDataset>[] = [
    {
      key: 'question',
      header: '问题',
      render: (row) => (
        <span className="line-clamp-2 text-xs text-foreground">{row.question || row.description || '未填写问题'}</span>
      ),
    },
    {
      key: 'status',
      header: '状态',
      align: 'center',
      render: (row) => {
        const status = Number(row.status ?? 1);
        const map: Record<number, { label: string; className: string }> = {
          1: { label: '待评估', className: 'border-border text-muted-foreground' },
          2: { label: '已评估', className: 'border-success/30 text-success' },
          3: { label: '评估中', className: 'border-primary/30 text-primary' },
        };
        const view = map[status] ?? map[1];
        return <span className={`inline-flex rounded-md border px-1.5 py-px text-2xs ${view.className}`}>{view.label}</span>;
      },
    },
    {
      key: 'action',
      header: '操作',
      align: 'right',
      render: (row) => (
        <Button
          size="sm"
          variant="ghost"
          loading={runningId === row.id}
          disabled={Number(row.status ?? 1) === 3}
          onClick={() => onRun(row)}
        >
          <Play size={12} aria-hidden="true" />
          运行
        </Button>
      ),
    },
  ];

  return (
    <DataTable
      caption="评估样本列表，可单独触发某一条的评估"
      columns={columns}
      rows={rows}
      rowKey={(row) => String(row.id)}
      loading={loading}
      skeletonRows={4}
      dense
      emptyTitle="评估集还是空的"
      emptyDescription="先到「评估看板」导入几条问题与标准答案，这里才有可运行的样本。"
    />
  );
};
