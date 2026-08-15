import React, { useEffect, useState } from 'react';
import { 
  BarChart3, 
  Activity, 
  Clock, 
  MessageSquare,
  AlertTriangle,
  Coins,
  PlayCircle
} from 'lucide-react';
import { 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip as RechartsTooltip, 
  ResponsiveContainer,
  LineChart,
  Line,
  Legend
} from 'recharts';
import { manageApi } from '../../lib/api';
import type { BenchmarkItem, EvaluationDataset, MetricsOverview } from '../../types/api';
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/Card';
import { Button } from '../../components/ui/Button';
import { errorMessage } from '../../lib/utils';

export const AdminMetricsView: React.FC = () => {
  const [overview, setOverview] = useState<MetricsOverview | null>(null);
  const [trend, setTrend] = useState<unknown[]>([]);
  const [benchmarks, setBenchmarks] = useState<BenchmarkItem[]>([]);
  const [evaluations, setEvaluations] = useState<EvaluationDataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [runningEval, setRunningEval] = useState(false);
  const [error, setError] = useState('');

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      const [overviewData, trendData, benchData, evalData] = await Promise.all([
        manageApi.getMetricsOverview(),
        manageApi.getUsageTrend(14),
        manageApi.getBenchmarks(),
        manageApi.listEvaluationDataset({ pageNo: 1, pageSize: 20 })
      ]);
      setOverview(overviewData);
      setTrend(Array.isArray(trendData) ? trendData : []);
      setBenchmarks(Array.isArray(benchData) ? (benchData as BenchmarkItem[]) : []);
      // The dataset might be wrapped in records/list depending on backend, handle gracefully
      setEvaluations(evalData?.records || []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载指标数据失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void (async () => {
      await loadData();
    })();
  }, []);

  const handleRunEvaluation = async (datasetId?: number) => {
    if (!confirm('确定要触发评估任务吗？这将消耗较多大模型调用额度。')) {
      return;
    }
    setRunningEval(true);
    try {
      await manageApi.runEvaluation(datasetId ? [datasetId] : undefined);
      alert('评估任务已触发');
    } catch (e) {
      alert(`触发失败: ${errorMessage(e)}`);
    } finally {
      setRunningEval(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center h-full min-h-[500px]">
        <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin mb-4" />
        <p className="text-muted-foreground text-sm">正在加载指标数据...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <div className="bg-destructive/10 text-destructive px-4 py-3 rounded-md flex items-center gap-2">
          <AlertTriangle size={18} />
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto space-y-8 animate-in fade-in duration-500">
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <BarChart3 className="text-primary" />
            观测指标看板
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            实时总览对话系统运行状态、成本消耗及性能基准。
          </p>
        </div>
        <Button onClick={loadData} variant="outline" className="shrink-0">
          刷新数据
        </Button>
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card className="hover:shadow-md transition-shadow">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex justify-between">
              总对话轮次
              <MessageSquare size={16} className="text-primary/70" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{overview?.totalExchanges || 0}</div>
            <p className="text-xs text-muted-foreground mt-1">
              活跃会话数: {overview?.activeConversations || 0}
            </p>
          </CardContent>
        </Card>

        <Card className="hover:shadow-md transition-shadow">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex justify-between">
              平均响应耗时
              <Clock size={16} className="text-amber-500" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{overview?.avgResponseTimeMs || 0} <span className="text-sm font-normal text-muted-foreground">ms</span></div>
            <p className="text-xs text-muted-foreground mt-1">
              失败率: {overview?.errorRate || 0}%
            </p>
          </CardContent>
        </Card>

        <Card className="hover:shadow-md transition-shadow">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex justify-between">
              今日 Token 消耗
              <Activity size={16} className="text-green-500" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{(overview?.todayTokens || 0).toLocaleString()}</div>
            <p className="text-xs text-muted-foreground mt-1">
              总计: {(overview?.totalTokens || 0).toLocaleString()} Tokens
            </p>
          </CardContent>
        </Card>

        <Card className="hover:shadow-md transition-shadow">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex justify-between">
              今日预估成本
              <Coins size={16} className="text-blue-500" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">${overview?.todayCost || 0}</div>
            <p className="text-xs text-muted-foreground mt-1">
              总计: ${overview?.totalCost || 0}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Usage Trend Charts */}
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="text-lg">近 14 天 Token 用量趋势</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-[300px] w-full mt-4">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trend} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                <XAxis dataKey="date" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis yAxisId="left" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(val) => `${val / 1000}k`} />
                <YAxis yAxisId="right" orientation="right" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} />
                <RechartsTooltip 
                  contentStyle={{ backgroundColor: 'hsl(var(--background))', borderColor: 'hsl(var(--border))', borderRadius: '8px' }}
                  itemStyle={{ color: 'hsl(var(--foreground))' }}
                />
                <Legend />
                <Line yAxisId="left" type="monotone" dataKey="tokens" name="Tokens 消耗" stroke="hsl(var(--primary))" strokeWidth={3} dot={{ r: 4 }} activeDot={{ r: 6 }} />
                <Line yAxisId="right" type="monotone" dataKey="calls" name="调用次数" stroke="#10b981" strokeWidth={3} dot={{ r: 4 }} activeDot={{ r: 6 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Benchmarks & Evaluations Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Benchmarks Table */}
        <Card className="flex flex-col">
          <CardHeader>
            <CardTitle className="text-lg">流水线阶段耗时基准</CardTitle>
          </CardHeader>
          <CardContent className="flex-1 overflow-auto">
            <div className="rounded-md border border-border">
              <table className="w-full text-sm text-left">
                <thead className="bg-secondary/50 text-muted-foreground text-xs uppercase">
                  <tr>
                    <th className="px-4 py-3 font-medium">阶段代码</th>
                    <th className="px-4 py-3 font-medium">执行模式</th>
                    <th className="px-4 py-3 font-medium text-right">P50</th>
                    <th className="px-4 py-3 font-medium text-right">P90</th>
                    <th className="px-4 py-3 font-medium text-right">P99</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {benchmarks.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">暂无基准数据</td>
                    </tr>
                  ) : (
                    benchmarks.map((bench, idx) => (
                      <tr key={idx} className="hover:bg-secondary/30 transition-colors">
                        <td className="px-4 py-3 font-medium text-foreground">{bench.stageCode}</td>
                        <td className="px-4 py-3 text-muted-foreground">{bench.executionMode || '-'}</td>
                        <td className="px-4 py-3 text-right">{bench.p50Ms} ms</td>
                        <td className="px-4 py-3 text-right">{bench.p90Ms} ms</td>
                        <td className="px-4 py-3 text-right font-medium text-amber-500">{bench.p99Ms} ms</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        {/* Evaluations */}
        <Card className="flex flex-col">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-lg">评估数据集 (RAGAS)</CardTitle>
            <Button 
              size="sm" 
              onClick={() => handleRunEvaluation()} 
              disabled={runningEval}
              className="gap-2"
            >
              <PlayCircle size={16} />
              {runningEval ? '评估中...' : '全量评估'}
            </Button>
          </CardHeader>
          <CardContent className="flex-1 overflow-auto">
            <div className="rounded-md border border-border mt-2">
              <table className="w-full text-sm text-left">
                <thead className="bg-secondary/50 text-muted-foreground text-xs uppercase">
                  <tr>
                    <th className="px-4 py-3 font-medium">数据集 ID</th>
                    <th className="px-4 py-3 font-medium">描述</th>
                    <th className="px-4 py-3 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {evaluations.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="px-4 py-8 text-center text-muted-foreground">暂无评估数据集</td>
                    </tr>
                  ) : (
                    evaluations.map((item, idx) => (
                      <tr key={item.id || idx} className="hover:bg-secondary/30 transition-colors">
                        <td className="px-4 py-3 font-medium text-foreground">{item.id}</td>
                        <td className="px-4 py-3 text-muted-foreground truncate max-w-[200px]" title={item.description || item.question}>{item.description || item.question || '-'}</td>
                        <td className="px-4 py-3 text-right">
                          <Button 
                            variant="ghost" 
                            size="sm"
                            className="h-8 px-2"
                            onClick={() => handleRunEvaluation(item.id)}
                            disabled={runningEval}
                          >
                            运行
                          </Button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};
