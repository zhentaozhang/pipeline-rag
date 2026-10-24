import React, { useState } from 'react';
import { manageApi } from '../../lib/api';
import type { RouteTrace } from '../../types/api';
import { Button } from '../../components/ui/Button';
import { FilterBar, FilterField, FilterSearch, FilterSelect } from '../../components/ui/FilterBar';
import { AdminPageHeader } from '../../components/admin/AdminPageHeader';
import { useAsyncData } from '../../lib/useAsyncData';
import { useUrlFilters } from '../../lib/useUrlFilters';
import { useDebouncedValue } from '../../components/admin/useDebouncedValue';
import { loadFailure } from '../../components/admin/adminFormat';
import { RouteTraceDetail } from '../../components/admin/knowledge/RouteTraceDetail';
import { RouteTraceList } from '../../components/admin/knowledge/RouteTraceList';
import { routeTraceKey } from '../../components/admin/knowledge/routeTraceMeta';

const PAGE_SIZE = 20;
const FILTER_DEFAULTS = { q: '', mode: '', status: '', page: '1' };

interface RouteTracePage {
  records: RouteTrace[];
  total: number;
}

/** 路由追踪：左侧列表 + 右侧详情，筛选条件写进 URL，刷新和后退都不会丢 */
export const AdminKnowledgeRouteTraceView: React.FC = () => {
  const [filters, updateFilters] = useUrlFilters(FILTER_DEFAULTS);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const conversationId = useDebouncedValue(filters.q, 350).trim();
  const pageNo = Math.max(1, Number(filters.page) || 1);

  const { data, loading, error, refetch } = useAsyncData<RouteTracePage>(
    async () => {
      const response = await manageApi.queryKnowledgeRouteTracePage({
        conversationId,
        mode: filters.mode,
        routeStatus: filters.status,
        pageNo: String(pageNo),
        pageSize: String(PAGE_SIZE),
      });
      return {
        records: Array.isArray(response?.records) ? response.records : [],
        total: Number(response?.total ?? 0),
      };
    },
    [conversationId, filters.mode, filters.status, pageNo]
  );

  const records = data?.records ?? [];
  const total = data?.total ?? 0;
  const selected = records.find((row) => routeTraceKey(row) === selectedKey) ?? null;
  const applied = Boolean(conversationId || filters.mode || filters.status);

  return (
    <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-4">
      <AdminPageHeader
        eyebrow="路由追踪"
        title="路由追踪"
        description="每一轮问答的路由决策记录：命中了哪个主题、置信度多少、问题被改写成什么。"
        actions={
          <Button variant="outline" loading={loading} onClick={() => refetch()}>
            刷新追踪
          </Button>
        }
      />

      <FilterBar
        actions={
          applied ? (
            <Button size="sm" variant="ghost" onClick={() => updateFilters({ q: '', mode: '', status: '', page: '1' })}>
              清除筛选
            </Button>
          ) : null
        }
      >
        <FilterSearch
          label="会话 ID"
          value={filters.q}
          onChange={(value) => updateFilters({ q: value, page: '1' })}
          placeholder="按会话 ID 筛选"
        />
        <FilterSelect
          label="路由模式"
          value={filters.mode}
          onChange={(value) => updateFilters({ mode: value, page: '1' })}
          options={[
            { value: '', label: '全部模式' },
            { value: 'shadow', label: 'shadow（影子）' },
            { value: 'auto', label: 'auto（自动）' },
          ]}
        />
        <FilterSelect
          label="路由状态"
          value={filters.status}
          onChange={(value) => updateFilters({ status: value, page: '1' })}
          options={[
            { value: '', label: '全部状态' },
            { value: '1', label: '成功' },
            { value: '2', label: '低置信' },
            { value: '3', label: '失败' },
          ]}
        />
        <FilterField label="本页条数">
          <span className="flex h-9 items-center text-xs text-muted-foreground">共 {total} 条</span>
        </FilterField>
      </FilterBar>

      <div className="flex min-h-0 flex-col gap-4 md:flex-row">
        <div className="flex h-[560px] w-full flex-col md:w-80 md:shrink-0 lg:w-96">
          <RouteTraceList
            rows={records}
            loading={loading}
            error={error ? loadFailure(error, '路由追踪列表') : ''}
            onRetry={() => refetch()}
            selectedKey={selectedKey}
            onSelect={setSelectedKey}
            page={pageNo}
            pageSize={PAGE_SIZE}
            total={total}
            onPageChange={(next) => updateFilters({ page: String(next) })}
          />
        </div>
        <div className="flex h-[560px] min-h-0 flex-1 flex-col">
          <RouteTraceDetail record={selected} />
        </div>
      </div>
    </div>
  );
};