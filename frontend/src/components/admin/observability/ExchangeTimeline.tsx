import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import type { ExchangeItem } from '../../../types/api';
import { formatDateTime, formatStatusLabel, statusTone } from '../../../lib/observabilityHelpers';
import { AdminStatusBadge } from '../AdminStatusBadge';
import { formatCost, formatMs } from '../adminFormat';

interface ModelUsageTrace {
  totalTokens?: number;
  estimatedCost?: number;
}

interface DebugTraceShape {
  modelUsageTraces?: ModelUsageTrace[];
}

const TONE_MAP: Record<string, 'success' | 'warning' | 'destructive' | 'primary' | 'default'> = {
  success: 'success',
  completed: 'success',
  warning: 'warning',
  failed: 'destructive',
  error: 'destructive',
  running: 'primary',
};

function usageOf(exchange: ExchangeItem): { tokens: number; cost: number } {
  const trace = (exchange.debugTrace ?? null) as DebugTraceShape | null;
  const traces = Array.isArray(trace?.modelUsageTraces) ? trace!.modelUsageTraces! : [];
  return traces.reduce(
    (acc, item) => ({
      tokens: acc.tokens + Number(item?.totalTokens ?? 0),
      cost: acc.cost + Number(item?.estimatedCost ?? 0),
    }),
    { tokens: 0, cost: 0 }
  );
}

const Metric: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="flex flex-col gap-0.5">
    <dt className="text-2xs text-muted-foreground">{label}</dt>
    <dd className="font-mono text-xs tabular-nums text-foreground">{value}</dd>
  </div>
);

/** 单会话的轮次时间线：每轮给出耗时、引用数、token 与成本，便于定位慢在哪一轮 */
export const ExchangeTimeline: React.FC<{ conversationId: string; exchanges: ExchangeItem[] }> = ({
  conversationId,
  exchanges,
}) => {
  if (exchanges.length === 0) {
    return (
      <p className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
        这个会话还没有完成的问答轮次。等右上角状态不再是「运行中」后再刷新。
      </p>
    );
  }

  return (
    <ol className="flex flex-col gap-3">
      {exchanges.map((exchange, index) => {
        const usage = usageOf(exchange);
        const tone = statusTone(exchange.status);
        return (
          <li key={exchange.exchangeId} className="rounded-xl border border-border bg-card p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-secondary font-mono text-2xs text-secondary-foreground">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <p className="min-w-0 text-sm font-medium text-foreground first-letter:uppercase">
                  {exchange.question || '（没有问题文本）'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <AdminStatusBadge label={formatStatusLabel(exchange.status)} tone={TONE_MAP[String(tone)] ?? 'default'} />
                <Link
                  to={`/admin/observability/${conversationId}/exchange/${exchange.exchangeId}`}
                  className="inline-flex items-center gap-1 text-2xs text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  阶段明细
                  <ArrowUpRight size={12} aria-hidden="true" />
                </Link>
              </div>
            </div>

            <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
              {exchange.answer || exchange.errorMessage || '这轮没有回答内容。'}
            </p>

            <dl className="mt-3 grid grid-cols-2 gap-3 border-t border-border pt-3 sm:grid-cols-5">
              <Metric label="耗时" value={formatMs(exchange.totalResponseTimeMs ?? 0)} />
              <Metric label="引用" value={Array.isArray(exchange.references) ? exchange.references.length : 0} />
              <Metric label="推荐" value={Array.isArray(exchange.recommendations) ? exchange.recommendations.length : 0} />
              <Metric label="Token" value={usage.tokens || (exchange.tokensUsed ?? 0)} />
              <Metric label="成本" value={formatCost(usage.cost)} />
            </dl>
            <p className="mt-2 text-2xs text-muted-foreground">开始时间：{formatDateTime(exchange.createdAt)}</p>
          </li>
        );
      })}
    </ol>
  );
};
