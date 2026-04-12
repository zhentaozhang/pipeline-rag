import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { manageApi } from '../../lib/api';
import { Button } from '../../components/ui/Button';
import { Card, CardContent } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';

interface DashboardSummary {
  total: number;
  parseSuccess: number;
  strategyConfirmed: number;
  indexSuccess: number;
}

export const AdminDashboardView: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [documents, setDocuments] = useState<any[]>([]);
  const [summary, setSummary] = useState<DashboardSummary>({
    total: 0,
    parseSuccess: 0,
    strategyConfirmed: 0,
    indexSuccess: 0
  });

  const loadDashboard = async () => {
    setLoading(true);
    try {
      const data = await manageApi.queryDocumentPage({
        pageNo: 1,
        pageSize: 50,
        keyword: ''
      });
      const docs = Array.isArray(data?.records) ? data.records : [];
      setDocuments(docs);

      const hasCode = (status: any, code: number) => String(status) === String(code);

      setSummary({
        total: Number(data?.total || docs.length || 0),
        parseSuccess: docs.filter((item: any) => hasCode(item.parseStatus, 3)).length,
        strategyConfirmed: docs.filter((item: any) => hasCode(item.strategyStatus, 3)).length,
        indexSuccess: docs.filter((item: any) => hasCode(item.indexStatus, 3)).length,
      });
    } catch (error) {
      console.error('加载后台概览失败', error);
      setDocuments([]);
      setSummary({ total: 0, parseSuccess: 0, strategyConfirmed: 0, indexSuccess: 0 });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDashboard();
  }, []);

  const formatCount = (count: number) => count.toLocaleString();

  const getStatusVariant = (code: string | number) => {
    const c = String(code);
    if (c === '3') return 'success';
    if (c === '4') return 'destructive';
    if (c === '2') return 'default'; // Or warning
    return 'secondary';
  };

  return (
    <section className="p-6 md:p-8 flex flex-col gap-6 w-full max-w-7xl mx-auto">
      {/* Hero Card */}
      <Card className="p-8 border border-border/40 bg-card shadow-sm">
        <div className="max-w-3xl">
          <h3 className="text-xl font-semibold font-heading text-foreground mb-3">
            文档处理流水线
          </h3>
          <p className="text-muted-foreground leading-relaxed mb-6">
            跟踪文档从上传到对话观测的完整流程。
          </p>
          <Button onClick={() => navigate('/admin/documents')} size="lg" className="font-medium">
            前往接入文档
          </Button>
        </div>
      </Card>

      {/* Metrics Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: '文档总数', value: summary.total, desc: '已进入管理台的文档记录' },
          { label: '解析成功', value: summary.parseSuccess, desc: '可进入策略确认阶段的文档' },
          { label: '策略已确认', value: summary.strategyConfirmed, desc: '已经形成最终切块链路' },
          { label: '索引完成', value: summary.indexSuccess, desc: '可直接参与 RAG 检索问答' },
        ].map((metric, idx) => (
          <Card key={idx} className="border-border/40 shadow-sm hover:shadow-md transition-shadow">
            <CardContent className="p-6">
              <span className="text-sm text-muted-foreground font-medium uppercase tracking-wider">{metric.label}</span>
              <strong className="block mt-3 text-3xl font-bold font-heading text-foreground">
                {formatCount(metric.value)}
              </strong>
              <p className="mt-3 text-xs text-muted-foreground leading-relaxed opacity-80">
                {metric.desc}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Main Dashboard Split */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] gap-6">
        
        {/* Left Panel: Flow */}
        <Card className="border-border/40 shadow-sm">
          <CardContent className="p-6 md:p-8">
            <div className="flex justify-between items-center mb-8">
              <h4 className="text-lg font-semibold font-heading text-foreground">建议演示路径</h4>
            </div>

            <ol className="relative border-l border-border/60 ml-3 space-y-10">
              {[
                { title: '上传文档', desc: '通过假登录后的管理台上传 PDF / Word / Markdown 文档。' },
                { title: '查看系统推荐策略', desc: '根据文档结构与内容长度，观察结构切块、递归分块、语义分块和智能切块的组合。' },
                { title: '确认并构建索引', desc: '在推荐结果基础上补充或移除策略，再触发异步构建索引。' },
                { title: '做对话观测', desc: '查看真实会话在当前文档问答与开放式提问两种模式下的执行轨迹。' }
              ].map((step, idx) => (
                <li key={idx} className="ml-8">
                  <span className="absolute flex items-center justify-center w-6 h-6 bg-card border border-border rounded-full -left-[12px] text-muted-foreground text-xs font-bold font-mono">
                    {idx + 1}
                  </span>
                  <h5 className="font-semibold text-foreground mb-1.5">{step.title}</h5>
                  <p className="text-sm text-muted-foreground leading-relaxed">{step.desc}</p>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>

        {/* Right Panel: Recent Documents */}
        <Card className="border-border/40 shadow-sm">
          <CardContent className="p-6 md:p-8">
            <div className="flex justify-between items-center mb-6">
              <h4 className="text-lg font-semibold font-heading text-foreground">最近接入文档</h4>
              <Button variant="outline" size="sm" onClick={loadDashboard} className="h-8 text-xs font-medium border-border/50">
                刷新
              </Button>
            </div>

            {loading ? (
              <div className="min-h-[220px] flex items-center justify-center text-sm text-muted-foreground border border-dashed border-border/60 rounded-lg bg-secondary/20">
                正在加载后台概览...
              </div>
            ) : documents.length === 0 ? (
              <div className="min-h-[220px] flex items-center justify-center text-sm text-muted-foreground border border-dashed border-border/60 rounded-lg bg-secondary/20">
                当前还没有文档，先去“文档接入”页面上传一份资料。
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {documents.slice(0, 6).map((item) => (
                  <div key={item.documentId} className="flex flex-col sm:flex-row justify-between gap-4 p-4 rounded-xl bg-card border border-border/40 hover:border-primary/30 hover:shadow-sm transition-all">
                    <div className="min-w-0 flex-1">
                      <strong className="block text-sm font-semibold text-foreground truncate">
                        {item.documentName}
                      </strong>
                      <p className="mt-1 text-xs text-muted-foreground truncate font-mono opacity-70">
                        {item.originalFileName}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2 items-start shrink-0">
                      <Badge variant={getStatusVariant(item.parseStatus) as any} className="font-medium text-[11px] px-2 py-0.5">
                        解析: {item.parseStatusName || '未知'}
                      </Badge>
                      <Badge variant={getStatusVariant(item.indexStatus) as any} className="font-medium text-[11px] px-2 py-0.5">
                        索引: {item.indexStatusName || '未知'}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

      </div>
    </section>
  );
};
