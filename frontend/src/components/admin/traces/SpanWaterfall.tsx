import React, { useMemo, useState } from 'react';
import type { TraceSpan } from '../../../types/api';
import { formatMs } from '../adminFormat';
import { buildSpanTree } from './spanTree';

/** 不同 span 类型用语义令牌区分，避免硬编码色值在暗色主题下失效 */
function kindTone(kind: string): string {
  const lower = kind.toLowerCase();
  if (lower.includes('llm') || lower.includes('generation')) return 'bg-primary';
  if (lower.includes('retriev') || lower.includes('embed')) return 'bg-success';
  if (lower.includes('tool')) return 'bg-warning';
  if (lower.includes('chain') || lower.includes('span')) return 'bg-muted-foreground';
  return 'bg-primary/60';
}

const KIND_LABEL: Record<string, string> = {
  llm: '模型生成',
  generation: '模型生成',
  retrieval: '检索',
  embedding: '向量化',
  chain: '链路',
  tool: '工具调用',
  span: '步骤',
};

export const SpanWaterfall: React.FC<{ spans: TraceSpan[] }> = ({ spans }) => {
  const [expanded, setExpanded] = useState<string | null>(null);
  const nodes = useMemo(() => buildSpanTree(spans), [spans]);

  if (nodes.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
        这条链路没有记录任何 span。可能是采集中途失败，可以稍后重跑一次同样的请求。
      </p>
    );
  }

  const maxDuration = Math.max(...nodes.map((node) => Number(node.durationMs ?? 0)), 1);

  return (
    <ol className="flex flex-col gap-1">
      {nodes.map((node) => {
        const duration = Number(node.durationMs ?? 0);
        const width = Math.max(1.5, Math.round((duration / maxDuration) * 100));
        const open = expanded === node.spanId;
        return (
          <li key={node.spanId} className="rounded-lg border border-border bg-card">
            <button
              type="button"
              onClick={() => setExpanded(open ? null : node.spanId)}
              aria-expanded={open}
              className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-secondary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span style={{ paddingLeft: node.depth * 14 }} className="flex min-w-0 flex-1 items-center gap-2">
                <span aria-hidden="true" className={`h-1.5 w-1.5 shrink-0 rounded-full ${kindTone(node.kind)}`} />
                <span className="truncate text-xs font-medium text-foreground">{node.name}</span>
                <span className="shrink-0 rounded-md border border-border px-1.5 py-px text-2xs text-muted-foreground">
                  {KIND_LABEL[node.kind.toLowerCase()] ?? node.kind}
                </span>
                {node.status && node.status.toLowerCase() !== 'ok' ? (
                  <span className="shrink-0 rounded-md border border-destructive/30 px-1.5 py-px text-2xs text-destructive">
                    {node.status}
                  </span>
                ) : null}
              </span>
              <span className="w-24 shrink-0 font-mono text-2xs tabular-nums text-muted-foreground">{formatMs(duration)}</span>
            </button>
            <div className="mx-3 mb-2 h-1 overflow-hidden rounded-full bg-secondary" aria-hidden="true">
              <div className={`h-full rounded-full ${kindTone(node.kind)}`} style={{ width: `${width}%` }} />
            </div>
            {open ? (
              <div className="border-t border-border px-3 py-2.5">
                <dl className="grid grid-cols-2 gap-2 text-2xs sm:grid-cols-4">
                  <div>
                    <dt className="text-muted-foreground">span ID</dt>
                    <dd className="truncate font-mono text-foreground">{node.spanId}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">状态</dt>
                    <dd className="text-foreground">{node.status || '未知'}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">开始</dt>
                    <dd className="font-mono text-foreground">{node.startedAt || '—'}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">耗时</dt>
                    <dd className="font-mono tabular-nums text-foreground">{formatMs(duration)}</dd>
                  </div>
                </dl>
                <div className="mt-2 grid grid-cols-1 gap-2 lg:grid-cols-2">
                  {(
                    [
                      ['输入', node.input],
                      ['输出', node.output],
                    ] as const
                  ).map(([label, payload]) => (
                    <div key={label}>
                      <p className="text-2xs font-medium text-muted-foreground">{label}</p>
                      <pre className="mt-1 max-h-52 overflow-auto rounded-md border border-border bg-secondary/40 p-2 text-2xs leading-relaxed text-foreground">
                        {payload === null || payload === undefined
                          ? '（空）'
                          : typeof payload === 'string'
                            ? payload
                            : JSON.stringify(payload, null, 2)}
                      </pre>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
};