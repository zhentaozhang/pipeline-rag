import React from 'react';
import { Trash2, Zap } from 'lucide-react';
import type { EvaluationDataset } from '../../../types/api';
import { Button } from '../../../components/ui/Button';
import { DataTable, TablePagination, type DataTableColumn } from '../../../components/ui/DataTable';
import { IconButton } from '../../../components/ui/IconButton';
import { AdminStatusBadge, type AdminStatusTone } from '../AdminStatusBadge';
import { ScoreCell } from './ScoreCell';

/** 后端 status：1 待评估 / 2 已评估 / 3 评估中 */
const statusMeta = (value: unknown): { label: string; tone: AdminStatusTone } => {
  const code = Number(value ?? 1);
  if (code === 2) return { label: '已评估', tone: 'success' };
  if (code === 3) return { label: '评估中', tone: 'primary' };
  if (code === 1) return { label: '待评估', tone: 'default' };
  return { label: '未知', tone: 'default' };
};

interface Props {
  rows: EvaluationDataset[];
  loading: boolean;
  keyword: string;
  page: number;
  pageSize: number;
  total: number;
  runningId: number | null;
  onRun: (row: EvaluationDataset) => void;
  onDelete: (row: EvaluationDataset) => void;
  onPageChange: (page: number) => void;
  onClearSearch: () => void;
}

/** 评估样本表：五项 RAGAS 分数右对齐，分数同时带文字等级，不只靠颜色 */
export const EvaluationTable: React.FC<Props> = ({
  rows,
  loading,
  keyword,
  page,
  pageSize,
  total,
  runningId,
  onRun,
  onDelete,
  onPageChange,
  onClearSearch,
}) => {
  const columns: DataTableColumn<EvaluationDataset>[] = [
    {
      key: 'question',
      header: '问题',
      render: (row) => (
        <div className="max-w-[22rem]">
          <p className="line-clamp-2 text-xs font-medium text-foreground">{row.question || row.description || '未填写问题'}</p>
          <p className="mt-0.5 line-clamp-1 text-2xs text-muted-foreground">标准答案：{row.groundTruth || '未填写'}</p>
        </div>
      ),
    },
    {
      key: 'status',
      header: '状态',
      align: 'center',
      render: (row) => {
        const meta = statusMeta(row.status);
        return <AdminStatusBadge label={meta.label} tone={meta.tone} />;
      },
    },
    { key: 'faithfulness', header: '忠实度', align: 'right', render: (row) => <ScoreCell value={row.faithfulnessScore} /> },
    { key: 'relevancy', header: '答案相关性', align: 'right', render: (row) => <ScoreCell value={row.answerRelevancyScore} /> },
    { key: 'precision', header: '上下文精确率', align: 'right', render: (row) => <ScoreCell value={row.contextPrecisionScore} /> },
    { key: 'recall', header: '上下文召回率', align: 'right', render: (row) => <ScoreCell value={row.contextRecallScore} /> },
    { key: 'correctness', header: '答案正确性', align: 'right', render: (row) => <ScoreCell value={row.answerCorrectnessScore} /> },
    {
      key: 'action',
      header: '操作',
      align: 'right',
      render: (row) => (
        <span className="inline-flex items-center gap-1">
          <IconButton
            label={runningId === row.id ? `样本 ${row.id} 提交中` : `运行样本 ${row.id}`}
            hint={runningId === row.id ? '正在提交，请稍候' : '单独重跑这一条评估'}
            variant="ghost"
            icon={<Zap size={13} aria-hidden="true" />}
            onClick={() => onRun(row)}
          />
          <IconButton
            label={`删除样本 ${row.id}`}
            hint="从评估集移除"
            variant="ghost"
            icon={<Trash2 size={13} aria-hidden="true" />}
            onClick={() => onDelete(row)}
          />
        </span>
      ),
    },
  ];

  return (
    <DataTable
      caption="评估样本及其 RAGAS 五项分数，分数低于 0.6 标记为低"
      columns={columns}
      rows={rows}
      rowKey={(row) => String(row.id)}
      loading={loading}
      error=""
      skeletonRows={6}
      emptyTitle={keyword ? '没有匹配的样本' : '评估集还是空的'}
      emptyDescription={
        keyword
          ? '换个关键词试试，或清空搜索框看全部样本。'
          : '先导入几条「问题 + 标准答案」，再点右上角运行评估，这里才会出现分数。'
      }
      emptyAction={
        keyword ? (
          <Button size="sm" variant="outline" onClick={onClearSearch}>
            清空搜索
          </Button>
        ) : undefined
      }
      footer={<TablePagination page={page} pageSize={pageSize} total={total} onPageChange={onPageChange} />}
    />
  );
};
