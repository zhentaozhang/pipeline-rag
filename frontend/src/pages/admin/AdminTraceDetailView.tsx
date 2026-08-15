import React, { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { manageApi } from '../../lib/api';
import type { TraceDetail, TraceSpan } from '../../types/api';
import { Card, CardContent } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { formatTime, normalizeError } from '../../lib/observabilityHelpers';

const KIND_COLORS: Record<string, string> = {
  pipeline: 'bg-blue-100 text-blue-700',
  retrieval: 'bg-emerald-100 text-emerald-700',
  generation: 'bg-purple-100 text-purple-700',
  agent: 'bg-amber-100 text-amber-700',
  llm: 'bg-indigo-100 text-indigo-700',
  tool: 'bg-cyan-100 text-cyan-700'
};

const METRIC_LABELS: Record<string, string> = {
  faithfulness: '事实一致性',
  context_recall: '上下文召回',
  context_precision: '上下文精确率',
  answer_relevancy: '答案相关性',
  answer_correctness: '答案正确性'
};

function kindClass(kind: string): string {
  return KIND_COLORS[kind] ?? 'bg-gray-100 text-gray-600';
}

function spanTree(spans: TraceSpan[]): TraceSpan[] {
  // 按 parentSpanId 建立深度序（保持 started_at 顺序，根在顶）
  const depthMap = new Map<string, number>();
  const byId = new Map(spans.map((s) => [s.spanId, s]));
  const ordered: TraceSpan[] = [];
  for (const span of spans) {
    let depth = 0;
    let parent = span.parentSpanId ? byId.get(span.parentSpanId) : undefined;
    while (parent && depth < 20) {
      depth += 1;
      parent = parent.parentSpanId ? byId.get(parent.parentSpanId) : undefined;
    }
    depthMap.set(span.spanId, depth);
    ordered.push(span);
  }
  void depthMap;
  return ordered;
}

function renderValue(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export const AdminTraceDetailView: React.FC = () => {
  const { traceId = '' } = useParams<{ traceId: string }>();
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    manageApi
      .getTraceDetail(traceId)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e) => {
        if (!cancelled) setError(normalizeError(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [traceId]);

  const tree = useMemo(() => (detail ? spanTree(detail.spans) : []), [detail]);
  const totalMs = useMemo(() => {
    const roots = tree.filter((s) => !s.parentSpanId);
    return roots.reduce((acc, s) => acc + (s.durationMs ?? 0), 0);
  }, [tree]);

  if (loading) {
    return <div className="py-12 text-center text-sm text-gray-400">加载中...</div>;
  }
  if (error) {
    return <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>;
  }
  if (!detail) {
    return <div className="py-12 text-center text-sm text-gray-400">Trace 不存在</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Link
          to="/admin/traces"
          className="text-sm text-blue-600 hover:underline"
        >
          ← Trace 列表
        </Link>
        <h2 className="text-lg font-semibold text-gray-900">Trace 详情</h2>
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="grid grid-cols-2 gap-3 text-sm lg:grid-cols-4">
            <div>
              <p className="text-xs text-gray-500">Trace ID</p>
              <p className="mt-0.5 font-mono text-xs text-gray-800">{detail.traceId}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">会话 ID</p>
              <p className="mt-0.5 font-mono text-xs text-gray-800">{detail.conversationId}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Exchange</p>
              <p className="mt-0.5 text-gray-800">#{detail.exchangeId}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">总耗时</p>
              <p className="mt-0.5 text-gray-800">{totalMs} ms</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">创建时间</p>
              <p className="mt-0.5 text-gray-800">{formatTime(detail.createdAt)}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Span 数</p>
              <p className="mt-0.5 text-gray-800">{detail.spans.length}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Span 瀑布 */}
      <Card>
        <CardContent className="p-0">
          <div className="border-b border-gray-200 px-4 py-3 text-sm font-medium text-gray-700">
            Span 瀑布（{detail.spans.length}）
          </div>
          <ul className="divide-y divide-gray-100">
            {tree.map((span) => {
              const depth = span.parentSpanId ? 1 : 0;
              const isExpanded = expanded === span.spanId;
              const ratio =
                totalMs > 0 && span.durationMs != null
                  ? Math.min(100, Math.round((span.durationMs / totalMs) * 100))
                  : 0;
              return (
                <li key={span.spanId} className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    <span
                      className="inline-block h-2 w-2 rounded-full"
                      style={{ marginLeft: depth * 20 }}
                    />
                    <Badge variant={span.status === 'error' ? 'destructive' : 'default'}>
                      {span.status}
                    </Badge>
                    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${kindClass(span.kind)}`}>
                      {span.kind}
                    </span>
                    <button
                      className="text-sm font-medium text-gray-800 hover:text-blue-600"
                      onClick={() => setExpanded(isExpanded ? null : span.spanId)}
                    >
                      {span.name}
                    </button>
                    <span className="ml-auto text-xs text-gray-500">
                      {span.durationMs != null ? `${span.durationMs} ms` : '—'}
                    </span>
                  </div>
                  <div className="mt-1.5 ml-3 h-1.5 w-full max-w-md overflow-hidden rounded bg-gray-100">
                    <div
                      className={`h-full rounded ${
                        span.status === 'error' ? 'bg-red-400' : 'bg-blue-400'
                      }`}
                      style={{ width: `${ratio}%` }}
                    />
                  </div>
                  {isExpanded && (
                    <div className="mt-3 grid gap-2 pl-3 text-xs lg:grid-cols-2">
                      {span.input != null && (
                        <pre className="max-h-48 overflow-auto rounded bg-gray-50 p-2 text-gray-700">
                          {renderValue(span.input)}
                        </pre>
                      )}
                      {span.output != null && (
                        <pre className="max-h-48 overflow-auto rounded bg-gray-50 p-2 text-gray-700">
                          {renderValue(span.output)}
                        </pre>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </CardContent>
      </Card>

      {/* 评估分数 */}
      {detail.scores.length > 0 && (
        <Card>
          <CardContent className="p-4">
            <p className="mb-3 text-sm font-medium text-gray-700">评估分数</p>
            <div className="flex flex-wrap gap-3">
              {detail.scores.map((s) => (
                <div
                  key={s.scoreId}
                  className="rounded-lg border border-gray-200 px-4 py-2"
                >
                  <p className="text-xs text-gray-500">
                    {METRIC_LABELS[s.metricName] ?? s.metricName}
                  </p>
                  <p className="mt-0.5 text-lg font-semibold text-gray-900">
                    {(s.value ?? 0).toFixed(2)}
                  </p>
                  {s.reason && (
                    <p className="mt-1 max-w-xs text-xs text-gray-500">{s.reason}</p>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};
