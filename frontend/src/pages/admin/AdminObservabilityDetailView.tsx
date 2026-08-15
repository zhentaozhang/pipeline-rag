import React, { useState, useEffect, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { chatApi } from '../../lib/api';
import type { ChannelExecution, RetrievalResult, SessionDetail } from '../../types/api';
interface ModelUsageTrace {
  totalTokens?: number;
  estimatedCost?: number;
  [key: string]: unknown;
}

interface StageTrace {
  stageId?: string | number;
  stageName?: string;
  stageState?: string;
  [key: string]: unknown;
}
import {
  buildExchangeStatusNarrative,
  formatChatMode,
  formatDateTime,
  formatExecutionMode,
  formatStatusLabel,
  normalizeError,
  statusTone,
} from '../../lib/observabilityHelpers';
import { RAGSankeyView } from '../../components/admin/RAGSankeyView';

export const AdminObservabilityDetailView: React.FC = () => {
  const { conversationId, exchangeId } = useParams<{ conversationId: string; exchangeId: string }>();

  const [loadingPage, setLoadingPage] = useState(false);
  const [activeSession, setActiveSession] = useState<SessionDetail | null>(null);
  const [activeExchangeDetail, setActiveExchangeDetail] = useState<Record<string, unknown> | null>(null);
  const [channelExecutions, setChannelExecutions] = useState<ChannelExecution[]>([]);
  const [retrievalResults, setRetrievalResults] = useState<RetrievalResult[]>([]);
  const [pageError, setPageError] = useState('');

  const activeExchange: Record<string, unknown> | null =
    (activeExchangeDetail?.exchange as Record<string, unknown> | undefined) || null;
  const stageTraces: StageTrace[] =
    activeExchangeDetail && Array.isArray(activeExchangeDetail.stageTraces)
      ? (activeExchangeDetail.stageTraces as StageTrace[])
      : [];

  const loadPage = async () => {
    if (!conversationId || !exchangeId) return;

    setLoadingPage(true);
    setPageError('');
    try {
      const [session, exchangeDetail, executions, results] = await Promise.all([
        chatApi.getSession(conversationId),
        chatApi.getExchangeDetail(conversationId, exchangeId),
        chatApi.getChannelExecutions(conversationId, exchangeId).catch(() => []),
        chatApi.getRetrievalResults(conversationId, exchangeId).catch(() => [])
      ]);
      setActiveSession(session);
      setActiveExchangeDetail((exchangeDetail as Record<string, unknown> | null) ?? null);
      setChannelExecutions(Array.isArray(executions) ? (executions as ChannelExecution[]) : []);
      setRetrievalResults(Array.isArray(results) ? (results as RetrievalResult[]) : []);
    } catch (error) {
      setActiveSession(null);
      setActiveExchangeDetail(null);
      setPageError(normalizeError(error, '加载轮次详情失败'));
    } finally {
      setLoadingPage(false);
    }
  };

  useEffect(() => {
    void (async () => {
      await loadPage();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, exchangeId]);

  const currentExchangeNarrative = useMemo(() => {
    if (!activeExchange) return '这页只负责看这一轮的执行链路。';
    return buildExchangeStatusNarrative(activeExchange);
  }, [activeExchange]);

  const totalTokenCount = useMemo(() => {
    const traces = (activeExchange?.debugTrace as { modelUsageTraces?: ModelUsageTrace[] } | undefined)
      ?.modelUsageTraces || [];
    return traces.reduce((sum, item) => sum + Number(item.totalTokens || 0), 0) || '无';
  }, [activeExchange]);

  const totalCostText = useMemo(() => {
    const traces = (activeExchange?.debugTrace as { modelUsageTraces?: ModelUsageTrace[] } | undefined)
      ?.modelUsageTraces || [];
    const total = traces.reduce((sum, item) => sum + Number(item.estimatedCost || 0), 0);
    return total > 0 ? `¥ ${total.toFixed(4)}` : '无';
  }, [activeExchange]);

  const getStatusColor = (tone: string) => {
    if (tone === 'running') return 'bg-primary/10 text-primary border border-primary/20';
    if (tone === 'completed') return 'bg-success/10 text-success border border-success/20';
    if (tone === 'failed') return 'bg-destructive/10 text-destructive border border-destructive/20';
    if (tone === 'warning') return 'bg-warning/10 text-warning border border-warning/20';
    return 'bg-secondary/30 text-muted-foreground border border-border/50';
  };

  return (
    <div className="p-6 md:p-8 flex flex-col gap-6 max-w-7xl mx-auto w-full">
      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <Link 
          to={`/admin/observability/${conversationId}`}
          className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          返回会话轮次列表
        </Link>

        <div className="flex items-center gap-3">
          <button 
            onClick={loadPage}
            disabled={loadingPage}
            className="px-4 py-2 bg-card border border-border/50 rounded-md text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors disabled:opacity-50"
          >
            {loadingPage ? '刷新中...' : '刷新详情'}
          </button>
        </div>
      </div>

      {pageError && (
        <div className="p-4 bg-destructive/10 text-destructive rounded-lg text-sm border border-destructive/20">
          {pageError}
        </div>
      )}

      {loadingPage && !activeExchangeDetail ? (
        <div className="p-12 text-center text-muted-foreground border border-dashed border-border/50 rounded-xl bg-card">
          正在加载轮次详情...
        </div>
      ) : !activeExchange ? (
        <div className="p-12 text-center text-muted-foreground border border-dashed border-border/50 rounded-xl bg-card">
          没有找到这条轮次，请返回会话页重新选择。
        </div>
      ) : (
        <>
          {/* Header */}
          <div className="border-b border-border/50 pb-6">
            <span className="text-xs font-mono text-muted-foreground uppercase tracking-widest">轮次详情</span>
            <h2 className="text-2xl font-bold font-heading text-foreground mt-2 mb-3">
              {String(activeExchange?.question || '未记录问题')}
            </h2>
            <p className="text-sm text-muted-foreground max-w-3xl leading-relaxed mb-4">
              {currentExchangeNarrative}
            </p>
            <div className="flex flex-wrap gap-2 mb-6">
              <span className={`px-2 py-1 text-xs font-medium rounded ${getStatusColor(statusTone(activeExchange.status))}`}>
                {formatStatusLabel(activeExchange.status)}
              </span>
              <span className="px-2 py-1 text-xs font-medium rounded bg-secondary border border-border/50 text-foreground">
                {formatChatMode(activeSession?.chatMode)}
              </span>
              {(activeExchange.debugTrace as { executionMode?: string } | undefined)?.executionMode && (
                <span className="px-2 py-1 text-xs font-medium rounded bg-secondary border border-border/50 text-muted-foreground">
                  {formatExecutionMode(
                    (activeExchange.debugTrace as { executionMode?: string } | undefined)?.executionMode || ''
                  )}
                </span>
              )}
              <span className="px-2 py-1 text-xs font-medium rounded bg-secondary border border-border/50 text-muted-foreground font-mono">
                会话 {conversationId}
              </span>
              <span className="px-2 py-1 text-xs font-medium rounded bg-secondary border border-border/50 text-muted-foreground font-mono">
                轮次 {exchangeId}
              </span>
            </div>

            <dl className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div className="flex flex-col gap-1">
                <dt className="text-xs text-muted-foreground uppercase tracking-wider">文档范围</dt>
                <dd className="text-sm font-medium text-foreground truncate">
                  {activeSession?.selectedDocumentName || '未绑定文档'}
                </dd>
              </div>
              <div className="flex flex-col gap-1">
                <dt className="text-xs text-muted-foreground uppercase tracking-wider">执行时间</dt>
                <dd className="text-sm font-medium text-foreground">
                  {formatDateTime(activeExchange.editTime || activeExchange.createTime)}
                </dd>
              </div>
              <div className="flex flex-col gap-1">
                <dt className="text-xs text-muted-foreground uppercase tracking-wider">总耗时</dt>
                <dd className="text-sm font-medium text-foreground">
                  {activeExchange.totalResponseTimeMs ? `${activeExchange.totalResponseTimeMs} ms` : '无'}
                </dd>
              </div>
              <div className="flex flex-col gap-1">
                <dt className="text-xs text-muted-foreground uppercase tracking-wider">引用 / 推荐</dt>
                <dd className="text-sm font-medium text-foreground">
                  {(activeExchange.references as unknown[] | undefined)?.length || 0} / {
                    (activeExchange.recommendations as unknown[] | undefined)?.length || 0
                  }
                </dd>
              </div>
              <div className="flex flex-col gap-1">
                <dt className="text-xs text-muted-foreground uppercase tracking-wider">总 Token / 成本</dt>
                <dd className="text-sm font-medium text-foreground">
                  {totalTokenCount} / {totalCostText}
                </dd>
              </div>
            </dl>
          </div>

          {/* RAG Sankey Pipeline */}
          <RAGSankeyView 
            channelExecutions={channelExecutions}
            retrievalResults={retrievalResults}
            activeExchange={activeExchange}
          />

          {/* Timeline Section */}
          <section>
            <h3 className="text-lg font-semibold font-heading text-foreground mb-1">
              <span className="block text-xs font-mono text-muted-foreground uppercase tracking-widest mb-1">执行时间线</span>
              执行阶段时间线
            </h3>
            <p className="text-sm text-muted-foreground mb-6">各阶段的执行耗时与状态。</p>

            {!stageTraces.length ? (
              <div className="p-8 text-center text-muted-foreground border border-dashed border-border/50 rounded-xl bg-card">
                当前轮次还没有可展示的阶段轨迹。
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                {stageTraces.map((trace, index) => {
                  const tone = statusTone(trace.stageState || '');
                  return (
                    <div key={trace.stageId} className="flex gap-4">
                      {/* Timeline dot */}
                      <div className="flex flex-col items-center pt-2">
                        <div className={`w-3 h-3 rounded-full shrink-0 z-10 ${
                          tone === 'running' ? 'bg-primary animate-pulse' :
                          tone === 'completed' ? 'bg-success' :
                          tone === 'failed' ? 'bg-destructive' : 'bg-warning'
                        }`} />
                        {index < stageTraces.length - 1 && (
                          <div className="w-0.5 flex-1 bg-border/60 mt-2" />
                        )}
                      </div>

                      <div className="flex-1 bg-card border border-border/40 rounded-xl p-5 shadow-sm mb-2 hover:shadow-md transition-shadow">
                        <div className="flex justify-between items-start mb-2">
                          <div className="flex items-center gap-3">
                            <strong className="text-base text-foreground font-heading">
                              {trace.stageName}
                            </strong>
                            <span className={`px-2 py-0.5 text-xs font-medium rounded ${getStatusColor(tone)}`}>
                              {formatStatusLabel(trace.stageState)}
                            </span>
                          </div>
                          <span className="text-xs text-muted-foreground font-mono">{formatDateTime(trace.startTime)}</span>
                        </div>
                        <p className="text-sm text-foreground/80 mb-3 leading-relaxed">
                          {String(trace.summaryText || '当前阶段已记录。')}
                        </p>
                        <div className="text-xs text-muted-foreground font-mono">
                          耗时 {trace.durationMs ? `${trace.durationMs} ms` : '无'}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* Simple Answer Block for Completeness */}
          <section className="mt-4 border-t border-border/50 pt-6">
            <h3 className="text-lg font-semibold font-heading text-foreground mb-4">
               最终回答
            </h3>
            <div className="p-5 bg-card rounded-xl text-foreground leading-relaxed text-sm whitespace-pre-wrap border border-border/40 shadow-sm">
              {String(activeExchange.answer || '没有回答。')}
            </div>
          </section>
        </>
      )}
    </div>
  );
};
