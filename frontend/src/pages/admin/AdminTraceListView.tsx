import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { manageApi } from '../../lib/api';
import type { TraceListItem, TracePageResponse } from '../../types/api';
import { Button } from '../../components/ui/Button';
import { Card, CardContent } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { formatTime, normalizeError, truncate } from '../../lib/observabilityHelpers';

const PAGE_SIZE = 15;

function statusTone(status: string): 'success' | 'destructive' | 'default' {
  if (status === 'ok') return 'success';
  if (status === 'error') return 'destructive';
  return 'default';
}

export const AdminTraceListView: React.FC = () => {
  const [page, setPage] = useState(1);
  const [conversationId, setConversationId] = useState('');
  const [status, setStatus] = useState('');
  const [data, setData] = useState<TracePageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await manageApi.getTraces({
        pageNo: page,
        pageSize: PAGE_SIZE,
        conversationId: conversationId.trim() || undefined,
        status: status || undefined
      });
      setError('');
      setData(res);
    } catch (e) {
      setError(normalizeError(e));
    } finally {
      setLoading(false);
    }
  }, [page, conversationId, status]);

  useEffect(() => {
    load();
  }, [load]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Trace 链路</h2>
        <div className="flex items-center gap-2">
          <input
            value={conversationId}
            onChange={(e) => {
              setConversationId(e.target.value);
              setPage(1);
            }}
            placeholder="按会话 ID 过滤"
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          >
            <option value="">全部状态</option>
            <option value="ok">正常</option>
            <option value="error">异常</option>
          </select>
          <Button
            variant="primary"
            onClick={() => {
              setLoading(true);
              void load();
            }}
            disabled={loading}
          >
            {loading ? '加载中...' : '刷新'}
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {/* 关键指标卡片 */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-gray-500">Trace 总数</p>
            <p className="mt-1 text-2xl font-semibold text-gray-900">
              {data?.stats.totalTraces ?? '—'}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-gray-500">今日新增</p>
            <p className="mt-1 text-2xl font-semibold text-gray-900">
              {data?.stats.todayTraces ?? '—'}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-gray-500">异常 Trace</p>
            <p className="mt-1 text-2xl font-semibold text-red-600">
              {data?.stats.errorTraces ?? '—'}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-gray-500">平均耗时 (ms)</p>
            <p className="mt-1 text-2xl font-semibold text-gray-900">
              {data ? Math.round(data.stats.avgRootDurationMs) : '—'}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
                <th className="px-4 py-3">Trace ID</th>
                <th className="px-4 py-3">会话</th>
                <th className="px-4 py-3">Span</th>
                <th className="px-4 py-3">耗时</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3">输出预览</th>
                <th className="px-4 py-3">时间</th>
              </tr>
            </thead>
            <tbody>
              {(data?.records ?? []).map((t: TraceListItem) => (
                <tr
                  key={t.traceId}
                  className="border-b border-gray-100 transition-colors hover:bg-gray-50"
                >
                  <td className="px-4 py-3">
                    <Link
                      to={`/admin/traces/${t.traceId}`}
                      className="font-mono text-xs text-blue-600 hover:underline"
                    >
                      {truncate(t.traceId, 20)}
                    </Link>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-600">
                    {truncate(t.conversationId, 18)}
                  </td>
                  <td className="px-4 py-3 text-gray-700">{t.spanCount}</td>
                  <td className="px-4 py-3 text-gray-700">
                    {t.durationMs != null ? `${Math.round(t.durationMs)} ms` : '—'}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={statusTone(t.status)}>{t.status}</Badge>
                  </td>
                  <td className="max-w-[220px] truncate px-4 py-3 text-xs text-gray-500">
                    {truncate(t.outputPreview, 60)}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {formatTime(t.createdAt)}
                  </td>
                </tr>
              ))}
              {!loading && (data?.records ?? []).length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-400">
                    暂无 trace 数据（对话未触发采样或尚无记录）
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <div className="flex items-center justify-between border-t border-gray-200 px-4 py-3">
            <span className="text-xs text-gray-500">共 {data?.total ?? 0} 条</span>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                上一页
              </Button>
              <span className="text-xs text-gray-600">
                {page} / {totalPages}
              </span>
              <Button
                variant="ghost"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                下一页
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
