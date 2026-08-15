import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { chatApi } from '../../lib/api';
import {
  formatChatMode,
  formatDateTime,
  formatExecutionMode,
  formatStatusLabel,
  listAssistantExchanges,
  normalizeError,
  sessionPreview,
  sessionTitle,
  statusTone,
  truncate
} from '../../lib/observabilityHelpers';
import type { SessionDetail } from '../../types/api';

interface ModelUsageTrace {
  totalTokens?: number;
  estimatedCost?: number;
  [key: string]: unknown;
}

interface MemorySummaryMeta {
  compressionApplied?: boolean;
  coveredExchangeCount?: number;
  summaryVersion?: number;
  compressionCount?: number;
  [key: string]: unknown;
}

export const AdminObservabilitySessionView: React.FC = () => {
  const { conversationId } = useParams<{ conversationId: string }>();
  const navigate = useNavigate();

  const [loadingSession, setLoadingSession] = useState(false);
  const [pollingSession, setPollingSession] = useState(false);
  const [activeSession, setActiveSession] = useState<SessionDetail | null>(null);
  const [pageError, setPageError] = useState('');
  const [rebuildingSummary, setRebuildingSummary] = useState(false);

  const pollTimerRef = useRef<number | null>(null);
  const sessionRequestInFlightRef = useRef(false);

  const assistantExchanges = useMemo(() => listAssistantExchanges(activeSession), [activeSession]);

  const loadSession = async (silent = false) => {
    if (!conversationId || sessionRequestInFlightRef.current) return;

    sessionRequestInFlightRef.current = true;
    if (silent) setPollingSession(true);
    else setLoadingSession(true);
    setPageError('');

    try {
      const data = await chatApi.getSession(conversationId);
      setActiveSession(data);
    } catch (error) {
      setActiveSession(null);
      setPageError(normalizeError(error, '加载会话详情失败'));
    } finally {
      sessionRequestInFlightRef.current = false;
      setLoadingSession(false);
      setPollingSession(false);
      schedulePolling();
    }
  };

  const schedulePolling = () => {
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    if (!activeSession?.running) return;

    pollTimerRef.current = window.setTimeout(() => {
      loadSession(true);
    }, 2500);
  };

  useEffect(() => {
    void (async () => {
      await loadSession();
    })();
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  useEffect(() => {
    schedulePolling();
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSession?.running]);

  const rebuildSummary = async () => {
    if (!conversationId || rebuildingSummary) return;

    setRebuildingSummary(true);
    setPageError('');

    try {
      const summary = await chatApi.rebuildConversationSummary(conversationId);
      if (activeSession?.conversationId === conversationId) {
        setActiveSession({ ...activeSession, memorySummary: summary as unknown as string });
      }
    } catch (error) {
      setPageError(normalizeError(error, '重建记忆摘要失败'));
    } finally {
      setRebuildingSummary(false);
    }
  };

  const exchangeTokenCount = (exchange: Record<string, unknown>) => {
    const traces = (exchange?.debugTrace as { modelUsageTraces?: ModelUsageTrace[] } | undefined)
      ?.modelUsageTraces || [];
    const total = traces.reduce((sum, item) => sum + Number(item.totalTokens || 0), 0);
    return total || '无';
  };

  const exchangeCost = (exchange: Record<string, unknown>) => {
    const traces = (exchange?.debugTrace as { modelUsageTraces?: ModelUsageTrace[] } | undefined)
      ?.modelUsageTraces || [];
    const total = traces.reduce((sum, item) => sum + Number(item.estimatedCost || 0), 0);
    return total > 0 ? `¥ ${total.toFixed(4)}` : '无';
  };

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
        <button 
          onClick={() => navigate('/admin/observability')}
          className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          返回会话列表
        </button>

        <div className="flex flex-wrap items-center gap-3">
          {(activeSession?.running || pollingSession) && (
            <span className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-primary/10 text-primary border border-primary/20 text-xs font-semibold">
              <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
              {pollingSession ? '实时轮询中' : '会话运行中'}
            </span>
          )}
          <button 
            onClick={() => loadSession()}
            disabled={loadingSession}
            className="px-4 py-2 bg-card border border-border/50 rounded-md text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors disabled:opacity-50"
          >
            {loadingSession ? '刷新中...' : '刷新会话详情'}
          </button>
          <button 
            onClick={rebuildSummary}
            disabled={!activeSession || rebuildingSummary}
            className="px-4 py-2 bg-foreground text-background hover:bg-foreground/90 rounded-md text-sm font-medium transition-colors disabled:opacity-50"
          >
            {rebuildingSummary ? '正在重建...' : '重建记忆摘要'}
          </button>
        </div>
      </div>

      {pageError && (
        <div className="p-4 bg-destructive/10 text-destructive rounded-lg text-sm border border-destructive/20">
          {pageError}
        </div>
      )}

      {loadingSession && !activeSession ? (
        <div className="p-12 text-center text-muted-foreground border border-dashed border-border/50 rounded-xl bg-card">
          正在加载会话详情...
        </div>
      ) : !activeSession ? (
        <div className="p-12 text-center text-muted-foreground border border-dashed border-border/50 rounded-xl bg-card">
          没有找到这条会话，请返回列表重新选择。
        </div>
      ) : (
        <>
          {/* Header */}
          <div className="border-b border-border/50 pb-6">
            <span className="text-xs font-mono text-muted-foreground uppercase tracking-widest">会话详情</span>
            <h2 className="text-2xl font-bold font-heading text-foreground mt-2 mb-3">
              {activeSession.selectedDocumentName || sessionTitle(activeSession)}
            </h2>
            <p className="text-sm text-muted-foreground max-w-3xl leading-relaxed mb-4">
              按轮次浏览整条会话，点击某一轮跳转到详情页查看执行链路。
            </p>
            <div className="flex flex-wrap gap-2">
              <span className="px-2 py-1 text-xs font-medium rounded bg-secondary border border-border/50 text-foreground">
                {formatChatMode(activeSession.chatMode)}
              </span>
              {activeSession.running ? (
                <span className="px-2 py-1 text-xs font-medium rounded bg-primary/10 border border-primary/20 text-primary">
                  当前会话仍在执行
                </span>
              ) : activeSession.latestTurnStatus && (
                <span className={`px-2 py-1 text-xs font-medium rounded ${getStatusColor(statusTone(activeSession.latestTurnStatus))}`}>
                  最近一轮{formatStatusLabel(activeSession.latestTurnStatus)}
                </span>
              )}
              <span className="px-2 py-1 text-xs font-medium rounded bg-secondary border border-border/50 text-muted-foreground font-mono">
                会话ID {activeSession.conversationId}
              </span>
            </div>
          </div>

          {/* Context Section */}
          <section className="pb-6 border-b border-border/50">
            <h3 className="text-lg font-semibold font-heading text-foreground mb-1">
              <span className="block text-xs font-mono text-muted-foreground uppercase tracking-widest mb-1">会话上下文</span>
              会话上下文
            </h3>
            <p className="text-sm text-muted-foreground mb-6">会话的最近状态、消息摘要和记忆压缩。</p>

            <dl className="grid grid-cols-1 gap-4 mb-6">
              <div className="flex flex-col sm:flex-row gap-2 sm:gap-6 py-3 border-b border-border/30">
                <dt className="text-sm text-muted-foreground shrink-0 sm:w-32">最近用户问题</dt>
                <dd className="text-sm text-foreground">{activeSession.latestUserMessage || '无'}</dd>
              </div>
              <div className="flex flex-col sm:flex-row gap-2 sm:gap-6 py-3 border-b border-border/30">
                <dt className="text-sm text-muted-foreground shrink-0 sm:w-32">最近助手回答</dt>
                <dd className="text-sm text-foreground">{sessionPreview(activeSession)}</dd>
              </div>
              <div className="flex flex-col sm:flex-row gap-2 sm:gap-6 py-3">
                <dt className="text-sm text-muted-foreground shrink-0 sm:w-32">消息数</dt>
                <dd className="text-sm text-foreground">{activeSession.messageCount || 0}</dd>
              </div>
            </dl>

            {(activeSession.memorySummary as unknown as MemorySummaryMeta | null | undefined)?.compressionApplied ? (
              <div className="mt-6 pt-6 border-t border-border/50">
                <h4 className="text-base font-semibold font-heading text-foreground mb-4">
                  <span className="block text-xs font-mono text-muted-foreground uppercase tracking-widest mb-1">记忆摘要</span>
                   记忆摘要
                </h4>
                <div className="flex flex-wrap gap-2 mb-4">
                  <span className="px-2 py-1 bg-secondary border border-border/50 text-muted-foreground rounded text-xs font-mono">
                    覆盖 {(activeSession.memorySummary as unknown as MemorySummaryMeta | null | undefined)?.coveredExchangeCount ?? 0} 轮
                  </span>
                  <span className="px-2 py-1 bg-secondary border border-border/50 text-muted-foreground rounded text-xs font-mono">
                    版本 {(activeSession.memorySummary as unknown as MemorySummaryMeta | null | undefined)?.summaryVersion ?? 0}
                  </span>
                  <span className="px-2 py-1 bg-secondary border border-border/50 text-muted-foreground rounded text-xs font-mono">
                    压缩 {(activeSession.memorySummary as unknown as MemorySummaryMeta | null | undefined)?.compressionCount ?? 0} 次
                  </span>
                </div>
                <pre className="bg-card p-4 rounded-lg text-sm text-foreground whitespace-pre-wrap font-mono border border-border/60 shadow-sm leading-relaxed">
                  {String((activeSession.memorySummary as unknown as MemorySummaryMeta | null | undefined)?.summaryText || '无')}
                </pre>
              </div>
            ) : (
              <div className="mt-4 p-4 bg-secondary/20 rounded-lg text-sm text-muted-foreground border border-dashed border-border/60">
                当前会话还没有形成记忆摘要。常见原因是轮次还不够，或者摘要尚未完成压缩。
              </div>
            )}
          </section>

          {/* Rounds Section */}
          <section>
            <h3 className="text-lg font-semibold font-heading text-foreground mb-1">
              <span className="block text-xs font-mono text-muted-foreground uppercase tracking-widest mb-1">轮次列表</span>
               会话轮次
            </h3>
            <p className="text-sm text-muted-foreground mb-6">点击某一轮跳转到详情页查看执行链路。</p>

            {!assistantExchanges.length ? (
              <div className="p-8 text-center text-muted-foreground border border-dashed border-border/50 rounded-xl bg-card">
                当前会话还没有助手轮次，无法展示执行链路。
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                {assistantExchanges.map((exchange: Record<string, unknown>, index: number) => {
                  const tone = statusTone(exchange.status);
                  return (
                    <div key={String(exchange.exchangeId ?? index)} className="flex gap-4">
                      {/* Timeline dot */}
                      <div className="flex flex-col items-center pt-2">
                        <div className={`w-3 h-3 rounded-full shrink-0 z-10 ${
                          tone === 'running' ? 'bg-primary animate-pulse' : 
                          tone === 'completed' ? 'bg-success' :
                          tone === 'failed' ? 'bg-destructive' : 'bg-warning'
                        }`} />
                        {index < assistantExchanges.length - 1 && (
                          <div className="w-0.5 flex-1 bg-border/60 mt-2" />
                        )}
                      </div>

                      {/* Content Card */}
                      <Link 
                        to={`/admin/observability/${conversationId}/exchange/${exchange.exchangeId}`}
                        className="flex-1 bg-card border border-border/40 rounded-xl p-5 shadow-sm hover:shadow-md hover:border-primary/30 transition-all group mb-2"
                      >
                        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 mb-4">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-bold text-foreground font-mono">第 {index + 1} 轮</span>
                            <span className={`px-2 py-1 text-xs font-medium rounded ${getStatusColor(tone)}`}>
                              {formatStatusLabel(exchange.status)}
                            </span>
                            {(exchange.debugTrace as { executionMode?: string } | undefined)?.executionMode && (
                              <span className="px-2 py-1 text-xs font-medium rounded bg-secondary border border-border/50 text-foreground">
                                {formatExecutionMode(
                                  (exchange.debugTrace as { executionMode?: string } | undefined)?.executionMode || ''
                                )}
                              </span>
                            )}
                          </div>
                          <span className="text-xs text-muted-foreground font-mono">{formatDateTime(exchange.editTime || exchange.createTime)}</span>
                        </div>

                        <div className="flex flex-col gap-2 mb-4">
                          <p className="text-sm text-foreground leading-relaxed">
                            <strong className="text-muted-foreground select-none">问：</strong>
                            {String(exchange.question || '未记录问题')}
                          </p>
                          <p className="text-sm text-foreground/80 leading-relaxed">
                            <strong className="text-muted-foreground/80 select-none">答：</strong>
                            {truncate(exchange.answer || '还没有回答内容', 200)}
                          </p>
                        </div>

                        <div className="flex flex-wrap gap-4 text-xs text-muted-foreground mb-4 font-mono">
                          <span>耗时 {exchange.totalResponseTimeMs ? `${exchange.totalResponseTimeMs} ms` : '无'}</span>
                          <span>引用 {(exchange.references as unknown[] | undefined)?.length || 0}</span>
                          <span>推荐 {(exchange.recommendations as unknown[] | undefined)?.length || 0}</span>
                          <span>Token {exchangeTokenCount(exchange)}</span>
                          <span>成本 {exchangeCost(exchange)}</span>
                        </div>

                        <span className="text-sm font-semibold text-primary group-hover:underline">
                          进入这一轮的详情页 →
                        </span>
                      </Link>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
};
