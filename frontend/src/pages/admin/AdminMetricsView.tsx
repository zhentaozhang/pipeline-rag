import React, { useState } from 'react';
import { RefreshCw, Zap } from 'lucide-react';
import { manageApi } from '../../lib/api';
import { useAsyncData } from '../../lib/useAsyncData';
import type { BenchmarkItem, EvaluationDataset, MetricsOverview } from '../../types/api';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { Skeleton } from '../../components/ui/Skeleton';
import { toast } from '../../lib/toast';
import { AdminPageHeader } from '../../components/admin/AdminPageHeader';
import { AdminPanel } from '../../components/admin/AdminPanel';
import { AdminStatGrid } from '../../components/admin/AdminStatGrid';
import { BenchmarkTable } from '../../components/admin/metrics/BenchmarkTable';
import { EvaluationQuickTable } from '../../components/admin/metrics/EvaluationQuickTable';
import { UsageTrendChart, type UsageTrendPoint } from '../../components/admin/charts/UsageTrendChart';
import { actionFailure, formatCost, formatNumber, formatRatio, loadFailure } from '../../components/admin/adminFormat';

interface MetricsBundle {
  overview: MetricsOverview | null;
  trend: UsageTrendPoint[];
  benchmarks: BenchmarkItem[];
  evaluations: EvaluationDataset[];
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

/** 观测指标：概览卡片 + 用量趋势 + 阶段分位 + 评估样本快捷重跑 */
export const AdminMetricsView: React.FC = () => {
  const [runningId, setRunningId] = useState<number | null>(null);
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchRunning, setBatchRunning] = useState(false);

  const { data, loading, error, refetch } = useAsyncData<MetricsBundle>(async () => {
    const [overview, trend, benchmarks, evaluations] = await Promise.all([
      manageApi.getMetricsOverview(),
      manageApi.getUsageTrend(14),
      manageApi.getBenchmarks(),
      manageApi.listEvaluationDataset({ pageNo: 1, pageSize: 20 }),
    ]);
    return {
      // 后端偶尔把结果包一层 data，这里两种形态都接受
      overview: ((overview as { data?: MetricsOverview }).data ?? overview) as MetricsOverview,
      trend: asArray<UsageTrendPoint>(trend),
      benchmarks: asArray<BenchmarkItem>(benchmarks),
      evaluations: evaluations?.records ?? [],
    };
  });

  const overview = data?.overview ?? null;

  const runOne = async (item: EvaluationDataset) => {
    setRunningId(item.id);
    try {
      await manageApi.runEvaluation([item.id]);
      toast({ title: '已提交单条评估', description: `样本 #${item.id} 开始运行，稍后回到评估看板查看分数。`, variant: 'success' });
      refetch();
    } catch (runError) {
      toast({ title: '提交评估失败', description: actionFailure(runError, '提交单条评估', '请确认后端评估任务队列正常后重试。'), variant: 'error' });
    } finally {
      setRunningId(null);
    }
  };

  const runBatch = async () => {
    setBatchRunning(true);
    try {
      await manageApi.runEvaluation();
      toast({ title: '已提交全量评估', description: '所有待评估样本已入队，结果会写回评估看板。', variant: 'success' });
      setBatchOpen(false);
      refetch();
    } catch (runError) {
      toast({ title: '提交全量评估失败', description: actionFailure(runError, '提交全量评估', '请确认后端评估任务队列正常后重试。'), variant: 'error' });
    } finally {
      setBatchRunning(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        eyebrow="观测指标"
        title="运行指标"
        description="这里汇总调用量、失败率、成本与阶段耗时。指标偏高时先看阶段分位表，再决定优化检索还是生成。"
        actions={
          <>
            <Button size="sm" variant="outline" onClick={() => refetch()} loading={loading}>
              <RefreshCw size={13} aria-hidden="true" />
              刷新
            </Button>
            <Button size="sm" onClick={() => setBatchOpen(true)} disabled={loading || !data || batchRunning}>
              <Zap size={13} aria-hidden="true" />
              运行全量评估
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
        <Alert variant="destructive" title="加载运行指标失败" action={<Button size="sm" variant="outline" onClick={() => refetch()}>重试</Button>}>
          {loadFailure(error, '运行指标')}
        </Alert>
      ) : (
        <>
          <AdminStatGrid
            stats={[
              { label: '问答轮次', value: formatNumber(overview?.totalExchanges), hint: `活跃会话 ${formatNumber(overview?.activeConversations)}` },
              { label: '平均响应', value: `${formatNumber(overview?.avgResponseTimeMs)} ms`, hint: `失败率 ${formatNumber(overview?.errorRate)}%` },
              { label: '今日 Token', value: formatNumber(overview?.todayTokens), hint: `累计 ${formatNumber(overview?.totalTokens)}` },
              { label: '今日成本', value: formatCost(overview?.todayCost), hint: `累计 ${formatCost(overview?.totalCost)}` },
              { label: '缓存命中率', value: formatRatio(overview?.cacheHitRatio), hint: '越高越省钱' },
            ]}
            columns={5}
          />

          <AdminPanel title="近 14 天用量趋势" description="实线为 Token，虚线为调用次数，左右各一根 Y 轴">
            <UsageTrendChart data={data?.trend ?? []} />
          </AdminPanel>

          <AdminPanel title="阶段耗时分布" description="某一阶段的 P99 明显高于 P50，说明长尾卡在这一步">
            <BenchmarkTable rows={data?.benchmarks ?? []} loading={loading} />
          </AdminPanel>

          <AdminPanel
            title="评估样本"
            description="只展示最近 20 条，完整分数到评估看板查看"
            actions={
              <Button size="sm" variant="outline" onClick={() => refetch()} loading={loading}>
                <RefreshCw size={13} aria-hidden="true" />
                刷新
              </Button>
            }
          >
            <EvaluationQuickTable rows={data?.evaluations ?? []} loading={loading} runningId={runningId} onRun={runOne} />
          </AdminPanel>
        </>
      )}

      <ConfirmDialog
        open={batchOpen}
        title="运行全量评估？"
        description="会把所有待评估样本排进队列，逐条调用模型评分，可能持续较长时间并产生费用。"
        confirmLabel="开始运行"
        onConfirm={runBatch}
        onCancel={() => setBatchOpen(false)}
        danger={false}
      />
    </div>
  );
};
