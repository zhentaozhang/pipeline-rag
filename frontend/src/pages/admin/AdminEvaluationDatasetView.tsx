import React, { useEffect, useState } from 'react';
import { Card } from '../../components/ui/Card';
import { Button } from '../../components/ui/Button';
import { manageApi } from '../../lib/api';
import { Database, Search, Beaker, CheckCircle2, Play, Trash2, Loader2 } from 'lucide-react';
import { formatDateTime } from '../../lib/manageFormat';
import { errorMessage } from '../../lib/utils';

interface DatasetItem {
  id: number;
  question?: string;
  groundTruth?: string;
  status?: number;
  sourceType?: string;
  conversationId?: string;
  createdAt?: string | null;
  faithfulnessScore?: number | null;
  answerRelevancyScore?: number | null;
  contextPrecisionScore?: number | null;
  contextRecallScore?: number | null;
  answerCorrectnessScore?: number | null;
  [key: string]: unknown;
}

export const AdminEvaluationDatasetView: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [items, setItems] = useState<DatasetItem[]>([]);
  const [total, setTotal] = useState(0);
  const [pageNo, setPageNo] = useState(1);
  const pageSize = 10;

  const loadData = async (page: number) => {
    try {
      setLoading(true);
      const res = await manageApi.listEvaluationDataset({ pageNo: page, pageSize });
      setItems(res.records || []);
      setTotal(res.total || 0);
      setPageNo(page);
    } catch (e) {
      console.error('Failed to load dataset:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData(1);
  }, []);

  const handleRunEvaluation = async (id?: number) => {
    try {
      setRunning(true);
      const res = await manageApi.runEvaluation(id ? [id] : undefined);
      alert(res?.message || '已触发评估任务，请等待后台执行完毕刷新页面查看结果。');
      await loadData(pageNo); // refresh
    } catch (e) {
      alert(`触发失败: ${errorMessage(e)}`);
      console.error('Failed to run evaluation:', e);
    } finally {
      setRunning(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除这条测试数据吗？')) return;
    try {
      setLoading(true);
      const res = await manageApi.deleteEvaluationDataset(id);
      alert(res?.message || '删除成功');
      await loadData(pageNo);
    } catch (e) {
      alert(`删除失败: ${errorMessage(e)}`);
      console.error('Failed to delete:', e);
      setLoading(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="p-8 max-w-[1400px] mx-auto space-y-8 animate-in fade-in duration-500">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground flex items-center gap-3">
            <Database className="text-primary" size={32} />
            评估测试集 (Golden Dataset)
          </h1>
          <p className="text-muted-foreground mt-2">
            收集用户的预期答案反馈，作为 RAG 回归测试和评估打分的标准数据集。
          </p>
        </div>
        <div className="flex gap-3">
            <Button 
            variant="default" 
            className="flex items-center gap-2"
            onClick={() => handleRunEvaluation()}
            disabled={running || items.filter(i => i.status === 1).length === 0}
          >
            {running ? <Loader2 size={18} className="animate-spin" /> : <Beaker size={18} />}
            批量运行 Ragas 评估
          </Button>
        </div>
      </div>

      <Card className="p-0 overflow-hidden border border-border/50 shadow-sm">
        <div className="p-4 border-b border-border/50 bg-secondary/20 flex gap-4 items-center">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={18} />
            <input 
              type="text"
              placeholder="搜索问题或答案..."
              className="w-full pl-10 pr-4 py-2 bg-background border border-border/50 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="bg-secondary/30 text-muted-foreground uppercase text-xs tracking-wider">
              <tr>
                <th className="px-6 py-4 font-medium">问题 (Question)</th>
                <th className="px-6 py-4 font-medium">期望答案 (Ground Truth)</th>
                <th className="px-6 py-4 font-medium w-32">来源</th>
                <th className="px-6 py-4 font-medium w-48">Ragas 指标</th>
                <th className="px-6 py-4 font-medium w-32">状态</th>
                <th className="px-6 py-4 font-medium w-48">创建时间</th>
                <th className="px-6 py-4 font-medium w-32 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {loading && items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-muted-foreground">
                    加载中...
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-muted-foreground">
                    暂无测试数据
                  </td>
                </tr>
              ) : (
                items.map((item) => (
                  <tr key={item.id} className="hover:bg-secondary/20 transition-colors">
                    <td className="px-6 py-4">
                      <div className="text-foreground font-medium line-clamp-3 leading-relaxed">
                        {item.question}
                      </div>
                      <div className="text-xs text-muted-foreground mt-2 font-mono opacity-60">ID: {item.id}</div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-muted-foreground line-clamp-3 leading-relaxed">
                        {item.groundTruth}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className="px-2 py-1 bg-blue-500/10 text-blue-500 text-xs rounded border border-blue-500/20 whitespace-nowrap">
                        {item.sourceType === 'user_feedback' ? '用户反馈' : item.sourceType}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      {item.status === 2 && (
                        <div className="flex flex-col gap-1 text-[11px] font-mono">
                          <div className="flex justify-between w-32">
                            <span className="text-muted-foreground">Faithful:</span>
                            <span className={item.faithfulnessScore && item.faithfulnessScore >= 0.8 ? "text-green-500" : "text-orange-500"}>{item.faithfulnessScore ?? '-'}</span>
                          </div>
                          <div className="flex justify-between w-32">
                            <span className="text-muted-foreground">Relevant:</span>
                            <span className={item.answerRelevancyScore && item.answerRelevancyScore >= 0.8 ? "text-green-500" : "text-orange-500"}>{item.answerRelevancyScore ?? '-'}</span>
                          </div>
                          <div className="flex justify-between w-32">
                            <span className="text-muted-foreground">Precision:</span>
                            <span className={item.contextPrecisionScore && item.contextPrecisionScore >= 0.8 ? "text-green-500" : "text-orange-500"}>{item.contextPrecisionScore ?? '-'}</span>
                          </div>
                          <div className="flex justify-between w-32">
                            <span className="text-muted-foreground">Recall:</span>
                            <span className={item.contextRecallScore && item.contextRecallScore >= 0.8 ? "text-green-500" : "text-orange-500"}>{item.contextRecallScore ?? '-'}</span>
                          </div>
                          <div className="flex justify-between w-32 font-bold mt-1 pt-1 border-t border-border/50">
                            <span className="text-foreground">Correctness:</span>
                            <span className={item.answerCorrectnessScore && item.answerCorrectnessScore >= 0.8 ? "text-green-500" : "text-orange-500"}>{item.answerCorrectnessScore ?? '-'}</span>
                          </div>
                        </div>
                      )}
                      {item.status !== 2 && (
                        <span className="text-muted-foreground text-xs">-</span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      {item.status === 2 ? (
                        <div className="flex items-center gap-1.5 text-green-500 text-xs font-medium">
                          <CheckCircle2 size={14} /> 已评估
                        </div>
                      ) : item.status === 3 ? (
                        <div className="flex items-center gap-1.5 text-blue-500 text-xs font-medium">
                          <Loader2 size={14} className="animate-spin" /> 评估中
                        </div>
                      ) : (
                        <div className="flex items-center gap-1.5 text-orange-500 text-xs font-medium">
                          <span className="w-1.5 h-1.5 rounded-full bg-orange-500" /> 待评估
                        </div>
                      )}
                    </td>
                    <td className="px-6 py-4 text-muted-foreground whitespace-nowrap">
                      {formatDateTime(item.createdAt)}
                    </td>
                    <td className="px-6 py-4 text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => handleRunEvaluation(item.id)}
                          disabled={running}
                          title="运行单条评估"
                          className="p-1.5 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded transition-colors disabled:opacity-50"
                        >
                          <Play size={16} />
                        </button>
                        <button
                          onClick={() => handleDelete(item.id)}
                          disabled={loading}
                          title="删除"
                          className="p-1.5 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded transition-colors disabled:opacity-50"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="p-4 border-t border-border/50 bg-secondary/10 flex items-center justify-between text-sm text-muted-foreground">
          <div>
            共 {total} 条记录
          </div>
          <div className="flex items-center gap-2">
            <Button 
              variant="outline" 
              size="sm"
              disabled={pageNo <= 1 || loading}
              onClick={() => loadData(pageNo - 1)}
            >
              上一页
            </Button>
            <span className="px-4 text-foreground font-medium">
              {pageNo} / {totalPages}
            </span>
            <Button 
              variant="outline" 
              size="sm"
              disabled={pageNo >= totalPages || loading}
              onClick={() => loadData(pageNo + 1)}
            >
              下一页
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
};
