import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { chatApi } from '../../lib/api';
import { formatChatMode, formatDateTime, formatStatusLabel, statusTone } from '../../lib/observabilityHelpers';
import { useAsyncData } from '../../lib/useAsyncData';
import { toast } from '../../lib/toast';
import { actionFailure, loadFailure } from '../../components/admin/adminFormat';
import type { SessionDetail } from '../../types/api';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { EmptyState } from '../../components/ui/EmptyState';
import { Skeleton } from '../../components/ui/Skeleton';
import { AdminPageHeader } from '../../components/admin/AdminPageHeader';
import { AdminStatusBadge } from '../../components/admin/AdminStatusBadge';
import { AdminStatGrid } from '../../components/admin/AdminStatGrid';
import { ExchangeTimeline } from '../../components/admin/observability/ExchangeTimeline';
import { SessionMemoryPanel } from '../../components/admin/observability/SessionMemoryPanel';

const POLL_INTERVAL = 2500;

const TONE_MAP: Record<string, 'success' | 'warning' | 'destructive' | 'primary' | 'default'> = {
  success: 'success',
  completed: 'success',
  warning: 'warning',
  failed: 'destructive',
  error: 'destructive',
  running: 'primary',
};

/** 单会话观测：轮次时间线 + 记忆摘要；运行中会话自动轮询，避免手动刷新 */
export const AdminObservabilitySessionView: React.FC = () => {
  const { conversationId = '' } = useParams();
  const navigate = useNavigate();
  const [rebuilding, setRebuilding] = useState(false);

  const { data: session, loading, error, refetch } = useAsyncData<SessionDetail>(
    () => chatApi.getSession(conversationId),
    [conversationId]
  );

  const running = Boolean(session?.running);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      refetch();
    }, POLL_INTERVAL);
    return () => window.clearInterval(timer);
  }, [running, refetch]);

  const rebuild = async () => {
    setRebuilding(true);
    try {
      await chatApi.rebuildConversationSummary(conversationId);
      toast({ title: '摘要已重建', description: '新的会话摘要会在下一轮问答时生效。', variant: 'success' });
      refetch();
    } catch (rebuildError) {
      toast({
        title: '重建摘要失败',
        description: actionFailure(rebuildError, '重建会话摘要', '请确认会话仍在，然后重试。'),
        variant: 'error',
      });
    } finally {
      setRebuilding(false);
    }
  };

  const exchanges = Array.isArray(session?.exchanges) ? [...session!.exchanges].reverse() : [];
  const totalTokens = exchanges.reduce((sum, item) => {
    const trace = (item.debugTrace ?? null) as { modelUsageTraces?: Array<{ totalTokens?: number }> } | null;
    const traces = Array.isArray(trace?.modelUsageTraces) ? trace!.modelUsageTraces! : [];
    return sum + traces.reduce((inner, usage) => inner + Number(usage?.totalTokens ?? 0), Number(item.tokensUsed ?? 0));
  }, 0);

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        eyebrow="对话观测"
        title={session?.title || '会话详情'}
        description={`会话 ID：${conversationId}`}
        actions={
          <>
            <Button size="sm" variant="outline" onClick={() => navigate('/admin/observability')}>
              <ArrowLeft size={13} aria-hidden="true" />
              返回列表
            </Button>
            <Button size="sm" variant="outline" onClick={() => refetch()} loading={loading}>
              <RefreshCw size={13} aria-hidden="true" />
              刷新
            </Button>
          </>
        }
      />

      {loading && !session ? (
        <Skeleton lines={8} />
      ) : error ? (
        <Alert
          variant="destructive"
          title="加载会话失败"
          action={<Button size="sm" variant="outline" onClick={() => refetch()}>重试</Button>}
        >
          {loadFailure(error, '会话详情')}
        </Alert>
      ) : !session ? (
        <EmptyState
          title="没有找到这个会话"
          description="会话可能已被删除。返回列表重新选择一个会话。"
          action={<Button size="sm" onClick={() => navigate('/admin/observability')}>返回会话列表</Button>}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <AdminStatusBadge label={formatChatMode(session.chatMode)} />
            <AdminStatusBadge
              label={formatStatusLabel(session.latestTurnStatus)}
              tone={TONE_MAP[String(statusTone(session.latestTurnStatus))] ?? 'default'}
            />
            {running ? (
              <span className="text-2xs text-muted-foreground">运行中，每 {POLL_INTERVAL / 1000}s 自动刷新</span>
            ) : null}
          </div>

          <AdminStatGrid
            stats={[
              { label: '问答轮次', value: Number(session.exchangeCount ?? exchanges.length) },
              { label: '消息条数', value: Number(session.messageCount ?? 0) },
              { label: '累计 Token', value: totalTokens, hint: '所有轮次模型用量合计' },
              { label: '最近更新', value: formatDateTime(session.updatedAt), hint: '按后端更新时间为准' },
            ]}
          />

          {session.latestTurnErrorMessage ? (
            <Alert variant="destructive" title="最近一轮失败">
              {session.latestTurnErrorMessage}
            </Alert>
          ) : null}

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.4fr_1fr]">
            <section className="flex flex-col gap-3">
              <h2 className="text-sm font-semibold text-foreground">轮次时间线</h2>
              <ExchangeTimeline conversationId={conversationId} exchanges={exchanges} />
            </section>
            <SessionMemoryPanel memorySummary={session.memorySummary || ''} rebuilding={rebuilding} onRebuild={rebuild} />
          </div>
        </>
      )}
    </div>
  );
};
