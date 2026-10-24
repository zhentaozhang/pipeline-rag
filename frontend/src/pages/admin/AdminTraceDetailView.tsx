import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, ExternalLink, RefreshCw } from 'lucide-react';
import { manageApi } from '../../lib/api';
import { useAsyncData } from '../../lib/useAsyncData';
import type { TraceDetail } from '../../types/api';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Skeleton } from '../../components/ui/Skeleton';
import { AdminPageHeader } from '../../components/admin/AdminPageHeader';
import { AdminPanel } from '../../components/admin/AdminPanel';
import { AdminStatGrid } from '../../components/admin/AdminStatGrid';
import { AdminStatusBadge } from '../../components/admin/AdminStatusBadge';
import { SpanWaterfall } from '../../components/admin/traces/SpanWaterfall';
import { TraceScoreList } from '../../components/admin/traces/TraceScoreList';
import { formatMs, formatNumber, loadFailure } from '../../components/admin/adminFormat';
import { formatDateTime } from '../../lib/observabilityHelpers';

function rootDuration(trace: TraceDetail): number {
  const root = trace.spans.find((span) => span.spanId === trace.rootSpanId) ?? trace.spans.find((span) => !span.parentSpanId);
  const direct = Number(root?.durationMs ?? 0);
  if (direct > 0) return direct;
  // 老链路缺根耗时，用各 span 之和近似，避免整页显示 0
  return trace.spans.reduce((sum, span) => sum + Number(span.durationMs ?? 0), 0);
}

function renderPayload(payload: unknown): string {
  if (payload === null || payload === undefined) return '（空）';
  return typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2);
}

/** 单条链路的详情：span 瀑布定位瓶颈，打分看质量 */
export const AdminTraceDetailView: React.FC = () => {
  const { traceId = '' } = useParams();
  const { data, loading, error, refetch } = useAsyncData<TraceDetail>(() => manageApi.getTraceDetail(traceId), [traceId]);

  const failedSpans = data ? data.spans.filter((span) => span.status && span.status.toLowerCase() !== 'ok').length : 0;

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        eyebrow="Trace 链路"
        title={traceId || '链路详情'}
        description="耗时条长度相对这条链路最慢的 span。点任意一行可以展开输入输出。"
        actions={
          <>
            <Button size="sm" variant="outline" onClick={() => window.history.back()}>
              <ArrowLeft size={13} aria-hidden="true" />
              返回
            </Button>
            <Button size="sm" variant="outline" onClick={() => refetch()} loading={loading}>
              <RefreshCw size={13} aria-hidden="true" />
              刷新
            </Button>
            {data?.langfuseUrl ? (
              <Button size="sm" variant="outline" onClick={() => window.open(String(data.langfuseUrl), '_blank', 'noopener')}>
                <ExternalLink size={13} aria-hidden="true" />
                Langfuse
              </Button>
            ) : null}
          </>
        }
      />

      {loading && !data ? (
        <div className="flex flex-col gap-4">
          <Skeleton lines={3} />
          <Skeleton lines={10} />
        </div>
      ) : error ? (
        <Alert variant="destructive" title="加载链路详情失败" action={<Button size="sm" variant="outline" onClick={() => refetch()}>重试</Button>}>
          {loadFailure(error, '链路详情')}
        </Alert>
      ) : data ? (
        <>
          <AdminStatGrid
            stats={[
              { label: '总耗时', value: formatMs(rootDuration(data)) },
              { label: 'Span 数', value: formatNumber(data.spans.length), hint: `异常 ${failedSpans} 个`, tone: failedSpans > 0 ? 'destructive' : 'default' },
              { label: '打分项', value: formatNumber(data.scores.length), hint: data.scores.length === 0 ? '还没跑评估' : '已在线打分' },
              { label: '创建时间', value: formatDateTime(data.createdAt), hint: data.flushedAt ? `落盘 ${formatDateTime(data.flushedAt)}` : '尚未落盘' },
            ]}
          />

          <div className="flex flex-wrap items-center gap-2">
            <AdminStatusBadge label={failedSpans > 0 ? '有异常 span' : '全部成功'} tone={failedSpans > 0 ? 'destructive' : 'success'} />
            {data.conversationId ? (
              <Link
                to={`/admin/observability/${data.conversationId}`}
                className="font-mono text-2xs text-primary underline-offset-2 hover:underline"
              >
                会话 {data.conversationId}
              </Link>
            ) : null}
            {data.exchangeId ? <span className="font-mono text-2xs text-muted-foreground">exchange #{data.exchangeId}</span> : null}
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.6fr_1fr]">
            <AdminPanel title="Span 瀑布" description="按调用树缩进，颜色区分 span 类型">
              <SpanWaterfall spans={data.spans} />
            </AdminPanel>

            <div className="flex flex-col gap-4">
              <AdminPanel title="质量打分">
                <TraceScoreList scores={data.scores} />
              </AdminPanel>

              <AdminPanel title="链路输入">
                <pre className="max-h-64 overflow-auto rounded-md border border-border bg-secondary/40 p-2 text-2xs leading-relaxed text-foreground">
                  {renderPayload(data.input)}
                </pre>
              </AdminPanel>

              <AdminPanel title="链路输出">
                <pre className="max-h-64 overflow-auto rounded-md border border-border bg-secondary/40 p-2 text-2xs leading-relaxed text-foreground">
                  {renderPayload(data.output)}
                </pre>
              </AdminPanel>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
};
