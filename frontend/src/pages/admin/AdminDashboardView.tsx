import React from 'react';
import { useNavigate } from 'react-router-dom';
import { FilePlus2, RefreshCw } from 'lucide-react';
import { manageApi } from '../../lib/api';
import type { ManageDocument } from '../../types/api';
import { Button } from '../../components/ui/Button';
import { EmptyState } from '../../components/ui/EmptyState';
import { Skeleton } from '../../components/ui/Skeleton';
import { AdminPageHeader } from '../../components/admin/AdminPageHeader';
import { AdminPanel } from '../../components/admin/AdminPanel';
import { AdminStatGrid } from '../../components/admin/AdminStatGrid';
import { AdminStatusBadge } from '../../components/admin/AdminStatusBadge';
import { useAsyncData } from '../../lib/useAsyncData';
import { loadFailure } from '../../components/admin/adminFormat';

const isStatus = (value: unknown, code: number) => String(value ?? '') === String(code);

const DEMO_STEPS = [
  { title: '上传文档', desc: '在「接入文档」上传 PDF / Word / Markdown，系统会先做解析。' },
  { title: '确认推荐策略', desc: '按文档结构推荐结构切块、递归分块、语义分块与智能切块的组合。' },
  { title: '构建索引', desc: '在推荐结果上增删策略后触发异步构建，完成后才能参与检索。' },
  { title: '看对话观测', desc: '在「对话观测」里看真实会话的检索与生成轨迹。' },
];

interface DashboardData {
  total: number;
  documents: ManageDocument[];
  parseSuccess: number;
  strategyConfirmed: number;
  indexSuccess: number;
}

/** 流水线总览：一眼看清文档在当前处理到哪一步 */
export const AdminDashboardView: React.FC = () => {
  const navigate = useNavigate();

  const { data, loading, error, refetch } = useAsyncData<DashboardData>(async () => {
    const response = await manageApi.queryDocumentPage({ pageNo: 1, pageSize: 50, keyword: '' });
    const documents = Array.isArray(response?.records) ? response.records : [];
    return {
      // 概览只看最近 50 份，总数以后端 total 为准
      total: Number(response?.total ?? documents.length),
      documents,
      parseSuccess: documents.filter((item) => isStatus(item.parseStatus, 3)).length,
      strategyConfirmed: documents.filter((item) => isStatus(item.strategyStatus, 3)).length,
      indexSuccess: documents.filter((item) => isStatus(item.indexStatus, 3)).length,
    };
  }, []);

  const stats = data
    ? [
        { label: '文档总数', value: String(data.total), hint: '已进入管理台的文档记录' },
        { label: '解析成功', value: String(data.parseSuccess), hint: '最近 50 份中可进入策略确认的' },
        { label: '策略已确认', value: String(data.strategyConfirmed), hint: '最近 50 份中已完成切块配置的' },
        { label: '索引完成', value: String(data.indexSuccess), hint: '最近 50 份中可参与检索的' },
      ]
    : [];

  const recent = data?.documents.slice(0, 6) ?? [];

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4">
      <AdminPageHeader
        eyebrow="流水线总览"
        title="文档处理流水线"
        description="从上传、策略确认、索引构建到对话观测，这里汇总当前整体进度。"
        actions={
          <>
            <Button variant="outline" loading={loading} onClick={() => refetch()}>
              <RefreshCw size={14} aria-hidden="true" />
              刷新
            </Button>
            <Button onClick={() => navigate('/admin/documents')}>
              <FilePlus2 size={14} aria-hidden="true" />
              前往接入文档
            </Button>
          </>
        }
      />

      {error ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-card p-3">
          <p className="text-xs text-destructive">{loadFailure(error, '后台概览')}</p>
          <Button size="sm" variant="outline" onClick={() => refetch()}>
            重试
          </Button>
        </div>
      ) : null}

      {stats.length > 0 ? (
        <AdminStatGrid stats={stats} columns={4} />
      ) : (
        <AdminStatGrid
          stats={[
            { label: '文档总数', value: loading ? '—' : '0', hint: '已进入管理台的文档记录' },
            { label: '解析成功', value: loading ? '—' : '0', hint: '最近 50 份中可进入策略确认的' },
            { label: '策略已确认', value: loading ? '—' : '0', hint: '最近 50 份中已完成切块配置的' },
            { label: '索引完成', value: loading ? '—' : '0', hint: '最近 50 份中可参与检索的' },
          ]}
          columns={4}
        />
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <AdminPanel title="建议演示路径" description="第一次使用按这个顺序走一遍，能把整条链路看清。">
          <ol className="relative ml-3 flex flex-col gap-5 border-l border-border pl-6">
            {DEMO_STEPS.map((step, index) => (
              <li key={step.title} className="relative">
                <span className="absolute -left-[2.1rem] flex h-6 w-6 items-center justify-center rounded-full border border-border bg-card font-mono text-2xs text-muted-foreground">
                  {index + 1}
                </span>
                <h3 className="text-xs font-medium text-foreground">{step.title}</h3>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{step.desc}</p>
              </li>
            ))}
          </ol>
        </AdminPanel>

        <AdminPanel title="最近接入文档" description="按更新时间取最近 6 份。">
          {loading && recent.length === 0 ? (
            <Skeleton lines={4} />
          ) : recent.length === 0 ? (
            <EmptyState
              title="还没有文档"
              description="先上传一份资料，这里就会显示它的解析与索引状态。"
              action={
                <Button size="sm" onClick={() => navigate('/admin/documents')}>
                  去上传
                </Button>
              }
              compact
            />
          ) : (
            <ul className="flex flex-col gap-2">
              {recent.map((item) => (
                <li key={item.documentId}>
                  <button
                    type="button"
                    onClick={() => navigate(`/admin/documents/${item.documentId}`)}
                    className="flex w-full items-start justify-between gap-3 rounded-lg border border-border px-3 py-2 text-left transition-colors hover:border-primary/40 hover:bg-secondary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-medium text-foreground">{item.documentName}</span>
                      <span className="mt-0.5 block truncate font-mono text-2xs text-muted-foreground">{item.originalFileName}</span>
                    </span>
                    <span className="flex shrink-0 flex-col items-end gap-1">
                      <AdminStatusBadge type="parse" code={item.parseStatus} label={item.parseStatusName || '解析状态未知'} />
                      <AdminStatusBadge type="index" code={item.indexStatus} label={item.indexStatusName || '索引状态未知'} />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </AdminPanel>
      </div>
    </div>
  );
};
