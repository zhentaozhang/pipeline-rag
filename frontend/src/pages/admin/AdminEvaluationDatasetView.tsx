import React, { useMemo, useState } from 'react';
import { RefreshCw, Zap } from 'lucide-react';
import { manageApi } from '../../lib/api';
import type { EvaluationDataset } from '../../types/api';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { FilterBar, FilterSearch } from '../../components/ui/FilterBar';
import { Skeleton } from '../../components/ui/Skeleton';
import { toast } from '../../lib/toast';
import { useAsyncData } from '../../lib/useAsyncData';
import { useUrlFilters } from '../../lib/useUrlFilters';
import { AdminPageHeader } from '../../components/admin/AdminPageHeader';
import { AdminPanel } from '../../components/admin/AdminPanel';
import { AdminStatGrid } from '../../components/admin/AdminStatGrid';
import { EvaluationTable } from '../../components/admin/evaluation/EvaluationTable';
import { useDebouncedValue } from '../../components/admin/useDebouncedValue';
import { actionFailure, formatNumber, loadFailure } from '../../components/admin/adminFormat';

const DEFAULT_FILTERS = { q: '', page: '1' };
const PAGE_SIZE = 10;
/** 一次拉满，前端做真实的搜索 + 分页；评估集是人工维护的，超过 200 条再改回服务端分页 */
const FETCH_SIZE = 200;

interface DatasetBundle {
  records: EvaluationDataset[];
  total: number;
}

/** 评估看板：样本清单 + RAGAS 五项分数 + 重跑与删除 */
export const AdminEvaluationDatasetView: React.FC = () => {
  const [filters, patchFilters] = useUrlFilters(DEFAULT_FILTERS);
  const keyword = useDebouncedValue(filters.q, 300);
  const [runningId, setRunningId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<EvaluationDataset | null>(null);
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchRunning, setBatchRunning] = useState(false);

  const { data, loading, error, refetch } = useAsyncData<DatasetBundle>(async () => {
    const response = await manageApi.listEvaluationDataset({ pageNo: 1, pageSize: FETCH_SIZE });
    return { records: response?.records ?? [], total: Number(response?.total ?? response?.records?.length ?? 0) };
  });

  const records = useMemo(() => data?.records ?? [], [data]);
  const filtered = useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    if (!needle) return records;
    return records.filter((item) =>
      [item.question, item.description, item.groundTruth].some((field) => String(field ?? '').toLowerCase().includes(needle))
    );
  }, [records, keyword]);

  const page = Math.max(1, Number(filters.page) || 1);
  const pageRows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const pending = records.filter((item) => Number(item.status ?? 1) === 1).length;
  const done = records.filter((item) => Number(item.status ?? 1) === 2).length;

  const runOne = async (item: EvaluationDataset) => {
    setRunningId(item.id);
    try {
      await manageApi.runEvaluation([item.id]);
      toast({ title: '已提交评估', description: `样本 #${item.id} 已入队，稍后刷新看分数。`, variant: 'success' });
      refetch();
    } catch (runError) {
      toast({ title: '提交评估失败', description: actionFailure(runError, '提交评估', '请确认后端评估任务队列正常后重试。'), variant: 'error' });
    } finally {
      setRunningId(null);
    }
  };

  const runBatch = async () => {
    setBatchRunning(true);
    try {
      await manageApi.runEvaluation();
      toast({ title: '已提交全量评估', description: '待评估样本都入队了，列表里状态会变成「评估中」。', variant: 'success' });
      setBatchOpen(false);
      refetch();
    } catch (runError) {
      toast({ title: '提交全量评估失败', description: actionFailure(runError, '提交全量评估', '请确认后端评估任务队列正常后重试。'), variant: 'error' });
    } finally {
      setBatchRunning(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    const id = deleting.id;
    setDeleting(null);
    try {
      await manageApi.deleteEvaluationDataset(id);
      toast({ title: '已删除样本', description: `样本 #${id} 已从评估集移除。`, variant: 'success' });
      refetch();
    } catch (deleteError) {
      toast({ title: '删除失败', description: actionFailure(deleteError, '删除评估样本'), variant: 'error' });
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        eyebrow="评估看板"
        title="评估数据集"
        description="每条样本都会用 RAGAS 五项指标打分：忠实度看答案有没有编，上下文指标看检索给得够不够。"
        actions={
          <>
            <Button size="sm" variant="outline" onClick={() => refetch()} loading={loading}>
              <RefreshCw size={13} aria-hidden="true" />
              刷新
            </Button>
            <Button size="sm" onClick={() => setBatchOpen(true)} disabled={pending === 0 || batchRunning}>
              <Zap size={13} aria-hidden="true" />
              运行全部待评估
            </Button>
          </>
        }
      />

      {loading && !data ? (
        <div className="flex flex-col gap-4">
          <Skeleton lines={3} />
          <Skeleton lines={8} />
        </div>
      ) : error ? (
        <Alert
          variant="destructive"
          title="加载评估数据集失败"
          action={
            <Button size="sm" variant="outline" onClick={() => refetch()}>
              重试
            </Button>
          }
        >
          {loadFailure(error, '评估数据集')}
        </Alert>
      ) : (
        <>
          <AdminStatGrid
            stats={[
              { label: '样本总数', value: formatNumber(records.length), hint: `后端报告 ${formatNumber(data?.total)}` },
              { label: '已评估', value: formatNumber(done), tone: 'success' },
              { label: '待评估', value: formatNumber(pending), tone: pending > 0 ? 'warning' : 'default' },
              { label: '筛出条数', value: formatNumber(filtered.length), hint: keyword ? `关键词「${keyword}」` : '未筛选' },
            ]}
          />

          <AdminPanel
            title="样本清单"
            description={`一次最多加载 ${FETCH_SIZE} 条，搜索会在这批数据里过滤，再在前端分页。`}
            bodyClassName="flex flex-col gap-3"
          >
            <FilterBar>
              <FilterSearch
                label="搜索样本"
                value={filters.q}
                onChange={(value) => patchFilters({ q: value, page: '1' })}
                placeholder="按问题、标准答案或描述搜索"
              />
            </FilterBar>

            <EvaluationTable
              rows={pageRows}
              loading={loading}
              keyword={keyword}
              page={page}
              pageSize={PAGE_SIZE}
              total={filtered.length}
              runningId={runningId}
              onRun={runOne}
              onDelete={setDeleting}
              onPageChange={(next) => patchFilters({ page: String(next) })}
              onClearSearch={() => patchFilters({ q: '', page: '1' })}
            />
          </AdminPanel>
        </>
      )}

      <ConfirmDialog
        open={deleting !== null}
        title="删除这条评估样本？"
        description={deleting ? `样本 #${deleting.id}「${deleting.question || '未填写问题'}」会被永久移除，已有分数一并丢失。` : ''}
        confirmLabel="删除"
        danger
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      />

      <ConfirmDialog
        open={batchOpen}
        title="运行全部待评估样本？"
        description={`还有 ${pending} 条待评估，会逐条调用模型评分，可能持续较长时间并产生费用。`}
        confirmLabel="开始运行"
        onConfirm={runBatch}
        onCancel={() => setBatchOpen(false)}
      />
    </div>
  );
};
