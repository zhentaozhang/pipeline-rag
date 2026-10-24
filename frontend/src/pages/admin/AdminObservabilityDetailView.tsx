import React from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { chatApi } from '../../lib/api';
import {
  buildExchangeStatusNarrative,
  formatChatMode,
  formatDateTime,
  formatExecutionMode,
  formatStatusLabel,
  statusTone,
} from '../../lib/observabilityHelpers';
import { useAsyncData } from '../../lib/useAsyncData';
import type { ChannelExecution, ExchangeReference, RetrievalResult, SessionDetail } from '../../types/api';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Skeleton } from '../../components/ui/Skeleton';
import { AdminPageHeader } from '../../components/admin/AdminPageHeader';
import { AdminPanel } from '../../components/admin/AdminPanel';
import { AdminStatGrid } from '../../components/admin/AdminStatGrid';
import { AdminStatusBadge } from '../../components/admin/AdminStatusBadge';
import { RAGSankeyView } from '../../components/admin/RAGSankeyView';
import { StageTimeline, type StageTrace } from '../../components/admin/observability/StageTimeline';
import { formatCost, formatMs, loadFailure } from '../../components/admin/adminFormat';

interface UsageTrace {
  totalTokens?: number;
  estimatedCost?: number;
}

interface ExchangeDetailResponse {
  exchange?: Record<string, unknown>;
  stageTraces?: StageTrace[];
}

interface DetailBundle {
  session: SessionDetail;
  exchangeDetail: ExchangeDetailResponse | null;
  channelExecutions: ChannelExecution[];
  retrievalResults: RetrievalResult[];
}

function usageOf(exchange: Record<string, unknown> | null): { tokens: number; cost: number } {
  const traces = (exchange?.debugTrace as { modelUsageTraces?: UsageTrace[] } | undefined)?.modelUsageTraces ?? [];
  return traces.reduce(
    (acc, item) => ({
      tokens: acc.tokens + Number(item?.totalTokens ?? 0),
      cost: acc.cost + Number(item?.estimatedCost ?? 0),
    }),
    { tokens: 0, cost: 0 }
  );
}

/** 单轮问答的执行链路：阶段耗时、检索漏斗、引用与最终回答 */
export const AdminObservabilityDetailView: React.FC = () => {
  const { conversationId = '', exchangeId = '' } = useParams();
  const navigate = useNavigate();

  const { data, loading, error, refetch } = useAsyncData<DetailBundle>(
    async () => {
      const [session, exchangeDetail, executions, results] = await Promise.all([
        chatApi.getSession(conversationId),
        chatApi.getExchangeDetail(conversationId, exchangeId),
        chatApi.getChannelExecutions(conversationId, exchangeId).catch(() => []),
        chatApi.getRetrievalResults(conversationId, exchangeId).catch(() => []),
      ]);
      return {
        session,
        exchangeDetail: (exchangeDetail ?? null) as ExchangeDetailResponse | null,
        channelExecutions: Array.isArray(executions) ? (executions as ChannelExecution[]) : [],
        retrievalResults: Array.isArray(results) ? (results as RetrievalResult[]) : [],
      };
    },
    [conversationId, exchangeId]
  );

  const session = data?.session ?? null;
  const exchange = data?.exchangeDetail?.exchange ?? null;
  const stageTraces = data?.exchangeDetail?.stageTraces ?? [];
  const usage = usageOf(exchange);
  const references = (exchange?.references as ExchangeReference[] | undefined) ?? [];
  const recommendations = (exchange?.recommendations as string[] | undefined) ?? [];
  const narrative = exchange ? buildExchangeStatusNarrative(exchange) : '这页只负责看这一轮的执行链路。';
  const tone = String(statusTone(exchange?.status));

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        eyebrow="对话观测"
        title={String(exchange?.question ?? '轮次详情')}
        description={narrative}
        actions={
          <>
            <Button size="sm" variant="outline" onClick={() => navigate(`/admin/observability/${conversationId}`)}>
              <ArrowLeft size={13} aria-hidden="true" />
              返回会话
            </Button>
            <Button size="sm" variant="outline" onClick={() => refetch()} loading={loading}>
              <RefreshCw size={13} aria-hidden="true" />
              刷新
            </Button>
          </>
        }
      />

      {loading && !data ? (
        <Skeleton lines={8} />
      ) : error ? (
        <Alert
          variant="destructive"
          title="加载轮次详情失败"
          action={<Button size="sm" variant="outline" onClick={() => refetch()}>重试</Button>}
        >
          {loadFailure(error, '轮次详情')}
        </Alert>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <AdminStatusBadge label={formatChatMode(session?.chatMode)} />
            <AdminStatusBadge label={formatStatusLabel(String(exchange?.status ?? ''))} tone={tone === 'completed' ? 'success' : tone === 'failed' || tone === 'error' ? 'destructive' : tone === 'running' ? 'primary' : 'default'} />
            {exchange?.executionMode ? <AdminStatusBadge label={formatExecutionMode(String(exchange.executionMode))} /> : null}
            <span className="font-mono text-2xs text-muted-foreground">exchange #{exchangeId}</span>
          </div>

          <AdminStatGrid
            stats={[
              {
                label: '文档范围',
                value: session?.selectedDocumentName || session?.selectedDocumentId || '未限定',
                hint: '这一轮实际可用的文档池',
              },
              { label: '执行时间', value: formatDateTime(exchange?.createdAt as string | null), hint: '按发起时刻排序' },
              { label: '总耗时', value: formatMs(Number(exchange?.totalResponseTimeMs ?? 0)) },
              {
                label: '引用 / 推荐',
                value: `${references.length} / ${recommendations.length}`,
                hint: '引用即最终回答里的资料出处',
              },
              {
                label: 'Token / 成本',
                value: `${usage.tokens || Number(exchange?.tokensUsed ?? 0)} / ${formatCost(usage.cost)}`,
              },
            ]}
            columns={5}
          />

          {exchange?.errorMessage ? (
            <Alert variant="destructive" title="这一轮报错">
              {String(exchange.errorMessage)}
            </Alert>
          ) : null}

          <AdminPanel
            title="检索漏斗"
            description="从两路召回经过融合、重排到最终引用的数量变化"
          >
            <RAGSankeyView
              channelExecutions={data?.channelExecutions ?? []}
              retrievalResults={data?.retrievalResults ?? []}
              activeExchange={exchange}
            />
          </AdminPanel>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_1.2fr]">
            <AdminPanel title="阶段耗时" description="耗时条长度相对本轮最慢阶段">
              <StageTimeline stages={stageTraces} />
            </AdminPanel>

            <div className="flex flex-col gap-4">
              <AdminPanel title="最终回答">
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                  {String(exchange?.answer ?? '') || '这一轮没有保存回答内容。'}
                </p>
              </AdminPanel>

              <AdminPanel title="引用来源" description={`共 ${references.length} 条`}>
                {references.length === 0 ? (
                  <p className="text-sm text-muted-foreground">这一轮没有引用任何资料。可能是开放对话模式，或检索没命中。</p>
                ) : (
                  <ol className="flex flex-col gap-2">
                    {references.map((reference, index) => (
                      <li key={String(reference.id ?? reference.chunk_id ?? index)} className="rounded-lg border border-border p-2.5">
                        <p className="text-xs font-medium text-foreground">
                          {index + 1}. {reference.title || reference.name || reference.section_title || '未命名资料'}
                        </p>
                        {reference.content ? (
                          <p className="mt-1 line-clamp-2 text-2xs leading-relaxed text-muted-foreground">{String(reference.content)}</p>
                        ) : null}
                      </li>
                    ))}
                  </ol>
                )}
              </AdminPanel>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
